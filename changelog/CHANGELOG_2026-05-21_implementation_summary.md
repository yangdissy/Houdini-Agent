# Houdini-Agent 改动总结（2026-05-21）

## 说明
- 本文汇总了本轮连续实施中的主要改动，并附带当前工作区的完整 Git 改动文件清单，便于后续审阅与提交。
- 范围包含：Harness 架构对齐、策略与可观测性、记忆系统、知识库检索与应用、规则系统。

## 一、架构与执行链路（Harness / 工具调度）

### 1) Harness V2 基础与策略统一
- 新增 `houdini_agent/core/harness_engine.py`：
  - 引入 Harness V2 开关与运行态容器。
  - 引入策略决策（allow/deny/ask/retry）与重试键逻辑。
- 新增 `houdini_agent/core/harness_policy_config.py`：
  - 抽离高风险工具集合，作为单一真值源。

### 2) 执行器分类改为 Registry 驱动
- 新增 `houdini_agent/core/streaming_tool_executor.py`（并接入主链路）：
  - 使用 runtime profile 驱动 async/serial/high-risk 分类。
  - 支持每轮刷新 profile，降低硬编码漂移风险。
- 更新 `houdini_agent/utils/tool_registry.py`：
  - 统一风险分类来源。
  - 增加 streaming executor profile 构建能力。

### 3) AIClient 与 UI 桥接更新
- 更新 `houdini_agent/utils/ai_client.py`：
  - 注入并复用 runtime_profile_provider。
  - 保留 legacy 分支作为回退。
- 更新 `houdini_agent/ui/ai_tab.py`、`houdini_agent/ui/input_area.py`、`houdini_agent/ui/cursor_widgets.py`：
  - 增加策略时间线、风险提示、恢复建议。
  - Token 面板接入 harness trace 汇总与表格。
  - 修复规则编辑对话框中 username 相关问题。

### 4) 可观测性增强
- 在 `houdini_agent/ui/ai_tab.py` 中补充 harness_trace 落盘（会话级 jsonl）与回放可追踪信息。
- 重试键升级为“工具名 + 参数指纹”，避免不同参数互相消耗重试预算。

## 二、记忆系统改动（Memory）

### 1) search_memory 升级为三层联合检索
- 更新 `houdini_agent/utils/mcp/client.py`：
  - `search_memory` 从单 semantic 升级为 semantic + episodic + procedural 联合返回。
  - 保留兼容字段 `memories`（semantic）并新增分层字段。

### 2) 阈值策略统一
- 更新 `houdini_agent/utils/memory_store.py`：
  - 新增相似度阈值缩放函数，fallback embedding 下统一阈值自适应。
  - 去重逻辑 `find_duplicate_semantic` 接入同一阈值缩放机制。

### 3) 并发安全加固
- 更新 `houdini_agent/utils/memory_store.py`：
  - 增加 DB 重入锁与统一 DB 操作辅助方法。
  - SQLite 连接增加 timeout / busy_timeout。
  - 高频读写路径切换到线程安全访问。
  - `get_memory_store` 单例初始化增加全局锁。

### 4) 语义/策略记忆老化与淘汰（第三批）
- 更新 `houdini_agent/utils/memory_store.py`：
  - 新增语义衰减：`decay_semantic_confidence`。
  - 新增策略衰减：`decay_procedural_priority`。
  - 新增清理策略：`prune_semantic_memories`、`prune_procedural_memories`。
  - 新增统一维护入口：`maintain_long_term_memory`。
- 更新 `houdini_agent/utils/reward_engine.py`：
  - 周期触发长期记忆维护并返回维护统计。

## 三、知识库检索与应用改动（Doc RAG）

### 1) 检索质量提升（第一批）
- 更新 `houdini_agent/utils/doc_rag.py`：
  - `search_knowledge` 改为分项加权（标题/正文/覆盖率/来源权重/短片段惩罚）。
  - 结果补充 `matched_terms`、`rank_reason`。
  - 增加 query-type 识别重排（node/vex/hom/general）。
  - 增加去重与同源多样性约束。

### 2) 应用链路增强（自动注入）
- 更新 `houdini_agent/utils/doc_rag.py`：
  - `auto_retrieve` 增加按类型配额注入（node/vex/hom/knowledge）。
  - 增加低证据阈值与回退提示，避免弱相关片段误注入。

### 3) 工具侧结构化返回
- 更新 `houdini_agent/utils/mcp/client.py`：
  - `search_local_doc` 保留原文本结果，同时新增结构化字段：
    - `query`、`count`、`items`
    - `confidence_band`、`source`、`matched_terms`、`rank_reason`、`snippet`

### 4) 缓存与分段优化（第二批）
- 更新 `houdini_agent/utils/doc_rag.py`：
  - 知识库缓存指纹从 mtime 升级为 mtime+size。
  - 分段器增加“无 ## 标题时窗口切分”后备逻辑，提升覆盖率。

## 四、规则系统改动
- 更新 `rules/MainRules.md`：
  - 加入 karpathy-guidelines 的核心行为规则（先思考、简单优先、外科手术式修改、可验证目标）。
  - 通过现有 rules 自动注入链路生效（无需额外工具注册）。

## 五、验证与质量状态
- 针对本轮主要修改文件执行过多轮错误检查（get_errors），关键文件均通过。
- 未在本文内附端到端业务回归数据（如需要可再补充自动回归脚本与结果）。

## 六、当前工作区 Git 改动文件清单（完整）

```text
 M houdini_agent/core/agent_runner.py
 M houdini_agent/core/main_window.py
 M houdini_agent/main.py
 M houdini_agent/ui/ai_tab.py
 M houdini_agent/ui/cursor_widgets.py
 M houdini_agent/ui/header.py
 M houdini_agent/ui/input_area.py
 M houdini_agent/ui/memory_manager_dialog.py
 M houdini_agent/utils/ai_client.py
 M houdini_agent/utils/doc_rag.py
 M houdini_agent/utils/growth_tracker.py
 M houdini_agent/utils/mcp/client.py
 M houdini_agent/utils/memory_store.py
 M houdini_agent/utils/reflection.py
 M houdini_agent/utils/reward_engine.py
 M houdini_agent/utils/rules_manager.py
 M houdini_agent/utils/tool_registry.py
 D houdini_agent_backup/QUICK_SHELF_CODE.py
 M houdini_agent_backup/core/agent_runner.py
 M houdini_agent_backup/ui/ai_tab.py
 M houdini_agent_backup/utils/ai_client.py
 M houdini_agent_backup/utils/mcp/client.py
 M rules/MainRules.md
 M shared/common_utils.py
?? houdini_agent/core/harness_engine.py
?? houdini_agent/core/harness_policy_config.py
?? houdini_agent/core/streaming_tool_executor.py
?? houdini_agent/ui/login_dialog.py
?? shared/user_paths.py
```

## 七、建议提交拆分（可选）
- 提交 A：Harness/策略/调度重构
- 提交 B：记忆系统（检索+并发+维护）
- 提交 C：知识库检索与应用优化
- 提交 D：规则与提示词策略
