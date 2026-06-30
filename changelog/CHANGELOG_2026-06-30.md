# Houdini-Agent 更新记录（2026-06-30）

## 发布摘要

本次日期下两批独立改动：

1. **Rules Manager 硬化**（`houdini_agent/utils/rules_manager.py`）—— 数据安全 + 性能 + token 预算 + 并发健壮性。
2. **Reward Engine 重构**（`reward_engine.py` + `reflection.py` + `growth_tracker.py`）—— 正确性 + 可观测性 + 性能 + 线程安全。
3. **DeepSeek V4 / JSON Output 小增强**（`ai_client.py` + `reflection.py` + 测试）—— 补齐上游 v1.5.5 的 V4 thinking 参数、SiliconFlow DeepSeek V4 适配与 JSON mode 反思调用。

两批均不破坏 DB / 磁盘格式，外部 API 变化都已同步调用方。

---

# Rules Manager 硬化（同日第一批）

## 摘要

只动一个文件：`houdini_agent/utils/rules_manager.py`。聚焦**数据安全 + 性能 + token 预算 + 并发健壮性**四件事，外部 API 与磁盘文件格式完全兼容，调用方（`memory_mixin.py`、`cursor_widgets.py`）无需任何改动。

---

## 关键更新

### 1. UI 规则原子写入

**问题**：`_save_ui_rules` 之前直接 `open(file, "w")`。如果写入过程中崩溃（断电、Houdini kill、磁盘满），`config/user_rules.json` 会被截断为 0 字节空文件，**用户所有规则永久丢失**。

**修复**：改为「写 `.tmp` → `fsync` → `os.replace`」三段式。`os.replace` 在 Windows/POSIX 都是原子操作，要么旧文件、要么新文件，不会出现中间态。写入失败时清理 `.tmp` 残留。

### 2. 损坏文件自动备份（防覆盖丢失）

**问题**：`_load_ui_rules` 之前对 JSON 解析失败只是 `print` 一行后返回 `[]`。如果 `user_rules.json` 被外力损坏（git merge 冲突标记、手工编辑出错、磁盘扇区错误），加载得到空列表 → 用户下次操作触发保存 → 损坏文件被空内容覆盖，**永久丢失**。

**修复**：解析失败或顶层不是 list 时，把原文件重命名为 `user_rules.json.corrupt-<unix时间戳>` 再返回空。下次保存只会写新文件，旧规则可以从备份手动抢救。

### 3. 文件规则 mtime 缓存

**问题**：`get_rules_for_prompt()` 在**每次** AI 请求时被调用，里面 `_scan_file_rules()` 会无条件遍历 `rules/*.md`、`*.txt` 并 `read_text` 每个文件。Houdini 这种交互式场景下是不必要的磁盘 IO。

**修复**：新增 `_file_rules_signature()`，用目录下所有规则文件的 `(name, mtime_ns, size)` 元组作为指纹。`_scan_file_rules()` 先比对指纹，无变化时直接返回内存缓存，**完全跳过磁盘读取**。用户编辑 `rules/*.md` 后下次调用自动重扫，无需手动 reload。

### 4. Token 预算保护

**问题**：所有启用的规则会被**全文**注入到 system prompt。如果用户写了一条 100KB 的规则（或读到的文件很大），单次请求 token 成本爆炸，甚至可能超模型上下文窗口。

**修复**：
- `_MAX_RULE_CHARS = 8000`：单条规则超长则截断尾部并追加 `... [truncated]`。
- `_MAX_TOTAL_CHARS = 32000`：所有规则累加超预算后停止添加。
- 在 `<user_rules>` 头部加 note 告知 LLM 发生了截断/丢弃，避免它困惑「为什么规则戛然而止」。

### 5. 并发保护（RLock）

**问题**：`_ui_rules_cache` 是模块级 dict。UI 线程可能在编辑器里读写，AI 调用通常在后台 worker 线程注入 prompt。两线程对同一 list/dict 并发操作存在踩踏风险（Python GIL 不保护复合操作，比如「先读 cache 再修改」）。

