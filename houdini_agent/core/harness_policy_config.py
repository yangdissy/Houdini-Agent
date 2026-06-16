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
    "rename_node",
    "set_node_parameter",
    "batch_set_parameters",
    "connect_nodes",
    "copy_node",
    "set_display_flag",
    "disconnect_nodes",
    "set_node_flags",
    "create_network_box",
    "add_nodes_to_box",
    "layout_nodes",
})

HIGH_RISK_TOOLS = frozenset(DESTRUCTIVE_TOOLS | CODE_EXEC_TOOLS)

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
