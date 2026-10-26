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
    "execute_python",
    "create_wrangle_node",
    "create_node",
    "create_nodes_batch",
    "create_named_null",
    "rename_node",
    "set_node_parameter",
    "set_parameter_expression",
    "set_parameter_reference",
    "upsert_spare_parameter",
    "insert_multiparm_instance",
    "remove_multiparm_instance",
    "create_object_merges_batch",
    "batch_set_parameters",
    "connect_nodes",
    "cook_node",
    "cook_sample_frames",
    "copy_node",
    "set_display_flag",
    "disconnect_nodes",
    "set_node_flags",
    "create_network_box",
    "add_nodes_to_box",
    "set_network_box_comment",
    "layout_nodes",
})

HIGH_RISK_TOOLS = frozenset(DESTRUCTIVE_TOOLS | CODE_EXEC_TOOLS)

EXECUTION_FAILURE_LIMIT = 2
EXECUTION_ERROR_FAMILY_PATTERN = r"(?m)^\s*((?:[A-Za-z_]\w*\.)?[A-Za-z_]\w*(?:Error|Exception)|OperationFailed|ObjectWasDeleted|InvalidNodeType):"
EXECUTION_RECOVERY_TOOLS = frozenset({
    "inspect_node",
    "get_parameter_schema",
    "get_network_structure",
    "inspect_python",
    "get_houdini_node_doc",
    "search_local_doc",
    "search_tool_contracts",
    "inspect_tool_contract",
})
EXECUTION_FAILURE_RECOVERY_HINT = (
    "Repeated execution failures: this tool is paused for this user turn. "
    "Do not keep rewriting code or repeating the call. Inspect the relevant node/parameters "
    "or read the relevant documentation/tool contract with a read-only tool before retrying. "
    "If no new evidence is available, report the blocker to the user."
)

# Skills that implement their own narrower write authorization contract.
# install_houdini_skill separates source installation from explicit activation.
CONTROLLED_WRITE_SKILLS = frozenset({
    "install_houdini_skill",
})

PRIVATE_USER_PATH_PATTERN = r'(?i)(?:^|[^\w])cache/+users(?:/+([^/\s\'"<>;,)]+))?'

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
    (r'\b(?:api[_-]?key|password|passwd|pwd|secret|token)["\']?\s*[:=]', 'sensitive_assignment'),
    (r'-----BEGIN [A-Z ]*PRIVATE KEY-----', 'private_key_block'),
    (r'\bBearer\s+[A-Za-z0-9._\-]{16,}\b', 'bearer_token'),
)

SECRET_REDACTION_PATTERNS = (
    (r'\bsk-[A-Za-z0-9_\-]{8,}\b', '[REDACTED_API_KEY]'),
    (r'\bBearer\s+[A-Za-z0-9._\-]{8,}\b', 'Bearer [REDACTED_TOKEN]'),
    (r'(?i)\b(api[_-]?key|password|passwd|pwd|secret|token)["\']?\s*[:=]\s*(?:"[^"\n]*"|\'[^\'\n]*\'|[^\s,;]+)', r'\1=[REDACTED]'),
    (r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', '[REDACTED_PRIVATE_KEY]'),
)

PYTHON_BLOCKED_MODULES = frozenset({
    'subprocess', 'importlib', 'requests', 'urllib', 'socket', 'http.client',
})

PYTHON_BLOCKED_CALLS = frozenset({
    'os.remove', 'os.unlink', 'os.rmdir', 'os.removedirs', 'os.system',
    'shutil.rmtree', 'pathlib.Path.unlink', 'pathlib.Path.rmdir',
    'pathlib.Path.write_text', 'pathlib.Path.write_bytes',
    '__import__', 'exec', 'eval', 'compile',
})

PYTHON_DANGEROUS_PATTERNS = (
    (r'\bos\.remove\b', 'python_os_remove'),
    (r'\bos\.rmdir\b', 'python_os_rmdir'),
    (r'\bshutil\.rmtree\b', 'python_shutil_rmtree'),
    (r'\bos\.system\b', 'python_os_system'),
    (r'\bsubprocess\b', 'python_subprocess'),
    (r'\b__import__\b', 'python_dynamic_import'),
    (r'\bhou\.exit\b', 'python_hou_exit'),
    (r'\bhou\.hipFile\.clear\b', 'python_hip_clear'),
)

SHELL_DANGEROUS_PATTERNS = (
    (r'\brm\s+.*-r', 'shell_rm_recursive'),
    (r'\brm\s+.*-f', 'shell_rm_force'),
    (r'\b(?:rmdir|rd)\s+[^\r\n;&|]*/s\b', 'shell_rmdir_recursive'),
    (r'\bdel\s+[^\r\n;&|]*/[sq]\b', 'shell_del_recursive'),
    (r'\bformat\s+[a-zA-Z]:', 'shell_format_disk'),
    (r'\breg\s+(delete|add)', 'shell_registry_edit'),
    (r'\bshutdown\b', 'shell_shutdown'),
    (r'\breboot\b', 'shell_reboot'),
    (r'\brunas\b', 'shell_runas'),
    (r'\bsudo\b', 'shell_sudo'),
    (r'\bnetsh\b', 'shell_netsh'),
    (r'\btaskkill\s+/f', 'shell_taskkill_force'),
    (r'\b(?:Remove-Item|ri|rm|del|erase|rd|rmdir)\s+[^\r\n;&|]*-Recurse\b', 'shell_powershell_recursive_delete'),
    (r'Invoke-Expression', 'shell_invoke_expression'),
    (r'\biex\b', 'shell_iex'),
    (r'\bdiskpart\b', 'shell_diskpart'),
    (r'%0\|%0', 'shell_fork_bomb_cmd'),
    (r':\(\)\{.*\}', 'shell_fork_bomb_sh'),
)

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