**修复**：引入模块级 `threading.RLock()`，所有缓存读写、文件写入都在 `with _lock:` 内。RLock 允许同一线程重入（`add_rule` 内调 `_get_cache` 时不会自锁）。

### 6. 重构：消除 7 处重复的缓存懒加载样板

**问题**：之前 `get_all_rules` / `get_ui_rules` / `add_rule` / `update_rule` / `delete_rule` / `save_all_ui_rules` / `reload_rules` 七个函数每个开头都写一遍：

```python
key = _cache_key(username)
if key not in _ui_rules_cache:
    _ui_rules_cache[key] = _load_ui_rules(username)
```

**修复**：抽出 `_get_cache(username)` 助手。CRUD 函数体积平均减少 50%，逻辑更聚焦。

---

## 影响范围

| 文件 | 状态 |
|------|------|
| `houdini_agent/utils/rules_manager.py` | 修改 |
| 其他所有文件 | 不变 |

- **外部 API**：完全兼容，所有公开函数签名不变。
- **磁盘格式**：`config/user_rules.json` 结构不变。
- **`rules/*.md` 文件规则**：行为不变，但读取性能大幅提升（命中缓存时近零开销）。
- **`memory_mixin.py` / `cursor_widgets.py`**：调用方零修改。

## 兼容性

- 旧 `user_rules.json` 直接加载，无需迁移。
- 旧的损坏文件首次加载时会被自动备份为 `*.corrupt-*`，用户可手动恢复。
- 极少数情况下，若用户曾手工把 `user_rules.json` 改成非 list（如对象），本次会触发备份逻辑（这是期望行为，不是回归）。

---

# Reward Engine 重构（同日第二批）

## 摘要

聚焦 `houdini_agent/utils/reward_engine.py` 的**正确性 + 可观测性 + 性能 + 线程安全**，连带触及 `reflection.py` / `growth_tracker.py` 的字符串常量统一。外部 API 仅 `calculate_reward` 返回类型变化（float → dict），唯一调用方 `reflection.py` 已同步更新。

---

## 关键更新

### 1. 修复：0 工具调用时效率分被错误压低

**问题**：`calculate_reward` 中 `if tool_call_count <= 0: tool_call_count = 1`。纯对话任务（不调用任何工具）的 `efficiency_score` 被强制变成 `1/1.1 ≈ 0.91`，而不是预期的 1.0。语义上"零工具 = 完美效率"被破坏。

**修复**：去掉强转，公式 `1.0 / (1.0 + 0.1 * tc + 0.3 * rc)` 在 `tc=0, rc=0` 时自然返回 1.0。同时改用 `max(0, …)` 防御负数。

### 2. 拆分：维护职责移出热路径

**问题**：`process_task_completion` 在每次任务后用 `total % 10 == 0` / `total % 20 == 0` 自动触发全局 time-decay 和长期记忆维护。`total` 是累计总条数 —— 一旦清理过旧记忆，序列不连续，可能永久错过触发窗口。而且热路径上做大开销维护本身就不合适。

**修复**：
- `process_task_completion` 新增 `run_maintenance=False` 参数，默认不再自动跑维护。
- 抽出独立的 `RewardEngine.run_maintenance()` 方法。
- 调度责任移到 [reflection.py](houdini_agent/utils/reflection.py)：在 `reflect_on_task` 内显式判断 `total % 20 == 0` 后传入 `run_maintenance=True`，路径可见、可测、可替换。

### 3. 持久化分项分数（可观测性）

**问题**：`calculate_reward` 只返回最终 `reward: float`。下游做"为什么这条记忆被强化/衰减"的可解释性、做权重调参实验时，无法知道 success / efficiency / novelty / error_penalty 各自贡献多少。

**修复**：
- `calculate_reward` 返回类型从 `float` 改为 `Dict[str, float]`，含 `{reward, success, efficiency, novelty, error_penalty}` 五个分项。
- `process_task_completion` 透传 `scores` 字段到上层。
- `reflection.reflect_on_task` 将 `scores` 写入返回 dict，深度反思 prompt、日志、调参实验都可直接使用。
- **不动 DB schema**：通过返回 dict 暴露，避免 ALTER TABLE 给所有用户加迁移负担。

