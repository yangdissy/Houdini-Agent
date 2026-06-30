# -*- coding: utf-8 -*-
"""
奖励引擎 (Reward Engine)

每个任务完成后计算 reward score，驱动记忆强化/衰减。
类似人脑的多巴胺系统：
- 成功 → 强化
- 失败 → 衰减
- 犯错后纠正 → 特别强化（人脑对纠错特别敏感）
- 时间衰减 → 旧记忆自然淡化
"""

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .memory_store import MemoryStore, EpisodicRecord, get_memory_store
from shared.user_paths import normalize_username

# ============================================================
# 跨模块共享的 tag 常量
# ------------------------------------------------------------
# 这些 tag 在 reflection.py（生产）、reward_engine.py / growth_tracker.py
# （消费）之间流转。提取为常量避免字符串拼写漂移导致信号静默失效。
# ============================================================

TAG_ERROR_CORRECTION = "error_correction"   # 出错 → 纠正 → 成功
TAG_UNRESOLVED_ERROR = "unresolved_error"   # 出错且未解决

# ============================================================
# 奖励权重配置
# ============================================================

@dataclass
class RewardWeights:
    """奖励计算权重"""
    success: float = 0.4        # 任务成功权重
    efficiency: float = 0.25    # 效率权重
    novelty: float = 0.15       # 新颖度权重
    error_penalty: float = 0.2  # 错误惩罚权重


# ============================================================
# 奖励引擎
# ============================================================

