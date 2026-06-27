# -*- coding: utf-8 -*-
"""Shared policy constants for Harness V2.

Keep risk-related tool classification in one place so policy checks and
registry metadata stay consistent.
"""

from __future__ import annotations


DESTRUCTIVE_TOOLS = frozenset({
    "delete_node",
    "save_hip",
})

CODE_EXEC_TOOLS = frozenset({
    "execute_python",
    "execute_shell",
})

SCENE_MUTATION_TOOLS = frozenset({
    "create_wrangle_node",
    "create_node",
    "create_nodes_batch",
    "create_named_null",
    "rename_node",
    "set_node_parameter",
    "batch_set_parameters",
    "connect_nodes",
    "cook_node",
    "copy_node",
    "set_display_flag",
    "disconnect_nodes",
    "set_node_flags",
    "create_network_box",
    "add_nodes_to_box",
    "layout_nodes",
})

HIGH_RISK_TOOLS = frozenset(DESTRUCTIVE_TOOLS | CODE_EXEC_TOOLS)

SENSITIVE_ARG_KEYS = frozenset({
    'api_key',
    'apikey',
    'access_key',
    'auth_token',
    'authorization',
    'bearer_token',
    'client_secret',
    'credential',
    'credentials',
    'password',
    'private_key',
    'secret',
    'secret_key',
    'token',
})

SENSITIVE_VALUE_PATTERNS = (
    (r'\bsk-[A-Za-z0-9_\-]{16,}\b', 'openai_style_api_key'),
    (r'\b(?:api[_-]?key|password|passwd|pwd|secret|token)\s*[:=]', 'sensitive_assignment'),
    (r'-----BEGIN [A-Z ]*PRIVATE KEY-----', 'private_key_block'),
    (r'\bBearer\s+[A-Za-z0-9._\-]{16,}\b', 'bearer_token'),
)

SECRET_REDACTION_PATTERNS = (
    (r'\bsk-[A-Za-z0-9_\-]{8,}\b', '[REDACTED_API_KEY]'),
    (r'\bBearer\s+[A-Za-z0-9._\-]{8,}\b', 'Bearer [REDACTED_TOKEN]'),
    (r'(?i)\b(api[_-]?key|password|passwd|pwd|secret|token)\s*[:=]\s*([^\s,;]+)', r'\1=[REDACTED]'),
    (r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', '[REDACTED_PRIVATE_KEY]'),
)

PYTHON_DANGEROUS_PATTERNS = (
    (r'\bos\.remove\b', 'python_os_remove'),
    (r'\bos\.rmdir\b', 'python_os_rmdir'),
    (r'\bshutil\.rmtree\b', 'python_shutil_rmtree'),
    (r'\bos\.system\b', 'python_os_system'),
    (r'\bsubprocess\b', 'python_subprocess'),
    (r'\b__import__\b', 'python_dynamic_import'),
    (r'\bopen\s*\([^)]*["\']w["\']', 'python_open_write'),
    (r'\bhou\.exit\b', 'python_hou_exit'),
    (r'\bhou\.hipFile\.clear\b', 'python_hip_clear'),
)

SHELL_DANGEROUS_PATTERNS = (
    (r'\brm\s+.*-r', 'shell_rm_recursive'),
    (r'\brm\s+.*-f', 'shell_rm_force'),
    (r'\brmdir\s+/s', 'shell_rmdir_recursive'),
    (r'\bdel\s+/s', 'shell_del_recursive'),
    (r'\bdel\s+/q', 'shell_del_quiet'),
    (r'\brd\s+/s', 'shell_rd_recursive'),
    (r'\bformat\s+[a-zA-Z]:', 'shell_format_disk'),
    (r'\breg\s+(delete|add)', 'shell_registry_edit'),
    (r'\bshutdown\b', 'shell_shutdown'),
    (r'\breboot\b', 'shell_reboot'),
    (r'\brunas\b', 'shell_runas'),
    (r'\bsudo\b', 'shell_sudo'),
    (r'\bnetsh\b', 'shell_netsh'),
    (r'\btaskkill\s+/f', 'shell_taskkill_force'),
    (r'Remove-Item\s+.*-Recurse', 'shell_powershell_recursive_delete'),
    (r'Invoke-Expression', 'shell_invoke_expression'),
    (r'\biex\b', 'shell_iex'),
    (r'\bdiskpart\b', 'shell_diskpart'),
    (r'%0\|%0', 'shell_fork_bomb_cmd'),
    (r':\(\)\{.*\}', 'shell_fork_bomb_sh'),
)

# 需要用户确认的工具（确认模式下拦截）
CONFIRM_TOOLS = frozenset(SCENE_MUTATION_TOOLS | HIGH_RISK_TOOLS)

# 不需要 Houdini 主线程的工具（纯 Python / 系统操作，可在后台线程直接执行）
BG_SAFE_TOOLS = frozenset({
    'execute_shell',       # subprocess.run，不依赖 hou
    'search_local_doc',    # 纯 Python 文本检索
    'list_skills',         # 纯 Python 列表
    'search_memory',       # 纯 Python 记忆库检索
})

# 静默工具：不在执行列表 UI 中显示
SILENT_TOOLS = frozenset({
    'add_todo',
    'update_todo',
})

# Plan 模式静默工具
PLAN_SILENT_TOOLS = frozenset({
    'create_plan',
    'update_plan_step',
    'ask_question',
})

# Plan 模式执行阶段附加工具
PLAN_EXECUTION_EXTRA_TOOLS = frozenset({
    'update_plan_step',
})