### 4. 单例工厂线程安全

**问题**：`_engine_instances` 模块级字典在多线程访问下（`MemoryMixin._init_memory_system` 在后台线程初始化）存在 check-then-set 竞态，可能创建多个实例打开同一 SQLite DB。

**修复**：引入 `_engine_instances_lock = threading.RLock()`，`get_reward_engine` 内部用 `with lock:` 包住读写。同时统一 default 分支和用户分支的代码路径（之前两条分支独立判断）。

### 5. 共享 tag 常量（防字符串拼写漂移）

**问题**：`"error_correction"` / `"unresolved_error"` 这两个 tag 在 `reflection.py` 生产、`reward_engine.py` + `growth_tracker.py` 消费 —— 任何一处拼错都会**静默失效**（纠错信号不再被强化、风险容忍度不再调整），且没有任何告警。

**修复**：在 `reward_engine.py` 顶层导出 `TAG_ERROR_CORRECTION` / `TAG_UNRESOLVED_ERROR` 两个常量，三个文件 5 处魔法字符串全部替换为常量引用。

### 6. Hot path 性能：embedder 缓存到 `__init__`

**问题**：`_calculate_novelty` 每次任务结束都执行 `from .embedding import get_embedder; embedder = get_embedder()`。`get_embedder` 是带锁的全局单例工厂 —— 每次任务都走一次锁开销纯属浪费。

**修复**：在 `RewardEngine.__init__` 中 `self._embedder = get_embedder()` 一次取好；`_calculate_novelty` 改用 `self._embedder`。

---

## 影响范围

| 文件 | 状态 |
|------|------|
| `houdini_agent/utils/reward_engine.py` | 修改 |
| `houdini_agent/utils/reflection.py` | 修改（消费新的 `scores` 字段、调度维护、引用 tag 常量） |
| `houdini_agent/utils/growth_tracker.py` | 修改（引用 tag 常量） |
| `cache/memory/agent_memory.db` schema | **不变** |

- **API 兼容性**：`calculate_reward` 返回类型变化是唯一不兼容点。已确认 `reflection.py` 是唯一调用方，已同步。`process_task_completion` 的 `run_maintenance` 是新增可选参数，默认 False 改变了维护节奏 —— 调度责任已在 `reflection.py` 内补回原 `% 20` 节奏。
- **DB schema**：不变，分项分数走返回值通道，不持久化。

## 回归验证

冒烟测试覆盖：
- 0 工具调用 efficiency = 1.0
- 多工具 + 重试时 efficiency 下降
- 失败 + 错误时 reward 显著降低
- `calculate_reward` 返回 5 个分项字段齐全
- 默认 `run_maintenance=False` 时 `maintain_long_term_memory` 不被调用
- 显式 `run_maintenance=True` 才触发维护
- 16 线程并发 `get_reward_engine("alice")` 返回同一实例
- `TAG_ERROR_CORRECTION` / `TAG_UNRESOLVED_ERROR` 跨 3 个模块为同一对象
- `get_embedder` 在 `__init__` 期间只调用 1 次，后续 `calculate_reward` 不再调用

## 暂缓未做

以下几项之前评估过，需要先有指标支撑或属于项目级改动，未纳入本次：

- 纠错信号在 reward 阶段（×1.2）+ importance 阶段（×1.5）双重放大 —— 看 `growth_tracker.py` 也对 `error_correction` 做了 `risk_tolerance` 加成，**可能是有意的多巴胺放大设计**，改前应有指标支撑。
- `success: bool` → `task_quality: float` —— 需要上游建立质量评分机制，项目级改动。
- 权重从 `config/houdini_ai.ini` 读取 —— 目前没有在跑调参实验，YAGNI。
- `error_count` 在 success_score=0 之外又扣 error_penalty —— 错误被罚两次，但 reward 已被裁剪到 [0,1]，体感问题不明显。

---

# DeepSeek V4 / JSON Output 小增强（同日第三批）

## 摘要