class RewardEngine:
    """计算任务奖励分数并更新记忆重要度"""

    def __init__(self, store: Optional[MemoryStore] = None, weights: Optional[RewardWeights] = None):
        self.store = store or get_memory_store()
        self.weights = weights or RewardWeights()
        # 重要度更新阈值
        self.strengthen_threshold = 0.6   # reward > 此值 → 强化
        self.weaken_threshold = 0.3       # reward < 此值 → 衰减
        # 强化/衰减系数
        self.strengthen_factor = 1.2
        self.weaken_factor = 0.8
        self.error_correction_factor = 1.5  # 犯错后纠正的特殊强化
        # 缓存 embedder 引用，避免 hot path 每次反复 import + 走单例锁
        from .embedding import get_embedder
        self._embedder = get_embedder()

    # ==========================================================
    # 核心：计算 Reward Score
    # ==========================================================

    def calculate_reward(
        self,
        success: bool,
        error_count: int = 0,
        retry_count: int = 0,
        tool_call_count: int = 0,
        had_error_correction: bool = False,
        task_embedding=None,
    ) -> Dict[str, float]:
        """计算任务的 reward score 与分项分数

        Returns:
            dict 含 reward 与各分项：{reward, success, efficiency, novelty, error_penalty}
        """
        w = self.weights

        # 1. 成功分
        success_score = 1.0 if success else 0.0

        # 2. 效率分（0 次工具调用视为完美效率；retry 直接拉低）
        tc = max(0, tool_call_count)
        rc = max(0, retry_count)
        efficiency_score = 1.0 / (1.0 + 0.1 * tc + 0.3 * rc)

        # 3. 新颖度分（与已有记忆的最大相似度的反数）
        novelty_score = self._calculate_novelty(task_embedding)

        # 4. 错误惩罚
        error_penalty = min(1.0, error_count * 0.2)

        # 加权计算
        reward = (
            w.success * success_score
            + w.efficiency * efficiency_score
            + w.novelty * novelty_score
            - w.error_penalty * error_penalty
        )

        # 犯错后纠正的加成
        if had_error_correction and success:
            reward = min(1.0, reward * 1.2)

        # 裁剪到 [0, 1]
        reward = max(0.0, min(1.0, reward))

        return {
            "reward": reward,
            "success": success_score,
            "efficiency": efficiency_score,
            "novelty": novelty_score,
            "error_penalty": error_penalty,
        }

    def _calculate_novelty(self, task_embedding) -> float:
        """计算任务的新颖度

        与最近 N 条记忆的最大相似度的反数。
        新任务 → 高新颖度 → 更高 reward。
        """
        if task_embedding is None:
            return 0.5  # 默认中等新颖度

        recent = self.store.get_recent_episodic(limit=20)
        if not recent:
            return 1.0  # 无历史记忆 → 完全新颖

        max_sim = 0.0
        embedder = self._embedder
        for ep in recent:
            if ep.embedding is not None:
                sim = embedder.cosine_similarity(task_embedding, ep.embedding)
                max_sim = max(max_sim, sim)

        # 新颖度 = 1 - 最大相似度
        return max(0.0, 1.0 - max_sim)

    # ==========================================================
    # 记忆重要度更新
    # ==========================================================

    def update_importance(self, record: EpisodicRecord, reward: float) -> float:
        """根据 reward 更新记忆重要度

        Args:
            record: 事件记忆记录
            reward: 已计算的 reward score

        Returns:
            更新后的 importance 值
        """
        importance = record.importance

        # 基于 reward 的强化/衰减
        if reward >= self.strengthen_threshold:
            importance *= self.strengthen_factor
        elif reward < self.weaken_threshold:
            importance *= self.weaken_factor

        # 犯错后纠正的特殊强化
        if TAG_ERROR_CORRECTION in record.tags:
            importance *= self.error_correction_factor

        # 上限/下限
        importance = max(0.01, min(5.0, importance))

        # 写回数据库
        self.store.update_episodic_reward(record.id, reward, importance)

        return importance

    # ==========================================================
    # 全局时间衰减
    # ==========================================================

    def apply_time_decay(self, lambda_decay: float = 0.01):
        """对所有 episodic 记忆应用时间衰减

        importance *= exp(-lambda * days_since_creation)
        """
        self.store.decay_importance(lambda_decay)

    # ==========================================================
    # 完整的任务后处理
    # ==========================================================

    def process_task_completion(
        self,
        episodic_record: EpisodicRecord,
        tool_call_count: int = 0,
        run_maintenance: bool = False,
    ) -> Dict:
        """完整的任务后 reward 处理流程

        Args:
            episodic_record: 已创建但尚未计算 reward 的事件记忆
            tool_call_count: 工具调用总次数
            run_maintenance: 是否在本次调用中执行全局衰减/长期维护。
                默认 False — 维护职责交给上层调度（避免在热路径阻塞）。
                调用方可基于自己的节奏（条数、时间窗口、空闲信号）决定。

        Returns:
            处理结果字典，含 reward、分项分数、importance 等
        """
        # 检测是否有纠错行为
        had_error_correction = TAG_ERROR_CORRECTION in episodic_record.tags

        # 计算 reward（含分项分数）
        scores = self.calculate_reward(
            success=episodic_record.success,
            error_count=episodic_record.error_count,
            retry_count=episodic_record.retry_count,
            tool_call_count=tool_call_count,
            had_error_correction=had_error_correction,
            task_embedding=episodic_record.embedding,
        )
        reward = scores["reward"]

        # 更新 importance
        new_importance = self.update_importance(episodic_record, reward)

        result = {
            "reward": reward,
            "scores": scores,
            "importance": new_importance,
            "had_error_correction": had_error_correction,
            "total_episodes": self.store.count_episodic(),
            "memory_maintenance": None,
        }

        if run_maintenance:
            result["memory_maintenance"] = self.run_maintenance()

        return result

    def run_maintenance(self) -> Dict:
        """执行全局衰减 + 长期记忆维护。

        从 process_task_completion 拆出，便于上层按时间窗口/空闲调度调用，
        避免在每次任务完成的热路径上做大开销操作。
        """
        self.apply_time_decay()
        return self.store.maintain_long_term_memory()


# ============================================================
# 全局单例
# ============================================================

_engine_instances: Dict[str, RewardEngine] = {}
_engine_instances_lock = threading.RLock()

def get_reward_engine(username: Optional[str] = None) -> RewardEngine:
    """获取 RewardEngine 实例（按用户隔离，线程安全）。"""
    key = "default" if not username else normalize_username(username)
    with _engine_instances_lock:
        eng = _engine_instances.get(key)
        if eng is None:
            store = get_memory_store(username) if username else None
            eng = RewardEngine(store=store) if store else RewardEngine()
            _engine_instances[key] = eng
        return eng
