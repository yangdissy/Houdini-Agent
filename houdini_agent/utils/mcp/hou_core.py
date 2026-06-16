# -*- coding: utf-8 -*-
"""Houdini 核心操作层 - 供 server.py 和 client.py 共享的底层 Houdini API 封装。

架构说明：
    server.py  → 面向外部 MCP 客户端（通过 HTTP），返回 {status, message, data}
    client.py  → 面向内部 AI Agent（直接 Python 调用），返回 {success, result, error}

    本模块提供底层 Houdini 操作函数，无格式化封装。
    两个上层模块通过适配层调用本模块并自行格式化返回值。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    import hou  # type: ignore
except Exception:
    hou = None  # type: ignore


def hou_available() -> bool:
    """检查 Houdini API 是否可用"""
    return hou is not None


def resolve_node(path: str) -> Optional[Any]:
    """通过路径获取节点，失败返回 None"""
    if hou is None:
        return None
    try:
        return hou.node(path)
    except Exception:
        return None


def create_node(parent_path: str, node_type: str, node_name: str = "") -> Tuple[bool, str, Optional[Any]]:
    """创建节点
    
    Returns:
        (success, message, node_or_None)
    """
    if hou is None:
        return False, "Houdini 环境不可用", None
    parent = hou.node(parent_path)
    if not parent:
        return False, f"父节点 {parent_path} 不存在", None
    try:
        node = parent.createNode(node_type, node_name or None)
        return True, f"已创建节点 {node.path()}", node
    except Exception as e:
        return False, f"创建节点失败: {e}", None


def delete_node(node_path: str) -> Tuple[bool, str]:
    """删除节点"""
    if hou is None:
        return False, "Houdini 环境不可用"
    node = hou.node(node_path)
    if not node:
        return False, f"节点 '{node_path}' 不存在"
    try:
        node.destroy()
        return True, f"已删除节点 '{node_path}'"
    except Exception as e:
        return False, f"删除失败: {e}"


def connect_nodes(output_path: str, input_path: str, input_index: int = 0) -> Tuple[bool, str]:
    """连接两个节点"""
    if hou is None:
        return False, "Houdini 环境不可用"
    output_node = hou.node(output_path)
    input_node = hou.node(input_path)
    if output_node is None:
        return False, f"输出节点 '{output_path}' 不存在"
    if input_node is None:
        return False, f"输入节点 '{input_path}' 不存在"
    max_inputs = input_node.type().maxNumInputs()
    if input_index < 0 or input_index >= max_inputs:
        return False, f"输入端口索引 {input_index} 无效 (有效范围 0~{max_inputs - 1})"
    try:
        input_node.setInput(input_index, output_node, 0)
        try:
            related_paths = _collect_related_layout_paths([output_node, input_node])
            if related_paths:
                layout_nodes(
                    parent_path=input_node.parent().path(),
                    node_paths=related_paths,
                    method="tidy",
                    spacing=1.0,
                )
        except Exception:
            pass
        return True, f"已连接 {output_path} -> {input_path}[{input_index}]"
    except Exception as e:
        return False, f"连接失败: {e}"


def _collect_related_layout_paths(seed_nodes: List[Any], max_nodes: int = 48) -> List[str]:
    """Collect a bounded same-parent connected component for local tidy layout."""
    if not seed_nodes:
        return []
    parent = None
    for node in seed_nodes:
        if node is not None:
            parent = node.parent()
            break
    if parent is None:
        return []

    queue = [node for node in seed_nodes if node is not None and node.parent() == parent]
    seen: set = set()
    paths: List[str] = []

    while queue and len(paths) < max_nodes:
        node = queue.pop(0)
        try:
            path = node.path()
        except Exception:
            continue
        if path in seen:
            continue
        seen.add(path)
        paths.append(path)

        neighbors = []
        try:
            neighbors.extend([inp for inp in (node.inputs() or []) if inp is not None])
        except Exception:
            pass
        try:
            neighbors.extend([out for out in (node.outputs() or []) if out is not None])
        except Exception:
            pass
        for neighbor in neighbors:
            try:
                if neighbor.parent() == parent and neighbor.path() not in seen:
                    queue.append(neighbor)
            except Exception:
                continue

    return paths


def set_parameter(node_path: str, param_name: str, value: Any) -> Tuple[bool, str]:
    """设置节点参数"""
    if hou is None:
        return False, "Houdini 环境不可用"
    node = hou.node(node_path)
    if not node:
        return False, f"节点 '{node_path}' 不存在"
    parm = node.parm(param_name)
    if parm is None:
        # 尝试 parmTuple
        pt = node.parmTuple(param_name)
        if pt is not None:
            try:
                pt.set(value)
                return True, f"已设置 {node_path}/{param_name} = {value}"
            except Exception as e:
                return False, f"设置失败: {e}"
        return False, f"参数 '{param_name}' 不存在"
    try:
        parm.set(value)
        return True, f"已设置 {node_path}/{param_name} = {value}"
    except Exception as e:
        return False, f"设置失败: {e}"


def get_node_info(node_path: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """获取节点信息"""
    if hou is None:
        return False, "Houdini 环境不可用", None
    node = hou.node(node_path)
    if not node:
        return False, f"节点 '{node_path}' 不存在", None
    info = {
        "type": node.type().name(),
        "path": node.path(),
        "inputs": [i.path() for i in node.inputs() if i],
        "outputs": [o.path() for o in node.outputs() if o],
    }
    return True, "查询成功", info


def disconnect_nodes(node_path: str, input_index: Optional[int] = None) -> Tuple[bool, str]:
    """断开节点的一个或全部输入连接

    Args:
        node_path:   目标节点完整路径
        input_index: 要断开的输入端口索引；None 表示断开所有输入

    Returns:
        (success, message)
    """
    if hou is None:
        return False, "Houdini 环境不可用"
    node = hou.node(node_path)
    if not node:
        return False, f"节点 '{node_path}' 不存在"
    try:
        max_inputs = node.type().maxNumInputs()
        if input_index is not None:
            if input_index < 0 or input_index >= max_inputs:
                return False, f"输入端口索引 {input_index} 无效 (有效范围 0~{max_inputs - 1})"
            node.setInput(input_index, None)
            return True, f"已断开 {node_path}[{input_index}] 的输入连接"
        else:
            disconnected = []
            for i in range(max_inputs):
                if node.input(i) is not None:
                    node.setInput(i, None)
                    disconnected.append(i)
            if disconnected:
                return True, f"已断开 {node_path} 的全部输入连接（端口: {disconnected}）"
            return True, f"节点 {node_path} 无活跃输入连接，无需操作"
    except Exception as e:
        return False, f"断开连接失败: {e}"


def set_node_flags(
    node_path: str,
    bypass: Optional[bool] = None,
    template: Optional[bool] = None,
    lock: Optional[bool] = None,
) -> Tuple[bool, str]:
    """设置节点的 bypass / template / lock 标志

    Args:
        node_path: 节点完整路径
        bypass:    True=绕过节点（节点变灰，数据透传），False=取消绕过
        template:  True=设为模板节点（橙色），False=取消模板
        lock:      True=锁定节点（防止修改），False=解锁

    Returns:
        (success, message)
    """
    if hou is None:
        return False, "Houdini 环境不可用"
    node = hou.node(node_path)
    if not node:
        return False, f"节点 '{node_path}' 不存在"
    if bypass is None and template is None and lock is None:
        return False, "至少需要指定一个标志（bypass / template / lock）"
    try:
        applied = []
        if bypass is not None and hasattr(node, 'bypass'):
            node.bypass(bypass)
            applied.append(f"bypass={'on' if bypass else 'off'}")
        if template is not None and hasattr(node, 'setTemplateFlag'):
            node.setTemplateFlag(template)
            applied.append(f"template={'on' if template else 'off'}")
        if lock is not None and hasattr(node, 'setHardLocked'):
            node.setHardLocked(lock)
            applied.append(f"lock={'on' if lock else 'off'}")
        if applied:
            return True, f"已设置 {node_path}: {', '.join(applied)}"
        return False, f"节点类型 {node.type().name()} 不支持请求的标志"
    except Exception as e:
        return False, f"设置标志失败: {e}"


def set_display_flag(node_path: str) -> Tuple[bool, str]:
    """设置节点显示标志"""
    if hou is None:
        return False, "Houdini 环境不可用"
    node = hou.node(node_path)
    if not node:
        return False, f"节点 '{node_path}' 不存在"
    try:
        node.setDisplayFlag(True)
        node.setRenderFlag(True)
        return True, f"已设置 {node_path} 为显示节点"
    except Exception as e:
        return False, f"设置失败: {e}"


def check_errors(node_path: Optional[str] = None) -> Tuple[bool, str, List[str]]:
    """检查节点错误"""
    if hou is None:
        return False, "Houdini 环境不可用", []
    if node_path:
        node = hou.node(node_path)
        if not node:
            return False, f"节点 '{node_path}' 不存在", []
        errors = node.errors() or []
        return True, ("存在错误" if errors else "无错误"), errors
    else:
        error_nodes = []
        for n in hou.node('/').allSubChildren():
            try:
                if n.errors():
                    error_nodes.append(n.path())
            except Exception:
                continue
        return True, (f"发现 {len(error_nodes)} 个错误节点" if error_nodes else "无错误节点"), error_nodes


def layout_children(parent_path: str) -> Tuple[bool, str]:
    """自动布局子节点"""
    if hou is None:
        return False, "Houdini 环境不可用"
    parent = hou.node(parent_path)
    if not parent:
        return False, f"节点 '{parent_path}' 不存在"
    try:
        parent.layoutChildren()
        return True, f"已自动布局 {parent_path} 的子节点"
    except Exception as e:
        return False, f"布局失败: {e}"


# ============================================================
# 节点布局工具
# ============================================================

def layout_nodes(
    parent_path: str = "",
    node_paths: Optional[List[str]] = None,
    method: str = "auto",
    spacing: float = 1.0,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """多策略节点布局

    Args:
        parent_path: 父网络路径，留空使用当前活跃网络
        node_paths: 要布局的节点路径列表；为空时布局整个网络
        method: 布局方法 auto / tidy / grid / columns
        spacing: 间距倍率（默认 1.0）

    Returns:
        (success, message, positions_list)
        positions_list 中每项: {name, path, x, y}
    """
    if hou is None:
        return False, "Houdini 环境不可用", []

    # 解析父网络
    parent = None
    if parent_path:
        parent = hou.node(parent_path)
    if parent is None:
        # 尝试当前网络编辑器的 pwd
        try:
            editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor:
                parent = editor.pwd()
        except Exception:
            pass
    if parent is None:
        try:
            parent = hou.node("/obj")
        except Exception:
            pass
    if parent is None:
        return False, "未找到目标网络", []

    try:
        # ---------- 收集目标节点 ----------
        if node_paths:
            nodes = [hou.node(p) for p in node_paths if hou.node(p)]
            if not nodes:
                return False, "指定的节点路径均无效", []
        else:
            nodes = list(parent.children())
            if not nodes:
                return False, f"{parent.path()} 下没有子节点", []

        # ---------- 执行布局 ----------
        layout_method_used = method

        if method == "auto":
            if node_paths:
                _layout_columns(nodes, spacing)
                layout_method_used = "tidy(auto)"
            else:
                # 全网络 → layoutChildren（支持间距）
                h_sp = 2.0 * spacing
                v_sp = 1.0 * spacing
                try:
                    parent.layoutChildren(
                        horizontal_spacing=h_sp,
                        vertical_spacing=v_sp,
                    )
                    layout_method_used = "layoutChildren"
                except TypeError:
                    # 旧版 Houdini 可能不支持间距参数
                    parent.layoutChildren()
                    layout_method_used = "layoutChildren(no-spacing)"

        elif method in ("tidy", "columns"):
            _layout_columns(nodes, spacing)
            layout_method_used = "tidy" if method == "tidy" else "columns(tidy)"

        elif method == "grid":
            _layout_grid(nodes, spacing)
            layout_method_used = "grid"

        else:
            return False, f"未知布局方法: {method}", []

        # ---------- 收集结果位置 ----------
        positions = []
        for n in nodes:
            pos = n.position()
            positions.append({
                "name": n.name(),
                "path": n.path(),
                "x": round(pos[0], 3),
                "y": round(pos[1], 3),
            })

        return (
            True,
            f"已布局 {len(nodes)} 个节点（方法: {layout_method_used}）",
            positions,
        )

    except Exception as e:
        return False, f"布局失败: {e}", []


def _layout_grid(nodes: list, spacing: float = 1.0) -> None:
    """网格布局：按节点列表顺序排成 N 列网格"""
    if not nodes:
        return
    import math
    cols = max(1, int(math.ceil(math.sqrt(len(nodes)))))
    h_sp = 3.5 * spacing
    v_sp = 1.5 * spacing
    for idx, node in enumerate(nodes):
        col = idx % cols
        row = idx // cols
        node.setPosition(hou.Vector2(col * h_sp, -row * v_sp))


def _layout_columns(nodes: list, spacing: float = 1.0) -> None:
    """按拓扑关系整理节点：主链垂直，分支左右展开。"""
    if not nodes:
        return
    node_ids = [n.path() for n in nodes]
    node_set = set(node_ids)
    edges: List[Tuple[str, str, int]] = []
    original_positions: Dict[str, Tuple[float, float]] = {}

    for node in nodes:
        node_id = node.path()
        try:
            pos = node.position()
            original_positions[node_id] = (float(pos[0]), float(pos[1]))
        except Exception:
            original_positions[node_id] = (0.0, 0.0)
        try:
            for input_index, input_node in enumerate(node.inputs() or []):
                if input_node is not None and input_node.path() in node_set:
                    edges.append((input_node.path(), node_id, input_index))
        except Exception:
            continue

    positions = _compute_tidy_layout(
        node_ids,
        edges,
        spacing=spacing,
        original_positions=original_positions,
    )
    for node in nodes:
        x, y = positions.get(node.path(), (0.0, 0.0))
        node.setPosition(hou.Vector2(x, y))


def _compute_tidy_layout(
    node_ids: List[str],
    edges: List[Tuple[str, str, int]],
    spacing: float = 1.0,
    original_positions: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, Tuple[float, float]]:
    """Compute readable DAG positions without depending on Houdini APIs.

    Upstream nodes are placed above downstream nodes. Multi-input parents are
    nudged left/right according to input index, so V-shaped joins are easier to
    read than Houdini's generic auto-layout for generated networks.
    """
    if not node_ids:
        return {}

    spacing = max(float(spacing or 1.0), 0.2)
    h_sp = 3.6 * spacing
    v_sp = 1.7 * spacing
    order = {node_id: idx for idx, node_id in enumerate(node_ids)}
    node_set = set(node_ids)
    filtered_edges = [
        (src, dst, int(input_index or 0))
        for src, dst, input_index in edges
        if src in node_set and dst in node_set and src != dst
    ]

    parents: Dict[str, List[Tuple[str, int]]] = {node_id: [] for node_id in node_ids}
    children: Dict[str, List[Tuple[str, int]]] = {node_id: [] for node_id in node_ids}
    in_degree: Dict[str, int] = {node_id: 0 for node_id in node_ids}
    for src, dst, input_index in filtered_edges:
        parents[dst].append((src, input_index))
        children[src].append((dst, input_index))
        in_degree[dst] += 1

    from collections import deque
    depth: Dict[str, int] = {}
    queue = deque(sorted(
        (node_id for node_id in node_ids if in_degree[node_id] == 0),
        key=lambda node_id: order[node_id],
    ))
    for node_id in queue:
        depth[node_id] = 0

    remaining_degree = dict(in_degree)
    while queue:
        current = queue.popleft()
        current_depth = depth.get(current, 0)
        for child_id, _ in children[current]:
            depth[child_id] = max(depth.get(child_id, 0), current_depth + 1)
            remaining_degree[child_id] -= 1
            if remaining_degree[child_id] == 0:
                queue.append(child_id)

    for node_id in node_ids:
        if node_id not in depth:
            upstream_depths = [depth[p] for p, _ in parents[node_id] if p in depth]
            depth[node_id] = (max(upstream_depths) + 1) if upstream_depths else 0

    connected = {src for src, _, _ in filtered_edges} | {dst for _, dst, _ in filtered_edges}
    layers: Dict[int, List[str]] = {}
    isolated: List[str] = []
    for node_id in node_ids:
        if node_id not in connected:
            isolated.append(node_id)
        else:
            layers.setdefault(depth.get(node_id, 0), []).append(node_id)

    def original_x(node_id: str) -> float:
        if original_positions and node_id in original_positions:
            return original_positions[node_id][0]
        return float(order[node_id])

    for layer_nodes in layers.values():
        layer_nodes.sort(key=lambda node_id: (original_x(node_id), order[node_id]))
    isolated.sort(key=lambda node_id: (original_x(node_id), order[node_id]))

    x_pos: Dict[str, float] = {}
    for layer_index in sorted(layers):
        layer_nodes = layers[layer_index]
        for idx, node_id in enumerate(layer_nodes):
            x_pos[node_id] = (idx - (len(layer_nodes) - 1) / 2.0) * h_sp

    def input_count(child_id: str) -> int:
        input_indexes = [input_index for _, input_index in parents[child_id]]
        return max(input_indexes) + 1 if input_indexes else 1

    def pack_by_targets(items: List[Tuple[str, float]]) -> None:
        if not items:
            return
        items = sorted(items, key=lambda item: (item[1], order[item[0]]))
        packed: List[Tuple[str, float, float]] = []
        right_edge = None
        for node_id, target in items:
            x_value = target if right_edge is None else max(target, right_edge + h_sp)
            packed.append((node_id, target, x_value))
            right_edge = x_value
        shift = sum(target - x_value for _, target, x_value in packed) / float(len(packed))
        for node_id, _, x_value in packed:
            x_pos[node_id] = x_value + shift

    sorted_layers = sorted(layers)
    for _ in range(3):
        for layer_index in sorted_layers:
            targets = []
            for node_id in layers[layer_index]:
                if not parents[node_id]:
                    targets.append((node_id, x_pos.get(node_id, 0.0)))
                    continue
                parent_targets = [x_pos.get(parent_id, 0.0) for parent_id, _ in parents[node_id]]
                targets.append((node_id, sum(parent_targets) / float(len(parent_targets))))
            pack_by_targets(targets)

        for layer_index in reversed(sorted_layers):
            targets = []
            for node_id in layers[layer_index]:
                if not children[node_id]:
                    targets.append((node_id, x_pos.get(node_id, 0.0)))
                    continue
                child_targets = []
                for child_id, input_index in children[node_id]:
                    count = max(input_count(child_id), 1)
                    offset = (input_index - (count - 1) / 2.0) * min(h_sp * 0.9, h_sp)
                    child_targets.append(x_pos.get(child_id, 0.0) + offset)
                targets.append((node_id, sum(child_targets) / float(len(child_targets))))
            pack_by_targets(targets)

    positions: Dict[str, Tuple[float, float]] = {}
    for node_id in node_ids:
        if node_id in connected:
            positions[node_id] = (x_pos.get(node_id, 0.0), -depth.get(node_id, 0) * v_sp)

    if isolated:
        main_max_x = max([pos[0] for pos in positions.values()] or [0.0])
        iso_x = main_max_x + h_sp * 1.6
        for idx, node_id in enumerate(isolated):
            positions[node_id] = (iso_x, -idx * v_sp)

    if original_positions:
        selected_positions = [original_positions.get(node_id, (0.0, 0.0)) for node_id in node_ids]
        anchor_x = sum(pos[0] for pos in selected_positions) / float(len(selected_positions))
        anchor_y = sum(pos[1] for pos in selected_positions) / float(len(selected_positions))
        new_positions = [positions[node_id] for node_id in node_ids]
        center_x = sum(pos[0] for pos in new_positions) / float(len(new_positions))
        center_y = sum(pos[1] for pos in new_positions) / float(len(new_positions))
        positions = {
            node_id: (x - center_x + anchor_x, y - center_y + anchor_y)
            for node_id, (x, y) in positions.items()
        }

    return positions


def get_node_positions(
    parent_path: str = "",
    node_paths: Optional[List[str]] = None,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """获取节点位置信息

    Args:
        parent_path: 父网络路径（当 node_paths 为空时使用）
        node_paths: 特定节点路径列表

    Returns:
        (success, message, positions_list)
        positions_list 每项: {name, path, x, y, type}
    """
    if hou is None:
        return False, "Houdini 环境不可用", []

    nodes = []
    if node_paths:
        for p in node_paths:
            n = hou.node(p)
            if n:
                nodes.append(n)
        if not nodes:
            return False, "指定的节点路径均无效", []
    else:
        parent = hou.node(parent_path) if parent_path else None
        if parent is None:
            try:
                editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
                if editor:
                    parent = editor.pwd()
            except Exception:
                pass
        if parent is None:
            return False, "未找到目标网络", []
        nodes = list(parent.children())
        if not nodes:
            return False, f"{parent.path()} 下没有子节点", []

    positions = []
    for n in nodes:
        pos = n.position()
        positions.append({
            "name": n.name(),
            "path": n.path(),
            "x": round(pos[0], 3),
            "y": round(pos[1], 3),
            "type": n.type().name(),
        })

    return True, f"获取了 {len(positions)} 个节点的位置", positions


# ============================================================
# NetworkBox 操作
# ============================================================

# NetworkBox 语义颜色预设
_BOX_COLORS: Dict[str, Tuple[float, float, float]] = {
    "input":      (0.2, 0.4, 0.8),   # 蓝色 - 数据输入
    "processing": (0.3, 0.7, 0.3),   # 绿色 - 几何处理
    "deform":     (0.8, 0.6, 0.2),   # 橙色 - 变形/动画
    "output":     (0.7, 0.2, 0.3),   # 红色 - 输出/渲染
    "simulation": (0.6, 0.3, 0.7),   # 紫色 - 物理模拟
    "utility":    (0.5, 0.5, 0.5),   # 灰色 - 辅助工具
}


def create_network_box(
    parent_path: str,
    name: str = "",
    comment: str = "",
    color_preset: str = "",
    node_paths: Optional[List[str]] = None
) -> Tuple[bool, str, Optional[Any]]:
    """创建 NetworkBox 并可选地将节点加入其中

    Args:
        parent_path: 父网络路径（如 /obj/geo1）
        name: box 名称
        comment: 注释（显示在标题栏，描述这组节点的功能）
        color_preset: 颜色预设（input/processing/deform/output/simulation/utility）
        node_paths: 要加入 box 的节点路径列表

    Returns:
        (success, message, network_box_or_None)
    """
    if hou is None:
        return False, "Houdini 环境不可用", None

    parent = hou.node(parent_path)
    if not parent:
        return False, f"父网络 '{parent_path}' 不存在", None

    try:
        box = parent.createNetworkBox(name or None)

        if comment:
            box.setComment(comment)

        # 设置颜色
        if color_preset and color_preset in _BOX_COLORS:
            r, g, b = _BOX_COLORS[color_preset]
            box.setColor(hou.Color((r, g, b)))

        # 添加节点
        added = []
        if node_paths:
            for np in node_paths:
                node = hou.node(np)
                if node:
                    box.addNode(node)
                    added.append(np)

            if added:
                box.fitAroundContents()

        msg = f"已创建 NetworkBox: {box.name()}"
        if comment:
            msg += f" ({comment})"
        if added:
            msg += f"，包含 {len(added)} 个节点"

        return True, msg, box
    except Exception as e:
        return False, f"创建 NetworkBox 失败: {e}", None


def add_nodes_to_box(
    parent_path: str,
    box_name: str,
    node_paths: List[str],
    auto_fit: bool = True
) -> Tuple[bool, str]:
    """将节点添加到已有的 NetworkBox

    Args:
        parent_path: 父网络路径
        box_name: 目标 NetworkBox 名称
        node_paths: 要添加的节点路径列表
        auto_fit: 是否自动调整 box 大小

    Returns:
        (success, message)
    """
    if hou is None:
        return False, "Houdini 环境不可用"

    parent = hou.node(parent_path)
    if not parent:
        return False, f"父网络 '{parent_path}' 不存在"

    # 查找 NetworkBox
    target_box = None
    for box in parent.networkBoxes():
        if box.name() == box_name:
            target_box = box
            break

    if not target_box:
        return False, f"未找到 NetworkBox: {box_name}"

    added = []
    for np in node_paths:
        node = hou.node(np)
        if node:
            target_box.addNode(node)
            added.append(np)

    if auto_fit and added:
        target_box.fitAroundContents()

    return True, f"已将 {len(added)} 个节点添加到 {box_name}"


def list_network_boxes(parent_path: str) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """列出网络中所有 NetworkBox 及其内容

    Args:
        parent_path: 父网络路径

    Returns:
        (success, message, boxes_info_list)
    """
    if hou is None:
        return False, "Houdini 环境不可用", []

    parent = hou.node(parent_path)
    if not parent:
        return False, f"父网络 '{parent_path}' 不存在", []

    boxes_info = []
    for box in parent.networkBoxes():
        nodes = box.nodes()
        boxes_info.append({
            "name": box.name(),
            "comment": box.comment() or "",
            "node_count": len(nodes),
            "nodes": [n.path() for n in nodes],
            "minimized": box.isMinimized(),
        })

    return True, f"找到 {len(boxes_info)} 个 NetworkBox", boxes_info