本批只做上游 v1.5.5 的 API 层快赢项，**不引入 Meshy / QML / Bridge / 独立程序**，也暂不做长期记忆全局开关（Phase 3 已明确暂缓）。目标是补齐 DeepSeek V4 thinking 参数，覆盖 SiliconFlow 中转的 DeepSeek V4 模型，并让反思/睡眠整理走 API 级 JSON Output。

---

## 关键更新

### 1. DeepSeek V4 thinking 参数补齐

**问题**：项目已经有 `deepseek-v4-flash` / `deepseek-v4-pro` 模型与定价配置，但请求 payload 没有发送 V4 的显式 thinking 参数；`v4-pro` 也没有发送 `reasoning_effort='high'`。

**修复**：
- `chat_stream()` 对 DeepSeek V4 发送 `thinking: {"type": "enabled"}`。
- `v4-pro` 额外发送 `reasoning_effort: "high"`。
- `chat()` 非流式路径同步支持，避免反思、测试连接或兼容旧调用时能力不一致。

### 2. SiliconFlow DeepSeek V4 覆盖

**问题**：SiliconFlow 里也配置了 DeepSeek V4：

```text
deepseek-ai/DeepSeek-V4-Pro
deepseek-ai/DeepSeek-V4-Flash
```

如果只判断 `provider == 'deepseek'`，硅基流动路径会漏掉 V4 thinking 参数。

**修复**：新增轻量模型识别 helper，按模型名识别 DeepSeek V4，而不是只按 provider：

- `_is_deepseek_v4_model(model)`
- `_is_deepseek_v4_pro_model(model)`

现在原生 DeepSeek 与 SiliconFlow 的 V4-Pro / V4-Flash 都走同一套 thinking / reasoning_effort 逻辑。

### 3. reasoning_content 回灌支持 SiliconFlow

**问题**：agent loop 把 `reasoning_content` 回灌到下一轮 assistant message 时，原先只允许 `provider in ('deepseek', 'glm')`。SiliconFlow 的 DeepSeek 推理模型即使返回 reasoning，也可能在后续轮次被丢掉。

**修复**：两处回灌判定扩展为：

```python
provider in ('deepseek', 'glm', 'siliconflow')
```

覆盖普通 agent loop 与 JSON-mode tool-call loop。

### 4. `response_format` / JSON Output 支持

**问题**：反思模块要求 LLM 输出 JSON，但之前只靠系统提示词「请用 JSON 格式回答」，模型偶发包 Markdown fence、解释文本或半结构化内容时，解析稳定性不足。

**修复**：
- `AIClient.chat_stream()` 新增 `response_format: Optional[dict] = None`。
- `AIClient.chat()` 新增 `response_format: Optional[dict] = None`。
- OpenAI-compatible payload 中传入 `response_format`。
- `reflection.py` 两处 LLM 调用传 `response_format={'type': 'json_object'}`。

Anthropic 协议分支不传 `response_format`，保持现状。

---

## 影响范围

| 文件 | 状态 |
|------|------|
| `houdini_agent/utils/ai_client.py` | 修改：DeepSeek/SiliconFlow V4 thinking、`response_format`、reasoning 回灌 |
| `houdini_agent/utils/reflection.py` | 修改：反思/睡眠整理调用 JSON Output |
| `tests/test_ai_client_thinking.py` | 修改：新增 SiliconFlow DeepSeek V4 模型名检测测试 |

## 回归验证

已执行：

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_ai_client_thinking tests.test_token_optimizer
C:/rez/rez_2.112.0/Scripts/python.exe -m py_compile houdini_agent/utils/ai_client.py houdini_agent/utils/reflection.py tests/test_ai_client_thinking.py
```

结果：

- `Ran 36 tests` / `OK`
- 三个触碰文件 `py_compile` 通过
- VS Code diagnostics 无错误

## 已知说明

直接在 Rez Python 3.8 下裸 import `AIClient` 会触发 bundled `urllib3` 的 Python 3.9+ 类型语法问题（`tuple[...]`），这是当前环境/依赖组合问题，不是本次变更引入。现有相关单测通过 `requests` stub 覆盖了本批逻辑。

