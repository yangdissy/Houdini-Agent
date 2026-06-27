# Harness Guardrails 更新记录 — 2026-06-26

## 背景

本次围绕 Harness V2 的安全边界与工具结果治理进行加固，重点解决三个问题：工具策略不可被模型参数绕过、工具输入缺少统一 guardrails、工具输出进入 UI/LLM 前缺少统一结果契约与敏感信息脱敏。

---

## 本次改动

### 1. 工具执行边界加固

- 更新 `houdini_agent/ui/ai_tab.py`：
  - 将公开工具入口 `_execute_tool_with_todo()` 与内部执行实现 `_execute_tool_impl()` 分离。
  - 公开入口会丢弃模型可传入的 `_harness_policy_checked`、`_harness_skip_confirm`。
  - Harness V2 启用时，所有公开工具调用必须先经过 `_execute_tool_with_policy()`。
  - Policy wrapper 内部不再通过 kwargs 私有标志回调公开入口，改为直接调用内部执行方法。

### 2. Tool input guardrails

- 更新 `houdini_agent/core/harness_policy_config.py`：
  - 新增敏感参数 key 集合。
  - 新增敏感值匹配规则。
  - 新增危险 Python 代码模式。
  - 新增危险 Shell 命令模式。

- 更新 `houdini_agent/core/harness_engine.py`：
  - 在 `HarnessToolPolicyEngine.decide()` 中统一执行输入检查。
  - 拦截敏感字段与疑似 API key / token / password / private key。
  - 拦截危险 Python：文件删除、递归删除、`os.system`、`subprocess`、动态导入、写文件、退出 Houdini、清空 HIP。
  - 拦截危险 Shell：递归/强制删除、格式化磁盘、注册表修改、关机重启、提权、网络配置修改、强杀进程、PowerShell `Invoke-Expression`、`diskpart`、fork bomb。
  - 拦截路径异常：路径穿越、NUL 字符、非 Houdini 支持 root 的绝对节点路径。
  - 将 `execute_python.code` 与 `execute_shell.command` 纳入 Harness 层统一缺参检查。

### 3. Tool output guardrails

- 更新 `houdini_agent/core/harness_policy_config.py`：
  - 新增输出脱敏规则 `SECRET_REDACTION_PATTERNS`。

- 更新 `houdini_agent/core/harness_engine.py`：
  - 新增 `redact_secrets(value)`：递归脱敏字符串、dict、list、tuple。
  - 新增 `sanitize_tool_result(result)`：统一工具返回契约并脱敏。
  - 统一工具结果契约为 `{success: bool, result/error: ...}`。
  - 非 dict 结果会转为失败结果，避免异常形状继续进入后续链路。
  - 成功结果缺 `result` 时补空字符串。
  - 失败结果缺 `error` 时从 `result` 兜底，仍缺失则给出默认错误。

- 更新 `houdini_agent/ui/ai_tab.py`：
  - 在 Harness policy wrapper 执行工具后立即调用 `sanitize_tool_result()`。
  - UI、历史、回调和后续 LLM 流程拿到的是规范化脱敏后的结果。

- 更新 `houdini_agent/utils/ai_client.py`：
  - `_compress_tool_result()` 开头调用 `sanitize_tool_result()`。
  - 作为工具输出进入 LLM 上下文前的最后一道脱敏防线。
  - 覆盖 web/search 内置执行器或其他未直接经过 UI harness 的结果路径。

### 4. 测试覆盖

- 新增 `tests/test_harness_execution_boundary.py`：
  - 覆盖伪造 `_harness_policy_checked=True` 不能绕过 Ask 模式高风险工具拒绝。
  - 覆盖伪造 `_harness_skip_confirm=True` 不能跳过确认。

- 更新 `tests/test_harness_policy.py`：
  - 覆盖高风险工具确认策略。
  - 覆盖 execute 工具缺参检查。
  - 覆盖敏感参数 key、敏感值、危险 Python、危险 Shell、路径穿越、非法 Houdini root。
  - 覆盖输出结果规范化与递归脱敏。

- 更新 `tests/test_ai_client_thinking.py`：
  - 覆盖 `_compress_tool_result()` 在结果进入 LLM 前会脱敏。
  - 覆盖异常工具结果形状会被规范化。

- 更新 `tests/test_import_smoke.py`：
  - 在测试 stub 中补充 `numpy`，使 UI 导入测试在无完整运行依赖环境下仍可执行。

---

## 验证结果

目标回归测试通过：

```text
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_harness_policy tests.test_harness_execution_boundary tests.test_ai_client_thinking tests.test_diagnostics_export

Ran 32 tests in 0.008s
OK
```

相关文件 VS Code Problems 检查无报错：

- `houdini_agent/core/harness_engine.py`
- `houdini_agent/core/harness_policy_config.py`
- `houdini_agent/ui/ai_tab.py`
- `houdini_agent/utils/ai_client.py`
- `tests/test_harness_policy.py`
- `tests/test_ai_client_thinking.py`
- `tests/test_harness_execution_boundary.py`

---

## 当前已知事项

- 当前 Rez Python 环境没有安装 `pytest`，本次使用仓库兼容的 `unittest` 执行目标测试。
- `houdini_agent/utils/doc_rag.py` 在工作区中存在既有未提交改动，但不属于本次 Harness Guardrails 改动范围。
- 输出脱敏规则当前为代码内常量，后续可迁移到 `config/` 下的 JSON 策略文件，实现可配置化与 fail-closed 加载。

---

## 影响范围

主要涉及：

```text
houdini_agent/core/harness_engine.py
houdini_agent/core/harness_policy_config.py
houdini_agent/ui/ai_tab.py
houdini_agent/utils/ai_client.py
tests/test_harness_policy.py
tests/test_ai_client_thinking.py
tests/test_import_smoke.py
tests/test_harness_execution_boundary.py
```

本次改动不引入新依赖，不迁移运行时框架，不改变底层 Houdini 工具 handler 的业务逻辑。底层 MCP client 原有安全检查仍保留，作为 Harness 之后的第二道防线。
