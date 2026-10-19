# -*- coding: utf-8 -*-
"""
反思模块 (Reflection Module)

混合反思策略：
1. 规则反思（每次任务后）：零成本，从工具调用链提取信号
2. LLM 深度反思（每 N 个任务或条件触发）：使用便宜模型生成抽象规则

这是 AI 的"成长引擎"——每次任务后自动运行。
"""

import json
import math
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

from .memory_store import (
    MEMORY_CATEGORIES,
    MemoryStore,
    EpisodicRecord,
    SemanticRecord,
    ProceduralRecord,
    get_memory_store,
)
from .reward_engine import (
    RewardEngine,
    get_reward_engine,
    TAG_ERROR_CORRECTION,
    TAG_UNRESOLVED_ERROR,
)
from shared.user_paths import normalize_username

# ============================================================
# 反思配置
# ============================================================

# LLM 深度反思间隔（每 N 个任务触发一次）
DEEP_REFLECT_INTERVAL = 5
# 错误率上升阈值（触发紧急反思）
ERROR_RATE_SPIKE_THRESHOLD = 0.5
# 低 reward 阈值（单个任务 reward 低于此值时触发深度反思，从失败/低质量任务中学习）
LOW_REWARD_REFLECT_THRESHOLD = 0.4

# LLM 反思 Prompt 模板
REFLECTION_PROMPT = """你是一个自我改进的 AI 助手。请分析以下最近完成的任务记录，提取可复用的经验规则。

## 任务记录
{episodic_summaries}

## 要求
分析这些任务，提取：
1. **通用经验规则**：从成功和失败中总结出的可复用规则
2. **策略更新**：哪些问题解决策略应该调整优先级
3. **技能置信度**：评估各领域的掌握程度

请以 JSON 格式输出（不要包含 ```json 标记）：
{{
  "semantic_rules": [
    {{"rule": "规则描述（精炼，120字以内）", "category": "分类(preference/command/debug/pitfall/workflow/knowledge/user_profile/general)", "abstraction_level": 2, "confidence": 0.8}}
  ],
  "strategy_updates": [
    {{"name": "策略名", "priority_delta": 0.1, "reason": "调整原因"}}
  ],
  "skill_confidence": {{
    "vex": 0.8,
    "node_creation": 0.9,
    "terrain": 0.5,
    "general": 0.7
  }}
}}
"""

# ============================================================
# 睡眠机制 Prompt 模板
# ============================================================

# 浅睡眠 — 每 N 轮对话触发
LIGHT_SLEEP_INTERVAL = 5

LIGHT_SLEEP_PROMPT = """你是一个 Houdini AI 助手的"记忆整理"模块。请分析以下最近的对话记录，提取值得长期保留的经验和知识。

## 最近对话
{conversation_text}

## 要求
从对话中提取值得长期记住的内容，包括：
1. **日常偏好**：用户的代码风格、输出语言、格式偏好、交互习惯
2. **构建命令**：编译、测试、部署、渲染等常用命令
3. **调试模式**：常见问题的调试思路和路径
4. **踩坑记录**：项目中遇到的特殊限制和陷阱
5. **工作流模式**：节点连接方式、操作序列
6. **技术知识**：Houdini 节点用法、VEX 代码模式、参数设置技巧
7. **用户画像**：用户的工作领域、技能水平

## 分类与层级说明
category 必须从以下 8 个值中选择：
- preference: 日常偏好（代码风格、输出语言、格式偏好）
- command: 构建命令（编译、测试、部署常用命令）
- debug: 调试模式（调试思路和路径）
- pitfall: 踩坑记录（特殊限制和陷阱）
- workflow: 工作流模式（节点连接、操作序列）
- knowledge: 技术知识（节点用法、VEX 语法）
- user_profile: 用户画像（工作领域、技能水平）
- general: 其他通用经验

abstraction_level 必须从 0-5 中选择：
- 0 = 核心身份：用户身份、核心偏好、语言习惯（极少、极精炼、极重要）
- 1 = 核心偏好：代码风格、格式偏好、交互习惯（高频复用）
- 2 = 经验规则：可复用经验、最佳实践、调试思路
- 3 = 工作流模式：具体工作流、命令序列、节点连接
- 4 = 具体案例：特定任务的成功/失败记录、踩坑详情
- 5 = 原始细节：对话片段、参数细节、临时记录
注意：level 0 应极度稀少，仅用于最核心的用户身份和偏好。大多数记忆应在 2-4 级。

请以 JSON 格式输出（不要包含 ```json 标记）：
{{
  "episodic_summary": "用一段话概括这几轮对话的核心内容和结果",
  "semantic_rules": [
    {{"rule": "提取的经验规则（精炼，120字以内）", "category": "分类", "abstraction_level": 2, "confidence": 0.7}}
  ],
  "key_facts": [
    "值得记住的关键事实或用户偏好"
  ]
}}
"""

# 深度睡眠 — 上下文压缩时触发
DEEP_SLEEP_PROMPT = """你是一个 Houdini AI 助手的"深度记忆整理"模块。当前上下文即将被压缩，请从完整对话中提取所有值得永久保留的知识。

## 完整对话上下文
{conversation_text}

## 要求
这是一次深度记忆整理，请尽可能全面地提取：
1. **日常偏好**：用户的代码风格、输出语言、格式偏好、交互习惯
2. **构建命令**：编译、测试、部署、渲染等常用命令
3. **调试模式**：常见问题的调试思路和路径
4. **踩坑记录**：项目中遇到的特殊限制和陷阱
5. **工作流模式**：完整的工作流程、节点连接方式、常用操作序列
6. **技术知识**：涉及的所有 Houdini 节点用法、VEX 代码模式、参数设置
7. **用户画像**：用户的工作领域、技能水平
8. **策略更新**：哪些问题解决策略被验证有效或无效

## 分类与层级说明
category 必须从以下 8 个值中选择：
- preference: 日常偏好（代码风格、输出语言、格式偏好）
- command: 构建命令（编译、测试、部署常用命令）
- debug: 调试模式（调试思路和路径）
- pitfall: 踩坑记录（特殊限制和陷阱）
- workflow: 工作流模式（节点连接、操作序列）
- knowledge: 技术知识（节点用法、VEX 语法）
- user_profile: 用户画像（工作领域、技能水平）
- general: 其他通用经验

abstraction_level 必须从 0-5 中选择：
- 0 = 核心身份：用户身份、核心偏好、语言习惯（极少、极精炼、极重要）
- 1 = 核心偏好：代码风格、格式偏好、交互习惯（高频复用）
- 2 = 经验规则：可复用经验、最佳实践、调试思路
- 3 = 工作流模式：具体工作流、命令序列、节点连接
- 4 = 具体案例：特定任务的成功/失败记录、踩坑详情
- 5 = 原始细节：对话片段、参数细节、临时记录
注意：level 0 应极度稀少，仅用于最核心的用户身份和偏好。大多数记忆应在 2-4 级。

请以 JSON 格式输出（不要包含 ```json 标记）：
{{
  "episodic_summary": "用两到三段话全面概括整个对话的内容、过程和结果",
  "semantic_rules": [
    {{"rule": "提取的经验规则（精炼，120字以内）", "category": "分类", "abstraction_level": 2, "confidence": 0.8}}
  ],
  "procedural_strategies": [
    {{"name": "策略名(英文snake_case)", "description": "策略描述", "conditions": ["适用条件"]}}
  ],
  "key_facts": [
    "值得永久记住的关键事实"
  ]
}}
"""


class ReflectionModule:
    """混合反思模块：规则反思 + 定期 LLM 深度反思"""

    def __init__(
        self,
        store: Optional[MemoryStore] = None,
        reward_engine: Optional[RewardEngine] = None,
    ):
        self.store = store or get_memory_store()
        self.reward_engine = reward_engine or get_reward_engine()
        self._task_count_since_reflect = 0
        self._recent_error_counts: List[int] = []  # 最近 N 个任务的错误次数
        self._max_recent = 10

    @staticmethod
    def _finite_number(value: Any, default: float, minimum: float, maximum: float) -> float:
        if isinstance(value, bool):
            return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(number):
            return default
        return max(minimum, min(maximum, number))

    @classmethod
    def _normalize_semantic_rules(
        cls,
        value: Any,
        default_confidence: float,
        default_level: int = 2,
    ) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []

        rules = []
        for item in value:
            if not isinstance(item, dict):
                continue
            rule = item.get("rule")
            if not isinstance(rule, str):
                continue
            rule = rule.strip()[:120]
            if not rule:
                continue
            category = item.get("category", "general")
            if category not in MEMORY_CATEGORIES:
                category = "general"
            confidence = cls._finite_number(
                item.get("confidence"), default_confidence, 0.0, 1.0
            )
            level = int(cls._finite_number(
                item.get("abstraction_level"), float(default_level), 0.0, 5.0
            ))
            rules.append({
                "rule": rule,
                "category": category,
                "confidence": confidence,
                "abstraction_level": level,
            })
        return rules

    @staticmethod
    def _normalize_text_list(value: Any, max_length: int = 120) -> List[str]:
        if not isinstance(value, list):
            return []
        return [
            item.strip()[:max_length]
            for item in value
            if isinstance(item, str) and item.strip()
        ]

    @classmethod
    def _normalize_strategy_updates(cls, value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        updates = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            delta = cls._finite_number(item.get("priority_delta"), 0.0, -1.0, 1.0)
            if delta:
                updates.append({"name": name.strip(), "priority_delta": delta})
        return updates

    @classmethod
    def _normalize_skill_confidence(cls, value: Any) -> Dict[str, float]:
        if not isinstance(value, dict):
            return {}
        result = {}
        for name, confidence in value.items():
            if not isinstance(name, str) or not name.strip() or isinstance(confidence, bool):
                continue
            try:
                number = float(confidence)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                result[name.strip()] = max(0.0, min(1.0, number))
        return result

    @classmethod
    def _normalize_procedural_strategies(cls, value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        strategies = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            description = item.get("description")
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(description, str) or not description.strip():
                continue
            strategies.append({
                "name": name.strip(),
                "description": description.strip(),
                "conditions": cls._normalize_text_list(item.get("conditions")),
            })
        return strategies

    # ==========================================================
    # 规则反思（每次任务后，零成本）
    # ==========================================================

    def rule_reflect(self, episodic: EpisodicRecord, tool_calls: List[Dict]) -> EpisodicRecord:
        """规则反思：从工具调用链提取信号并更新 episodic tags

        Args:
            episodic: 事件记忆记录
            tool_calls: 工具调用序列 [{"name": ..., "success": ..., "error": ...}, ...]

        Returns:
            更新后的 episodic 记录
        """
        tags = list(episodic.tags)

        # 1. 检测重试次数
        retry_count = episodic.retry_count
        if retry_count > 2:
            tags.append("retry_heavy")

        # 2. 检测错误后成功（纠错行为）
        has_error = False
        has_success_after_error = False
        for tc in tool_calls:
            if tc.get("error") or not tc.get("success", True):
                has_error = True
            elif has_error and tc.get("success", True):
                has_success_after_error = True
                break

        if has_error and has_success_after_error and episodic.success:
            tags.append(TAG_ERROR_CORRECTION)

        if has_error and not episodic.success:
            tags.append(TAG_UNRESOLVED_ERROR)

        # 3. 检测复杂任务（工具调用 > 10）
        if len(tool_calls) > 10:
            tags.append("complex_task")

        # 4. 检测高效任务（工具调用 <= 3 且成功）
        if len(tool_calls) <= 3 and episodic.success:
            tags.append("efficient_task")

        # 5. 分析工具类型
        tool_names = [tc.get("name", "") for tc in tool_calls]
        if any("vex" in n.lower() or "wrangle" in n.lower() for n in tool_names):
            tags.append("vex_related")
        if any("create_node" in n for n in tool_names):
            tags.append("node_creation")
        if any("terrain" in n.lower() or "heightfield" in n.lower() for n in tool_names):
            tags.append("terrain_related")

        # 去重
        tags = list(dict.fromkeys(tags))
        episodic.tags = tags

        return episodic

    # ==========================================================
    # 完整的任务后反思流程
    # ==========================================================

    def reflect_on_task(
        self,
        session_id: str,
        task_description: str,
        result_summary: str,
        success: bool,
        error_count: int,
        retry_count: int,
        tool_calls: List[Dict],
        ai_client: Any = None,
        model: str = "deepseek-chat",
        provider: str = "deepseek",
    ) -> Dict:
        """完整的任务后反思流程

        Args:
            session_id: 会话 ID
            task_description: 任务描述（用户请求摘要）
            result_summary: 结果摘要
            success: 是否成功
            error_count: 错误次数
            retry_count: 重试次数
            tool_calls: 工具调用序列
            ai_client: AI 客户端实例（用于 LLM 深度反思）
            model: 反思用的模型
            provider: 反思用的提供商

        Returns:
            反思结果字典
        """
        result = {
            "episodic_id": None,
            "reward": 0.0,
            "importance": 1.0,
            "tags": [],
            "deep_reflected": False,
            "new_rules": [],
        }

        try:
            # 1. 创建 episodic 记忆
            episodic = EpisodicRecord(
                session_id=session_id,
                task_description=task_description,
                actions=[
                    {"name": tc.get("name", ""), "success": tc.get("success", True)}
                    for tc in tool_calls
                ],
                result_summary=result_summary,
                success=success,
                error_count=error_count,
                retry_count=retry_count,
            )

            # 2. 规则反思（提取信号标签）
            episodic = self.rule_reflect(episodic, tool_calls)
            result["tags"] = episodic.tags

            # 3. 写入 episodic 记忆
            self.store.add_episodic(episodic)
            result["episodic_id"] = episodic.id

            # 4. Reward 计算 + importance 更新
            #    维护（全局衰减 + 长期记忆整理）由本模块按节奏调度，
            #    避免在每次任务热路径上做大开销操作。
            total_after = self.store.count_episodic()
            run_maint = total_after > 0 and total_after % 20 == 0
            reward_result = self.reward_engine.process_task_completion(
                episodic_record=episodic,
                tool_call_count=len(tool_calls),
                run_maintenance=run_maint,
            )
            result["reward"] = reward_result["reward"]
            result["importance"] = reward_result["importance"]
            result["scores"] = reward_result.get("scores")
            result["memory_maintenance"] = reward_result.get("memory_maintenance")

            # 5. 更新统计
            self._task_count_since_reflect += 1
            self._recent_error_counts.append(error_count)
            if len(self._recent_error_counts) > self._max_recent:
                self._recent_error_counts = self._recent_error_counts[-self._max_recent:]

            # 6. 判断是否触发 LLM 深度反思
            should_deep_reflect = self._should_deep_reflect(reward_result["reward"])
            if should_deep_reflect and ai_client is not None:
                try:
                    deep_result = self._deep_reflect(ai_client, model, provider)
                    result["deep_reflected"] = deep_result.get("success", False)
                    result["new_rules"] = deep_result.get("new_rules", [])
                    if deep_result.get("error"):
                        result["deep_reflection_error"] = deep_result["error"]
                    if deep_result.get("strategy_updates"):
                        result["strategy_updates"] = deep_result["strategy_updates"]
                    if deep_result.get("skill_confidence"):
                        result["skill_confidence"] = deep_result["skill_confidence"]
                except Exception as e:
                    print(f"[Reflection] LLM 深度反思失败: {e}")
                    traceback.print_exc()

        except Exception as e:
            print(f"[Reflection] 反思流程出错: {e}")
            traceback.print_exc()

        return result

    # ==========================================================
    # LLM 深度反思
    # ==========================================================

    def _should_deep_reflect(self, reward: Optional[float] = None) -> bool:
        """判断是否应该触发 LLM 深度反思"""
        # 1. 每 N 个任务
        if self._task_count_since_reflect >= DEEP_REFLECT_INTERVAL:
            return True

        # 2. 错误率突增
        if len(self._recent_error_counts) >= 3:
            recent = self._recent_error_counts[-3:]
            error_rate = sum(1 for e in recent if e > 0) / len(recent)
            if error_rate >= ERROR_RATE_SPIKE_THRESHOLD:
                return True

        # 3. 单个任务 reward 偏低 → 立即深度反思，从低质量任务中学习
        #    （不必等满 5 个任务，避免错过教训）
        if reward is not None and reward < LOW_REWARD_REFLECT_THRESHOLD:
            return True

        return False

    def _deep_reflect(self, ai_client: Any, model: str, provider: str) -> Dict:
        """执行 LLM 深度反思

        输入：最近 N 条 episodic memory
        输出：新的 semantic rules + procedural strategy 更新

        Args:
            ai_client: AIClient 实例
            model: 模型名称
            provider: 提供商

        Returns:
            {"new_rules": [...], "strategy_updates": [...]}
        """
        # 获取最近的 episodic 记忆
        recent_episodes = self.store.get_recent_episodic(limit=DEEP_REFLECT_INTERVAL * 2)
        if not recent_episodes:
            return {"success": False, "new_rules": []}

        # 构建摘要
        summaries = []
        for i, ep in enumerate(recent_episodes[:10], 1):
            status = "✅ 成功" if ep.success else "❌ 失败"
            tags_str = ", ".join(ep.tags) if ep.tags else "无"
            summaries.append(
                f"{i}. [{status}] 任务: {ep.task_description}\n"
                f"   结果: {ep.result_summary}\n"
                f"   错误次数: {ep.error_count}, 重试: {ep.retry_count}, Reward: {ep.reward_score:.2f}\n"
                f"   标签: {tags_str}"
            )

        episodic_text = "\n\n".join(summaries)
        prompt = REFLECTION_PROMPT.format(episodic_summaries=episodic_text)

        # 调用 LLM
        messages = [
            {"role": "system", "content": "你是一个自我改进的 AI 助手。请用 JSON 格式回答。"},
            {"role": "user", "content": prompt},
        ]

        full_response = ""
        try:
            for chunk in ai_client.chat_stream(
                messages=messages,
                model=model,
                provider=provider,
                temperature=0.3,
                max_tokens=1500,
                tools=None,
                enable_thinking=False,
                response_format={'type': 'json_object'},
            ):
                if chunk.get("type") == "content":
                    full_response += chunk.get("content", "")
                elif chunk.get("type") == "error":
                    print(f"[Reflection] LLM 反思错误: {chunk.get('error')}")
                    return {"success": False, "new_rules": []}
        except Exception as e:
            print(f"[Reflection] LLM 调用失败: {e}")
            return {"success": False, "new_rules": []}

        # 解析 JSON 响应
        result = self._parse_reflection_response(full_response, recent_episodes)
        if result.get("success"):
            self._task_count_since_reflect = 0
        return result

    def _parse_reflection_response(self, response: str, source_episodes: List[EpisodicRecord]) -> Dict:
        """解析 LLM 反思响应并写入记忆"""
        result = {
            "success": False,
            "new_rules": [],
            "strategy_updates": [],
            "error": "",
        }

        # 清理 JSON
        text = response.strip()
        # 移除可能的 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as initial_error:
            # 尝试提取 JSON 部分
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError as extracted_error:
                    result["error"] = "invalid_json"
                    print(
                        "[Reflection] 无法解析反思响应: "
                        f"chars={len(text)}, starts_object={text.startswith('{')}, "
                        f"ends_object={text.endswith('}')}, "
                        f"error_pos={extracted_error.pos}"
                    )
                    return result
            else:
                result["error"] = "json_object_not_found"
                print(
                    "[Reflection] 反思响应中未找到 JSON: "
                    f"chars={len(text)}, error_pos={initial_error.pos}"
                )
                return result

        if not isinstance(data, dict):
            result["error"] = "json_root_not_object"
            return result

        source_ids = [ep.id for ep in source_episodes]
        semantic_rules = self._normalize_semantic_rules(
            data.get("semantic_rules"), default_confidence=0.6
        )
        strategy_updates = self._normalize_strategy_updates(data.get("strategy_updates"))

        # 1. 处理 semantic rules（含 abstraction_level）
        for rule_data in semantic_rules:
            rule_text = rule_data["rule"]
            record = SemanticRecord(
                rule=rule_text,
                source_episodes=source_ids[:5],
                confidence=rule_data["confidence"],
                category=rule_data["category"],
                abstraction_level=rule_data["abstraction_level"],
            )
            saved, created = self.store.upsert_semantic(
                record,
                duplicate_threshold=0.80,
                confidence_increment=0.1,
            )
            if created:
                result["new_rules"].append(rule_text)
                print(f"[Reflection] 新规则: {rule_text[:50]}...")
            else:
                print(f"[Reflection] 强化已有规则: {saved.rule[:50]}... (conf={saved.confidence:.2f})")

        # 2. 处理策略更新
        for update in strategy_updates:
            name = update["name"]
            priority_delta = update["priority_delta"]
            existing = self.store.get_procedural_by_name(name)
            if existing:
                self.store.update_procedural_priority(existing.id, priority_delta)
                result["strategy_updates"].append(update)
                print(f"[Reflection] 策略更新: {name} priority += {priority_delta}")

        # 3. 处理技能置信度（存入 growth tracker，通过外部调用）
        skill_conf = self._normalize_skill_confidence(data.get("skill_confidence"))
        if skill_conf:
            result["skill_confidence"] = skill_conf

        result["success"] = True
        return result

    # ==========================================================
    # ★ 睡眠机制：对话级记忆整理
    # ==========================================================

    def light_sleep(
        self,
        session_id: str,
        recent_messages: List[Dict],
        ai_client: Any,
        model: str,
        provider: str,
    ) -> Dict:
        """浅睡眠：总结最近 N 轮对话写入长期记忆

        每产生 LIGHT_SLEEP_INTERVAL 次用户提问时触发。
        使用当前 LLM 将最近对话总结为 episodic + semantic 记忆。

        Args:
            session_id: 会话 ID
            recent_messages: 最近 N 轮的消息列表 (user/assistant/tool)
            ai_client: AI 客户端实例
            model: 当前使用的模型
            provider: 当前使用的提供商

        Returns:
            {"success": bool, "episodic_id": str, "new_rules": [...]}
        """
        result = {"success": False, "episodic_id": None, "new_rules": []}

        if not recent_messages:
            return result

        try:
            # 构建对话文本
            conv_text = self._messages_to_text(recent_messages, max_chars=4000)
            prompt = LIGHT_SLEEP_PROMPT.format(conversation_text=conv_text)

            # 调用 LLM
            response = self._call_llm(ai_client, prompt, model, provider, max_tokens=1500)
            if not response:
                return result

            # 解析并写入记忆
            data = self._parse_json_response(response)
            if not data:
                return result

            if not isinstance(data, dict):
                return result

            semantic_rules = self._normalize_semantic_rules(
                data.get("semantic_rules"), default_confidence=0.7
            )
            key_facts = self._normalize_text_list(data.get("key_facts"))

            # 1. 写入 episodic 记忆（对话级摘要）
            summary = data.get("episodic_summary", "")
            if summary:
                episodic = EpisodicRecord(
                    session_id=session_id,
                    task_description=f"[Sleep] 对话摘要 ({len(recent_messages)} msgs)",
                    result_summary=summary[:300],
                    success=True,
                    tags=["sleep_light", "conversation_summary"],
                    importance=1.5,  # 整理后的记忆重要度更高
                )
                self.store.add_episodic(episodic)
                result["episodic_id"] = episodic.id

            # 2. 写入 semantic 规则（含 abstraction_level）
            for rule_data in semantic_rules:
                rule_text = rule_data["rule"]
                record = SemanticRecord(
                    rule=rule_text,
                    source_episodes=[result["episodic_id"]] if result["episodic_id"] else [],
                    confidence=rule_data["confidence"],
                    category=rule_data["category"],
                    abstraction_level=rule_data["abstraction_level"],
                )
                _, created = self.store.upsert_semantic(
                    record,
                    duplicate_threshold=0.80,
                    confidence_increment=0.1,
                )
                if created:
                    result["new_rules"].append(rule_text)

            # 3. key_facts → 追加为 level=1 核心偏好 semantic 规则
            for fact in key_facts:
                if len(fact) > 5:
                    record = SemanticRecord(
                        rule=fact[:120],
                        source_episodes=[result["episodic_id"]] if result["episodic_id"] else [],
                        confidence=0.8,
                        category="preference",
                        abstraction_level=1,
                    )
                    _, created = self.store.upsert_semantic(
                        record,
                        duplicate_threshold=0.80,
                        confidence_increment=0.1,
                    )
                    if created:
                        result["new_rules"].append(fact[:120])

            result["success"] = True
            n_rules = len(result["new_rules"])
            print(f"[Sleep] 💤 浅睡眠完成: episodic={bool(summary)}, {n_rules} new rules")

        except Exception as e:
            print(f"[Sleep] 浅睡眠失败: {e}")
            traceback.print_exc()

        return result

    def deep_sleep(
        self,
        session_id: str,
        all_messages: List[Dict],
        ai_client: Any,
        model: str,
        provider: str,
    ) -> Dict:
        """深度睡眠：上下文压缩前，总结全部上下文写入长期记忆

        当上下文窗口触发自动压缩时强制触发。
        使用当前 LLM 将整个对话上下文深度总结为长期记忆。

        Args:
            session_id: 会话 ID
            all_messages: 完整的对话消息列表
            ai_client: AI 客户端实例
            model: 当前使用的模型
            provider: 当前使用的提供商

        Returns:
            {"success": bool, "episodic_id": str, "new_rules": [...], "new_strategies": [...]}
        """
        result = {"success": False, "episodic_id": None, "new_rules": [], "new_strategies": []}

        if not all_messages:
            return result

        try:
            # 构建对话文本（深度睡眠允许更长的输入）
            conv_text = self._messages_to_text(all_messages, max_chars=8000)
            prompt = DEEP_SLEEP_PROMPT.format(conversation_text=conv_text)

            # 调用 LLM（深度睡眠允许更长的输出）
            response = self._call_llm(ai_client, prompt, model, provider, max_tokens=3000)
            if not response:
                return result

            # 解析并写入记忆
            data = self._parse_json_response(response)
            if not data:
                return result

            semantic_rules = self._normalize_semantic_rules(
                data.get("semantic_rules"), default_confidence=0.8
            )
            procedural_strategies = self._normalize_procedural_strategies(
                data.get("procedural_strategies")
            )
            key_facts = self._normalize_text_list(data.get("key_facts"))

            # 1. 写入 episodic 记忆（深度摘要）
            summary = data.get("episodic_summary", "")
            if summary:
                episodic = EpisodicRecord(
                    session_id=session_id,
                    task_description=f"[DeepSleep] 上下文深度整理 ({len(all_messages)} msgs)",
                    result_summary=summary[:500],
                    success=True,
                    tags=["sleep_deep", "context_consolidation"],
                    importance=2.0,  # 深度整理的记忆重要度最高
                )
                self.store.add_episodic(episodic)
                result["episodic_id"] = episodic.id

            # 2. 写入 semantic 规则（含 abstraction_level）
            for rule_data in semantic_rules:
                rule_text = rule_data["rule"]
                record = SemanticRecord(
                    rule=rule_text,
                    source_episodes=[result["episodic_id"]] if result["episodic_id"] else [],
                    confidence=rule_data["confidence"],
                    category=rule_data["category"],
                    abstraction_level=rule_data["abstraction_level"],
                )
                _, created = self.store.upsert_semantic(
                    record,
                    duplicate_threshold=0.80,
                    confidence_increment=0.15,
                )
                if created:
                    result["new_rules"].append(rule_text)

            # 3. 写入 procedural 策略
            for strat_data in procedural_strategies:
                name = strat_data["name"]
                desc = strat_data["description"]

                existing = self.store.get_procedural_by_name(name)
                if existing:
                    continue
                else:
                    record = ProceduralRecord(
                        strategy_name=name,
                        description=desc,
                        priority=0.6,
                        conditions=strat_data.get("conditions", []),
                    )
                    self.store.add_procedural(record)
                    result["new_strategies"].append(name)

            # 4. key_facts → level=1 核心偏好
            for fact in key_facts:
                if len(fact) > 5:
                    record = SemanticRecord(
                        rule=fact[:120],
                        source_episodes=[result["episodic_id"]] if result["episodic_id"] else [],
                        confidence=0.85,
                        category="preference",
                        abstraction_level=1,
                    )
                    _, created = self.store.upsert_semantic(
                        record,
                        duplicate_threshold=0.80,
                        confidence_increment=0.15,
                    )
                    if created:
                        result["new_rules"].append(fact[:120])

            result["success"] = True
            n_rules = len(result["new_rules"])
            n_strats = len(result["new_strategies"])
            print(f"[Sleep] 😴 深度睡眠完成: episodic={bool(summary)}, "
                  f"{n_rules} new rules, {n_strats} new strategies")

        except Exception as e:
            print(f"[Sleep] 深度睡眠失败: {e}")
            traceback.print_exc()

        return result

    # ==========================================================
    # 睡眠辅助方法
    # ==========================================================

    @staticmethod
    def _messages_to_text(messages: List[Dict], max_chars: int = 4000) -> str:
        """将消息列表转换为可读文本（供 LLM 分析）"""
        if max_chars <= 0:
            return ""

        lines = []
        for msg in messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')

            # 跳过无内容的消息
            if not content:
                # assistant with tool_calls → 标注
                if role == 'assistant' and msg.get('tool_calls'):
                    tc_names = [tc.get('function', {}).get('name', '?')
                                for tc in msg.get('tool_calls', [])]
                    line = f"[Assistant] 调用工具: {', '.join(tc_names)}"
                else:
                    continue
            elif role == 'system':
                continue  # 跳过 system 消息（不需要记忆系统提示词）
            elif role == 'user':
                # 多模态内容
                if isinstance(content, list):
                    text_parts = [p.get('text', '') for p in content
                                  if isinstance(p, dict) and p.get('type') == 'text']
                    content = ' '.join(t for t in text_parts if t)
                    if not content:
                        content = "[图片消息]"
                line = f"[User] {content}"
            elif role == 'assistant':
                # 去掉 think 标签
                import re
                content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
                if not content:
                    continue
                line = f"[Assistant] {content}"
            elif role == 'tool':
                tool_name = msg.get('name', 'unknown')
                # 压缩工具结果
                if len(content) > 200:
                    content = content[:200] + "..."
                line = f"[Tool:{tool_name}] {content}"
            else:
                continue

            lines.append(line)

        if not lines:
            return ""

        full_text = "\n".join(lines)
        if len(full_text) <= max_chars:
            return full_text

        omitted = "... (更早的内容已省略)"
        available = max_chars - len(omitted) - 1
        if available <= 0:
            return omitted[:max_chars]

        selected = []
        total = 0
        for line in reversed(lines):
            separator = 1 if selected else 0
            if total + separator + len(line) > available:
                if not selected:
                    selected.append(line[:available])
                break
            selected.append(line)
            total += separator + len(line)

        selected.reverse()
        return omitted + "\n" + "\n".join(selected)

    def _call_llm(self, ai_client: Any, prompt: str, model: str,
                  provider: str, max_tokens: int = 1500) -> str:
        """调用 LLM 并返回完整响应文本"""
        messages = [
            {"role": "system", "content": "你是一个 AI 助手的记忆整理模块。请用 JSON 格式回答。"},
            {"role": "user", "content": prompt},
        ]

        full_response = ""
        try:
            for chunk in ai_client.chat_stream(
                messages=messages,
                model=model,
                provider=provider,
                temperature=0.3,
                max_tokens=max_tokens,
                tools=None,
                enable_thinking=False,
                response_format={'type': 'json_object'},
            ):
                if chunk.get("type") == "content":
                    full_response += chunk.get("content", "")
                elif chunk.get("type") == "error":
                    print(f"[Sleep] LLM 错误: {chunk.get('error')}")
                    return ""
        except Exception as e:
            print(f"[Sleep] LLM 调用失败: {e}")
            return ""

        return full_response

    @staticmethod
    def _parse_json_response(response: str) -> Optional[Dict]:
        """解析 LLM 的 JSON 响应"""
        import re
        text = response.strip()
        # 移除 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    return data if isinstance(data, dict) else None
                except json.JSONDecodeError:
                    pass
            print(f"[Sleep] 无法解析 JSON 响应")
            return None

    # ==========================================================
    # 工具方法
    # ==========================================================

    def get_reflection_stats(self) -> Dict:
        """获取反思统计信息"""
        return {
            "tasks_since_reflect": self._task_count_since_reflect,
            "recent_errors": self._recent_error_counts[-5:] if self._recent_error_counts else [],
            "next_deep_reflect_in": max(0, DEEP_REFLECT_INTERVAL - self._task_count_since_reflect),
        }


# ============================================================
# 全局单例
# ============================================================

_reflection_instances: Dict[str, ReflectionModule] = {}

def get_reflection_module(username: Optional[str] = None) -> ReflectionModule:
    """获取 ReflectionModule 实例（按用户隔离）。"""
    global _reflection_instances
    if not username:
        key = "default"
        if key not in _reflection_instances:
            _reflection_instances[key] = ReflectionModule()
        return _reflection_instances[key]

    uname = normalize_username(username)
    if uname not in _reflection_instances:
        store = get_memory_store(uname)
        engine = get_reward_engine(uname)
        _reflection_instances[uname] = ReflectionModule(store=store, reward_engine=engine)
    return _reflection_instances[uname]
