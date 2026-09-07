# -*- coding: utf-8 -*-
"""
Houdini MCP Client
提供节点操作的核心功能，支持 AI Agent 的工具调用
"""
from __future__ import annotations

import os
import sys
import re
import time
import json
import fnmatch
import itertools
import difflib
import contextlib
from collections import OrderedDict
from typing import Any, Optional, Dict, List, Tuple
from pathlib import Path

try:
    import hou  # type: ignore
except Exception:
    hou = None  # type: ignore


# ============================================================
# 文档检索功能已移除，请使用 web_search 查询官方文档
# ============================================================

# 强制使用本地 lib 目录中的依赖库
_lib_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'lib')
if os.path.exists(_lib_path):
    # 将 lib 目录添加到 sys.path 最前面，确保优先使用
    if _lib_path in sys.path:
        sys.path.remove(_lib_path)
    sys.path.insert(0, _lib_path)

# 导入 requests
try:
    import requests
except ImportError:
    requests = None  # type: ignore

from .settings import read_settings
from ..scoped_validation import ScopedValidationOperationResult, ScopedValidationTransaction

# 导入 RAG 检索系统
try:
    from ..doc_rag import get_doc_rag
    HAS_DOC_RAG = True
except ImportError:
    HAS_DOC_RAG = False
    print("[MCP Client] DocRAG 模块未找到，本地文档检索功能不可用")

# 导入 Skill 系统
HAS_SKILLS = False
_list_skills = None   # type: ignore
_run_skill = None     # type: ignore
try:
    from ...skills import list_skills as _list_skills, run_skill as _run_skill
    HAS_SKILLS = True
except (ImportError, ValueError, SystemError):
    pass

if not HAS_SKILLS:
    try:
        import importlib
        _skills_mod = importlib.import_module('houdini_agent.skills')
        _list_skills = _skills_mod.list_skills
        _run_skill = _skills_mod.run_skill
        HAS_SKILLS = True
    except Exception:
        pass

if not HAS_SKILLS:
    # 最后尝试：基于文件路径直接导入
    try:
        import importlib.util
        _skills_init = Path(__file__).parent.parent.parent / 'skills' / '__init__.py'
        if _skills_init.exists():
            _spec = importlib.util.spec_from_file_location('houdini_skills', str(_skills_init))
            _skills_mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_skills_mod)
            _list_skills = _skills_mod.list_skills
            _run_skill = _skills_mod.run_skill
            HAS_SKILLS = True
    except Exception:
        pass

if not HAS_SKILLS:
    print("[MCP Client] Skill 系统未加载，run_skill/list_skills 不可用")


# 抑制 Houdini Qt 主窗口在批量节点操作期间的逐次重绘，
# 退出时一次性恢复并合并刷新。降低 QHeaderView/QLayout 在高频
# OPchange 通知下的悬空指针 race（Houdini 20.5 已知偶发 SIGSEGV）。
def _display_node_has_volume(display_node) -> bool:
    """判断 display 节点几何是否含 Volume/VDB primitive（用于跳过强制 cook）。

    含体积/VDB 时返回 True，让调用方跳过 cook(force=True)，避免驱动
    GPU 体积重绘与用户视口交互竞态崩溃。判断失败时保守返回 True（跳过更安全）。
    """
    if hou is None:
        return False
    try:
        if display_node.needsToCook():
            return True
        geo = display_node.geometry()
        if geo is None:
            return False
        for ptype in (hou.primType.Volume, hou.primType.VDB):
            if geo.countPrimType(ptype) > 0:
                return True
        return False
    except Exception:
        return True


class _SuspendHoudiniUIRedraw:
    def __init__(self):
        self._mw = None
        self._prev = None

    def __enter__(self):
        if hou is None:
            return self
        try:
            mw = hou.qt.mainWindow()
        except Exception:
            return self
        if mw is None:
            return self
        try:
            self._prev = mw.updatesEnabled()
            if self._prev:
                mw.setUpdatesEnabled(False)
                self._mw = mw
        except Exception:
            self._mw = None
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._mw is not None:
            try:
                self._mw.setUpdatesEnabled(True)
            except Exception:
                pass
        return False


class HoudiniMCP:
    """Houdini 节点操作客户端
    
    提供节点网络的读取、创建、修改、删除等操作。
    设计为 AI Agent 的工具执行后端。
    """
    
    # 类级别缓存（跨实例共享，只加载一次）
    _node_types_cache: Optional[Dict[str, List[str]]] = None  # {category: [type_names]}
    _node_types_cache_time: float = 0  # 缓存时间
    _common_node_inputs_cache: Dict[str, str] = {}  # 常见节点输入信息缓存
    _ats_cache: Dict[str, Dict[str, Any]] = {}  # ATS缓存: {node_type_key: ats_data}

    # perfMon 性能分析：当前活跃的 profile 对象
    _active_perf_profile: Any = None

    # 通用工具结果分页缓存：key = "tool_name:unique_key" → 完整文本
    # 使用 OrderedDict 实现 LRU，上限 _TOOL_PAGE_CACHE_MAX 条，防止内存无限增长
    _tool_page_cache: OrderedDict = OrderedDict()
    _TOOL_PAGE_LINES = 50       # 每页行数
    _TOOL_PAGE_CACHE_MAX = 100  # 最多缓存 100 条分页结果

    def __init__(self):
        import threading
        self._stop_event: Optional[threading.Event] = None
        self._username: Optional[str] = None

    def set_user(self, username: str):
        self._username = username

    def set_stop_event(self, event):
        """设置停止事件（从 AIClient 传入，用于检测用户中断）
        
        在 execute_python / execute_shell 中通过检查此事件来支持用户中断。
        """
        self._stop_event = event

    @classmethod
    def _paginate_tool_result(cls, text: str, cache_key: str, tool_hint: str,
                              page: int = 1, page_lines: int = 0) -> str:
        """通用工具结果分页
        
        Args:
            text: 完整的文本结果
            cache_key: 缓存键（如 "get_node_parameters:/obj/geo1/box1"）
            tool_hint: 供 AI 翻页的工具调用提示（如 'get_node_parameters(node_path="/obj/geo1/box1", page=2)'）
            page: 页码（从 1 开始）
            page_lines: 每页行数，0 表示使用默认值
        """
        if not page_lines:
            page_lines = cls._TOOL_PAGE_LINES

        # LRU 写入：先移除旧条目（如果存在），再插入到末尾
        cls._tool_page_cache.pop(cache_key, None)
        cls._tool_page_cache[cache_key] = text
        # 超出上限时淘汰最旧的条目
        while len(cls._tool_page_cache) > cls._TOOL_PAGE_CACHE_MAX:
            cls._tool_page_cache.popitem(last=False)

        lines = text.split('\n')
        total_lines = len(lines)
        total_pages = max(1, (total_lines + page_lines - 1) // page_lines)

        page = max(1, min(page, total_pages))

        start = (page - 1) * page_lines
        end = min(start + page_lines, total_lines)
        page_text = '\n'.join(lines[start:end])

        if total_pages == 1:
            return page_text

        header = f"[第 {page}/{total_pages} 页, 共 {total_lines} 行]\n\n"

        if page < total_pages:
            # 将 page_hint 中的页码替换为下一页
            next_page = page + 1
            footer = f"\n\n[第 {page}/{total_pages} 页] 还有更多内容，调用 {tool_hint.replace(f'page={page}', f'page={next_page}')} 查看下一页"
        else:
            footer = f"\n\n[第 {page}/{total_pages} 页 - 最后一页]"

        return header + page_text + footer

    # ========================================
    # 网络结构读取（轻量级，只返回拓扑信息）
    # ========================================
    
    def get_network_structure(self, network_path: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
        """获取节点网络的拓扑结构（节点名称、类型、连接关系）
        
        这是一个轻量级操作，不读取参数详情。
        
        Args:
            network_path: 网络路径，如 '/obj/geo1'。None 则使用当前网络。
        
        Returns:
            (success, data) 其中 data 包含:
            {
                "network_path": str,
                "network_type": str,
                "nodes": [
                    {
                        "name": str,
                        "path": str,
                        "type": str,
                        "type_label": str,
                        "is_displayed": bool,
                        "has_errors": bool,
                        "position": [x, y]
                    }
                ],
                "connections": [
                    {
                        "from": str,  # 源节点路径
                        "to": str,    # 目标节点路径
                        "input_index": int,
                        "input_label": str  # 输入端口名称（如有）
                    }
                ]
            }
        """
        if hou is None:
            return False, {"error": "未检测到 Houdini API（hou 模块）"}
        
        # 获取网络节点
        if network_path:
            network = hou.node(network_path)
            if network is None:
                return False, {"error": f"未找到网络: {network_path}"}
        else:
            network = self._current_network()
            if network is None:
                return False, {"error": "未找到当前网络，请打开网络编辑器"}
        
        nodes_data = []
        connections_data = []
        
        try:
            children = network.children()
            
            for node in children:
                try:
                    node_type = node.type()
                    category = node_type.category().name() if node_type else "Unknown"
                    type_name = node_type.name() if node_type else "unknown"
                    
                    # 获取位置
                    pos = node.position()
                    position = [pos[0], pos[1]] if pos else [0, 0]
                    
                    # 检查是否有错误
                    has_errors = False
                    try:
                        errors = node.errors()
                        has_errors = bool(errors)
                    except Exception:
                        pass
                    
                    node_info = {
                        "name": node.name(),
                        "path": node.path(),
                        "type": f"{category.lower()}/{type_name}",
                        "type_label": node_type.description() if node_type else "",
                        "is_displayed": node.isDisplayFlagSet() if hasattr(node, 'isDisplayFlagSet') else False,
                        "is_bypassed": node.isBypassed() if hasattr(node, 'isBypassed') else False,
                        "has_errors": has_errors,
                        "position": position
                    }
                    
                    # 检测 wrangle 类型节点，提取 VEX 代码
                    _wrangle_keywords = ('wrangle', 'snippet', 'vopnet')
                    if any(kw in type_name.lower() for kw in _wrangle_keywords):
                        try:
                            snippet = node.parm("snippet")
                            if snippet:
                                code = snippet.eval()
                                if code and code.strip():
                                    node_info["vex_code"] = code.strip()
                        except Exception:
                            pass
                    # 也检测 python 脚本节点
                    if 'python' in type_name.lower():
                        try:
                            for pname in ("python", "code", "script"):
                                parm = node.parm(pname)
                                if parm:
                                    code = parm.eval()
                                    if code and code.strip():
                                        node_info["python_code"] = code.strip()
                                        break
                        except Exception:
                            pass
                    
                    nodes_data.append(node_info)
                    
                    # 收集连接关系（含输入端口名称）
                    for input_idx, input_node in enumerate(node.inputs()):
                        if input_node is not None:
                            conn_info = {
                                "from": input_node.path(),
                                "to": node.path(),
                                "input_index": input_idx,
                            }
                            # 尝试获取输入端口标签
                            try:
                                input_label = node_type.inputLabel(input_idx)
                                if input_label:
                                    conn_info["input_label"] = input_label
                            except Exception:
                                pass
                            connections_data.append(conn_info)
                except Exception:
                    continue
            
            # 收集 NetworkBox 信息
            boxed_node_paths = set()
            boxes_data = []
            try:
                for box in network.networkBoxes():
                    box_nodes = box.nodes()
                    box_node_paths = [n.path() for n in box_nodes]
                    boxed_node_paths.update(box_node_paths)
                    boxes_data.append({
                        "name": box.name(),
                        "comment": box.comment() or "",
                        "node_count": len(box_nodes),
                        "nodes": box_node_paths,
                    })
            except Exception:
                pass  # networkBoxes() 可能在某些网络类型下不可用

            return True, {
                "network_path": network.path(),
                "network_type": network.type().name() if network.type() else "unknown",
                "node_count": len(nodes_data),
                "nodes": nodes_data,
                "connections": connections_data,
                "network_boxes": boxes_data,
                "boxed_node_paths": list(boxed_node_paths),
            }
        except Exception as e:
            return False, {"error": f"读取网络结构失败: {str(e)}"}

    def get_network_structure_text(self, network_path: Optional[str] = None,
                                   box_name: Optional[str] = None) -> Tuple[bool, str]:
        """获取节点网络结构的文本描述（适合 AI 阅读）
        
        三种模式：
        1. 无 box_name 且网络有 NetworkBox → 概览模式（折叠 box，省 token）
        2. 有 box_name → 钻入模式（只展示该 box 内节点）
        3. 无 box_name 且网络无 NetworkBox → 传统全展开模式
        """
        ok, data = self.get_network_structure(network_path)
        if not ok:
            return False, data.get("error", "未知错误")
        
        boxes = data.get("network_boxes", [])
        boxed_paths = set(data.get("boxed_node_paths", []))

        # ── 钻入模式：只展示指定 box 内的节点 ──
        if box_name:
            target = next((b for b in boxes if b["name"] == box_name), None)
            if not target:
                available = ", ".join(b["name"] for b in boxes) if boxes else "(无)"
                return False, f"未找到 NetworkBox: {box_name}。可用的 box: {available}"
            
            target_paths = set(target["nodes"])
            box_nodes = [n for n in data["nodes"] if n["path"] in target_paths]
            box_conns = [c for c in data["connections"]
                         if c["from"] in target_paths and c["to"] in target_paths]
            # box 与外部的跨组连接
            cross_conns = [c for c in data["connections"]
                           if (c["from"] in target_paths) != (c["to"] in target_paths)]
            
            lines = [
                f"## NetworkBox 详情: {box_name}",
                f"注释: {target['comment'] or '(无)'}",
                f"节点数量: {target['node_count']}",
                "", "### 节点列表:"
            ]
            wrangle_details = []
            self._format_node_list(box_nodes, lines, wrangle_details)
            
            if box_conns:
                lines.append("")
                lines.append("### 内部连接:")
                for conn in box_conns:
                    lines.append(self._format_connection(conn))
            
            if cross_conns:
                lines.append("")
                lines.append("### 跨组连接（与其他 box / 未分组节点）:")
                for conn in cross_conns:
                    lines.append(self._format_connection(conn))
            
            if wrangle_details:
                lines.append("")
                lines.append("### 节点内嵌代码:")
                for detail in wrangle_details:
                    lines.append(detail)
            
            return True, "\n".join(lines)

        # ── 概览模式：有 NetworkBox 时折叠显示（核心省 token 逻辑） ──
        if boxes:
            unboxed_nodes = [n for n in data["nodes"] if n["path"] not in boxed_paths]
            
            lines = [
                f"## 网络结构: {data['network_path']}",
                f"网络类型: {data['network_type']}",
                f"节点总数: {data['node_count']}",
                f"NetworkBox 分组: {len(boxes)} 个（包含 {len(boxed_paths)} 个节点）",
                "",
                "### NetworkBox 概览:"
            ]
            for b in boxes:
                # 统计 box 内节点类型摘要（取前 3 种）
                box_paths_set = set(b["nodes"])
                type_counts: Dict[str, int] = {}
                for n in data["nodes"]:
                    if n["path"] in box_paths_set:
                        short_type = n["type"].split("/")[-1] if "/" in n["type"] else n["type"]
                        type_counts[short_type] = type_counts.get(short_type, 0) + 1
                top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:3]
                types_str = ", ".join(f"{t}×{c}" for t, c in top_types)
                if len(type_counts) > 3:
                    types_str += f" 等{len(type_counts)}种"
                
                lines.append(f"📦 **{b['name']}**: {b['comment'] or '(无注释)'} — {b['node_count']} 个节点 [{types_str}]")
            
            lines.append(f"\n💡 使用 get_network_structure(box_name=\"box名称\") 查看某个分组的详细节点")
            
            if unboxed_nodes:
                lines.append(f"\n### 未分组节点 ({len(unboxed_nodes)} 个):")
                wrangle_details = []
                self._format_node_list(unboxed_nodes, lines, wrangle_details)
                if wrangle_details:
                    lines.append("")
                    lines.append("### 未分组节点内嵌代码:")
                    for detail in wrangle_details:
                        lines.append(detail)
            
            # 跨组连接：两端不在同一个 box 中的连接
            cross_conns = []
            # 构建 node_path → box_name 映射
            path_to_box: Dict[str, str] = {}
            for b in boxes:
                for np in b["nodes"]:
                    path_to_box[np] = b["name"]
            for conn in data["connections"]:
                src_box = path_to_box.get(conn["from"], "__unboxed__")
                dst_box = path_to_box.get(conn["to"], "__unboxed__")
                if src_box != dst_box:
                    cross_conns.append(conn)
            
            if cross_conns:
                lines.append("")
                lines.append("### 跨组连接:")
                for conn in cross_conns:
                    from_name = conn['from'].split('/')[-1]
                    to_name = conn['to'].split('/')[-1]
                    src_box = path_to_box.get(conn["from"], "未分组")
                    dst_box = path_to_box.get(conn["to"], "未分组")
                    idx = conn['input_index']
                    label = conn.get('input_label', '')
                    port_str = f"{label}({idx})" if label else str(idx)
                    lines.append(f"- [{src_box}] {from_name} → {to_name}[{port_str}] [{dst_box}]")
            
            return True, "\n".join(lines)

        # ── 传统模式：无 NetworkBox，全部展开（兼容旧行为） ──
        lines = [
            f"## 网络结构: {data['network_path']}",
            f"网络类型: {data['network_type']}",
            f"节点数量: {data['node_count']}",
            "",
            "### 节点列表:"
        ]
        
        wrangle_details = []
        self._format_node_list(data['nodes'], lines, wrangle_details)
        
        if data['connections']:
            lines.append("")
            lines.append("### 连接关系:")
            for conn in data['connections']:
                lines.append(self._format_connection(conn))
        
        if wrangle_details:
            lines.append("")
            lines.append("### 节点内嵌代码:")
            for detail in wrangle_details:
                lines.append(detail)
        
        return True, "\n".join(lines)

    @staticmethod
    def _format_node_list(nodes: List[Dict], lines: List[str], wrangle_details: List[str]):
        """格式化节点列表到 lines，收集代码详情到 wrangle_details"""
        for node in nodes:
            status = []
            if node.get('is_displayed'):
                status.append("显示")
            if node.get('is_bypassed'):
                status.append("BYPASS")
            if node.get('has_errors'):
                status.append("错误")
            status_str = f" [{', '.join(status)}]" if status else ""
            
            has_code = ""
            if node.get('vex_code'):
                has_code = " [含VEX代码]"
            elif node.get('python_code'):
                has_code = " [含Python代码]"
            
            lines.append(f"- `{node['name']}` ({node['type']}){status_str}{has_code}")
            
            bypass_tag = " [BYPASSED — inactive, 仅供参考]" if node.get('is_bypassed') else ""
            if node.get('vex_code'):
                code = node['vex_code']
                code_lines = code.split('\n')
                if len(code_lines) > 30:
                    code = '\n'.join(code_lines[:30]) + f'\n// ... 共 {len(code_lines)} 行，已截断'
                wrangle_details.append(
                    f"#### `{node['name']}` VEX 代码{bypass_tag}:\n```vex\n{code}\n```"
                )
            elif node.get('python_code'):
                code = node['python_code']
                code_lines = code.split('\n')
                if len(code_lines) > 30:
                    code = '\n'.join(code_lines[:30]) + f'\n# ... 共 {len(code_lines)} 行，已截断'
                wrangle_details.append(
                    f"#### `{node['name']}` Python 代码{bypass_tag}:\n```python\n{code}\n```"
                )

    @staticmethod
    def _format_connection(conn: Dict[str, Any], prefix: str = "- ") -> str:
        """格式化单条连接信息，包含输入端口名称（如有）"""
        from_name = conn['from'].split('/')[-1]
        to_name = conn['to'].split('/')[-1]
        idx = conn['input_index']
        label = conn.get('input_label', '')
        if label:
            port_str = f"{label}({idx})"
        else:
            port_str = str(idx)
        return f"{prefix}{from_name} → {to_name}[{port_str}]"

    # ========================================
    # ATS (Abstract Type System) 构建
    # ========================================
    
    def _build_ats(self, node_type: Any) -> Dict[str, Any]:
        """构建节点类型的ATS（抽象类型系统）
        
        Args:
            node_type: Houdini节点类型对象
            
        Returns:
            ATS数据字典，包含参数模板、默认值等信息
        """
        if hou is None or node_type is None:
            return {}
        
        # 生成缓存键
        type_key = f"{node_type.category().name().lower()}/{node_type.name()}"
        
        # 检查缓存
        if type_key in HoudiniMCP._ats_cache:
            return HoudiniMCP._ats_cache[type_key]
        
        try:
            # 获取参数模板
            parm_template_group = node_type.parmTemplateGroup()
            ats_data = {
                "type": type_key,
                "type_label": node_type.description() if hasattr(node_type, 'description') else "",
                "input_count": {
                    "min": node_type.minNumInputs() if hasattr(node_type, 'minNumInputs') else 0,
                    "max": node_type.maxNumInputs() if hasattr(node_type, 'maxNumInputs') else 0,
                },
                "output_count": {
                    "min": node_type.minNumOutputs() if hasattr(node_type, 'minNumOutputs') else 0,
                    "max": node_type.maxNumOutputs() if hasattr(node_type, 'maxNumOutputs') else 0,
                },
                "parameters": {}
            }
            
            # 提取参数模板信息（只包含参数名、类型、默认值）
            if parm_template_group:
                for parm_template in parm_template_group.parmTemplates():
                    try:
                        parm_name = parm_template.name()
                        parm_type = parm_template.type().name() if hasattr(parm_template, 'type') else "unknown"
                        
                        # 获取默认值
                        default_value = None
                        if hasattr(parm_template, 'defaultValue'):
                            try:
                                default_value = parm_template.defaultValue()
                                # 格式化浮点数
                                if isinstance(default_value, float):
                                    default_value = round(default_value, 6)
                                elif isinstance(default_value, tuple):
                                    default_value = tuple(round(v, 6) if isinstance(v, float) else v for v in default_value)
                            except Exception:
                                pass
                        
                        # 只保存关键信息
                        ats_data["parameters"][parm_name] = {
                            "type": parm_type,
                            "default_value": default_value,
                            "is_hidden": parm_template.isHidden() if hasattr(parm_template, 'isHidden') else False,
                        }
                    except Exception:
                        continue
            
            # 缓存ATS数据
            HoudiniMCP._ats_cache[type_key] = ats_data
            return ats_data
            
        except Exception:
            return {}
    
    # ========================================
    # 节点详情读取（优化版：先构建ATS，再读取部分上下文）
    # ========================================
    
    def get_node_details(self, node_path: str) -> Tuple[bool, Dict[str, Any]]:
        """获取指定节点的详细信息（优化版：先构建ATS，再读取部分上下文）
        
        流程：
        1. 先构建ATS（节点类型的抽象信息，包括参数模板、默认值等）
        2. 针对特定节点只读取部分上下文（非默认参数、错误、连接等）
        
        Args:
            node_path: 节点完整路径
        
        Returns:
            (success, data) 其中 data 包含:
            {
                "name": str,
                "path": str,
                "type": str,
                "type_label": str,
                "comment": str,
                "flags": {...},
                "errors": [...],
                "inputs": [...],
                "outputs": [...],
                "parameters": {...},  # 只包含非默认参数
                "ats": {...}  # ATS信息（可选，用于参考）
            }
        """
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        
        node = hou.node(node_path)
        if node is None:
            return False, {"error": f"未找到节点: {node_path}"}
        
        try:
            node_type = node.type()
            category = node_type.category().name() if node_type else "Unknown"
            type_name = node_type.name() if node_type else "unknown"
            type_key = f"{category.lower()}/{type_name}"
            
            # 第一步：构建ATS（节点类型的抽象信息）
            ats_data = self._build_ats(node_type)
            
            # 第二步：读取节点特定上下文（只读取部分信息）
            # 基本信息
            data = {
                "name": node.name(),
                "path": node.path(),
                "type": type_key,
                "type_label": node_type.description() if node_type else "",
                "comment": node.comment().strip() if node.comment() else "",
            }
            
            # 状态信息
            data["flags"] = {
                "display": node.isDisplayFlagSet() if hasattr(node, 'isDisplayFlagSet') else False,
                "render": node.isRenderFlagSet() if hasattr(node, 'isRenderFlagSet') else False,
                "bypass": node.isBypassed() if hasattr(node, 'isBypassed') else False,
                "locked": node.isLocked() if hasattr(node, 'isLocked') else False,
            }
            
            # 错误信息（重要，必须读取）
            errors = []
            try:
                errs = node.errors()
                if errs:
                    errors = list(errs)
            except Exception:
                pass
            data["errors"] = errors
            
            # 输入输出连接（重要，必须读取）
            inputs = []
            for i, inp in enumerate(node.inputs()):
                entry: Dict[str, Any] = {"index": i, "node": inp.path() if inp is not None else None}
                try:
                    entry["label"] = node.inputLabel(i)
                except Exception:
                    pass
                inputs.append(entry)
            data["inputs"] = inputs
            
            outputs = []
            try:
                for conn in node.outputConnections():
                    out_node = conn.outputNode()
                    outputs.append({
                        "node": out_node.path() if out_node else None,
                        "output_index": conn.outputIndex(),
                        "input_index": conn.inputIndex(),
                    })
            except Exception:
                for out in node.outputs():
                    outputs.append({"node": out.path()})
            data["outputs"] = outputs
            
            # 只读取非默认参数（部分上下文）
            params = {}
            for parm in node.parms():
                try:
                    if parm.isHidden() or parm.isDisabled():
                        continue
                    
                    parm_name = parm.name()
                    
                    # 检查是否为默认值
                    is_default = False
                    try:
                        is_default = parm.isAtDefault()
                    except Exception:
                        # 如果无法判断，则读取当前值
                        pass
                    
                    # 只保存非默认参数
                    if not is_default:
                        value = parm.eval()
                        
                        # 格式化浮点数
                        if isinstance(value, float):
                            value = round(value, 6)
                        elif isinstance(value, tuple):
                            value = tuple(round(v, 6) if isinstance(v, float) else v for v in value)
                        
                        params[parm_name] = {
                            "value": value,
                            "is_default": False
                        }
                except Exception:
                    continue
            
            data["parameters"] = params
            data["parameter_count"] = len(node.parms())
            data["child_count"] = len(node.children()) if hasattr(node, "children") else 0
            try:
                data["position"] = [node.position()[0], node.position()[1]]
            except Exception:
                pass
            
            # 可选：添加ATS引用（用于参考，但不包含在主要数据中）
            # 如果需要完整ATS信息，可以通过 get_node_type_ats 单独获取
            
            return True, data
        except Exception as e:
            return False, {"error": f"读取节点详情失败: {str(e)}"}

    def inspect_node(self, node_path: str, include_params: bool = True,
                     max_params: int = 40, include_errors: bool = True,
                     include_connections: bool = True,
                     compact: bool = False) -> Tuple[bool, Dict[str, Any]]:
        """Return structured node state for quick AI inspection."""
        ok, data = self.get_node_details(node_path)
        if not ok:
            return ok, data

        max_params = max(0, min(int(max_params), 200))
        if compact:
            include_params = False
            include_connections = False
            include_errors = False

        flags = data.get("flags", {}) or {}
        bypassed = bool(flags.get("bypass"))
        # 拼一个人类可读的 active_state，让模型读 JSON 时不会忽略 bypass
        if bypassed:
            active_state = "BYPASSED (节点已旁路，对下游无影响，不应据此推理网络行为)"
        elif flags.get("locked"):
            active_state = "LOCKED (节点已锁定缓存几何)"
        else:
            active_state = "active"

        result: Dict[str, Any] = {
            "name": data.get("name"),
            "path": data.get("path"),
            "type": data.get("type"),
            "type_label": data.get("type_label"),
            "comment": data.get("comment"),
            "bypassed": bypassed,
            "active_state": active_state,
            "flags": flags,
            "position": data.get("position"),
            "child_count": data.get("child_count", 0),
            "parameter_count": data.get("parameter_count", 0),
        }

        if include_errors:
            result["errors"] = data.get("errors", [])

        if include_connections:
            result["inputs"] = data.get("inputs", [])
            result["outputs"] = data.get("outputs", [])

        if include_params:
            params = data.get("parameters", {})
            param_items = list(params.items())[:max_params]
            result["parameters"] = {name: value for name, value in param_items}
            result["parameters_truncated"] = len(params) > len(param_items)
            result["non_default_parameter_count"] = len(params)

        return True, result

    def get_node_details_text(self, node_path: str) -> Tuple[bool, str]:
        """获取节点详情的文本描述（优化版：只显示部分上下文）"""
        ok, data = self.get_node_details(node_path)
        if not ok:
            return False, data.get("error", "未知错误")
        
        lines = [
            f"## 节点: {data['name']}",
            f"路径: {data['path']}",
            f"类型: {data['type']} ({data['type_label']})",
        ]
        
        if data['comment']:
            lines.append(f"备注: {data['comment']}")
        
        # 状态
        flags = data['flags']
        status = []
        if flags['display']:
            status.append("显示")
        if flags['render']:
            status.append("渲染")
        if flags['bypass']:
            status.append("旁路")
        if flags['locked']:
            status.append("锁定")
        if status:
            lines.append(f"状态: {', '.join(status)}")
        
        # 错误（重要上下文）
        if data['errors']:
            lines.append("")
            lines.append("### 错误:")
            for err in data['errors']:
                lines.append(f"- {err}")
        
        # 连接（重要上下文）
        if data['inputs']:
            lines.append("")
            lines.append("### 输入连接:")
            for inp in data['inputs']:
                lines.append(f"- [{inp['index']}] ← {inp['node']}")
        
        if data['outputs']:
            lines.append("")
            lines.append("### 输出连接:")
            for out in data['outputs']:
                lines.append(f"- → {out}")
        
        # 非默认参数（部分上下文，已优化）
        lines.append("")
        lines.append("### 参数（非默认值）:")
        if data['parameters']:
            for name, info in data['parameters'].items():
                value = info['value']
                if isinstance(value, tuple):
                    value_str = "(" + ", ".join(str(v) for v in value) + ")"
                else:
                    value_str = str(value)
                lines.append(f"- {name} = {value_str}")
        else:
            lines.append("（所有参数均为默认值）")
        
        return True, "\n".join(lines)
    
    def get_node_type_ats(self, node_type: str, category: str = "sop") -> Tuple[bool, Dict[str, Any]]:
        """获取节点类型的ATS（抽象类型系统）信息
        
        Args:
            node_type: 节点类型名称，如 'box', 'scatter'
            category: 节点类别，默认 'sop'
        
        Returns:
            (success, ats_data) ATS数据包含参数模板、默认值等信息
        """
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        
        try:
            # 获取节点类型对象
            categories = hou.nodeTypeCategories()
            cat_obj = categories.get(category.capitalize()) or categories.get(category.upper())
            if not cat_obj:
                return False, {"error": f"未找到类别: {category}"}
            
            node_type_obj = None
            type_lower = node_type.lower()
            for name, nt in cat_obj.nodeTypes().items():
                if name.lower() == type_lower or name.lower().endswith(f"::{type_lower}"):
                    node_type_obj = nt
                    break
            
            if not node_type_obj:
                return False, {"error": f"未找到节点类型: {node_type}"}
            
            # 构建ATS
            ats_data = self._build_ats(node_type_obj)
            if not ats_data:
                return False, {"error": "构建ATS失败"}
            
            return True, ats_data
            
        except Exception as e:
            return False, {"error": f"获取ATS失败: {str(e)}"}

    # ========================================
    # 错误和警告检查
    # ========================================
    
    def check_node_errors(self, node_path: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
        """检查节点或网络中的错误和警告
        
        Args:
            node_path: 节点路径。如果是网络路径，检查其下所有节点。如果为 None，检查当前网络。
        
        Returns:
            (success, data) 其中 data 包含 errors 和 warnings 列表
        """
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        
        try:
            # 确定要检查的节点
            if node_path:
                target = hou.node(node_path)
                if target is None:
                    return False, {"error": f"未找到节点: {node_path}"}
            else:
                # 获取当前网络
                try:
                    pane = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
                    target = pane.pwd() if pane else hou.node('/obj')
                except Exception:
                    target = hou.node('/obj')
            
            results = {
                "checked_path": target.path(),
                "total_nodes": 0,
                "error_count": 0,
                "warning_count": 0,
                "errors": [],
                "warnings": []
            }
            
            # 如果是容器节点，检查所有子节点
            if hasattr(target, 'children') and target.children():
                nodes_to_check = target.allSubChildren() if hasattr(target, 'allSubChildren') else target.children()
            else:
                nodes_to_check = [target]
            
            results["total_nodes"] = len(nodes_to_check)
            
            for node in nodes_to_check:
                try:
                    # 检查错误
                    errors = node.errors() if hasattr(node, 'errors') else []
                    for err in errors:
                        results["errors"].append({
                            "node_path": node.path(),
                            "node_name": node.name(),
                            "node_type": node.type().name() if node.type() else "unknown",
                            "message": str(err)
                        })
                        results["error_count"] += 1
                    
                    # 检查警告
                    warnings = node.warnings() if hasattr(node, 'warnings') else []
                    for warn in warnings:
                        results["warnings"].append({
                            "node_path": node.path(),
                            "node_name": node.name(),
                            "node_type": node.type().name() if node.type() else "unknown",
                            "message": str(warn)
                        })
                        results["warning_count"] += 1
                        
                except Exception:
                    continue
            
            return True, results
            
        except Exception as e:
            return False, {"error": f"检查错误失败: {str(e)}"}
    
    def check_node_errors_text(self, node_path: Optional[str] = None) -> Tuple[bool, str]:
        """获取错误检查的文本描述"""
        ok, data = self.check_node_errors(node_path)
        if not ok:
            return False, data.get("error", "未知错误")
        
        lines = [
            f"## 错误检查报告",
            f"检查路径: {data['checked_path']}",
            f"检查节点数: {data['total_nodes']}",
            f"错误数: {data['error_count']}",
            f"警告数: {data['warning_count']}",
        ]
        
        if data['errors']:
            lines.append("")
            lines.append("### 错误:")
            for err in data['errors']:
                lines.append(f"- **{err['node_name']}** ({err['node_type']}): {err['message']}")
        
        if data['warnings']:
            lines.append("")
            lines.append("### 警告:")
            for warn in data['warnings']:
                lines.append(f"- **{warn['node_name']}** ({warn['node_type']}): {warn['message']}")
        
        if not data['errors'] and not data['warnings']:
            lines.append("")
            lines.append("**没有发现错误或警告。**")
        
        return True, "\n".join(lines)

    def verify_network(self, parent_path: str, cook_display: bool = True) -> Tuple[bool, str]:
        """核查一个网络的所有 child 节点：errors / warnings / flags / display 节点几何 evidence。

        "中键查每个节点" 的一次性版本：建完/改完网络后调一次，比逐个 check_errors 高效。

        Args:
            parent_path: 父网络路径（如 '/obj/geo1'）
            cook_display: 是否强制 cook display 节点（False 时只读已有 errors，不重新 cook）
        """
        if hou is None:
            return False, "未检测到 Houdini API"

        parent = hou.node(parent_path)
        if parent is None:
            return False, f"未找到网络: {parent_path}"

        # 强制 cook display node，让上游错误浮现
        display = None
        if hasattr(parent, "displayNode"):
            try:
                display = parent.displayNode()
            except Exception:
                display = None
        # ★ Manual 模式检测：Agent 运行期间 Cook Guard 会把更新模式切为 Manual，
        #   此时 cook(force=False) 对时间戳未过期的节点可能直接返回 stale 缓存，
        #   导致几何 evidence 读到旧的 0 值（改了源/连线也不反映）。
        manual_mode = False
        try:
            manual_mode = (hou.updateModeSetting() == hou.updateMode.Manual)
        except Exception:
            manual_mode = False
        if cook_display and display is not None:
            try:
                # Manual 模式下用 force=True 强制重算，绕过 stale 缓存；
                # 但含 Volume/VDB 的节点跳过强制 cook（GPU 体积重绘竞态崩溃风险）。
                force = manual_mode and not _display_node_has_volume(display)
                display.cook(force=force)
            except Exception as exc:
                # cook 失败本身就是 evidence，不当作工具错误
                pass

        # 收集每个 child 的报告
        child_reports: List[Dict[str, Any]] = []
        error_nodes: List[str] = []
        warning_nodes: List[str] = []
        for child in parent.children():
            errs: List[str] = []
            warns: List[str] = []
            try:
                errs = list(child.errors())
            except Exception:
                pass
            try:
                warns = list(child.warnings())
            except Exception:
                pass
            flags = {}
            try:
                flags["display"] = bool(child.isDisplayFlagSet()) if hasattr(child, "isDisplayFlagSet") else None
            except Exception:
                flags["display"] = None
            try:
                flags["render"] = bool(child.isRenderFlagSet()) if hasattr(child, "isRenderFlagSet") else None
            except Exception:
                flags["render"] = None
            try:
                flags["bypass"] = bool(child.isBypassed()) if hasattr(child, "isBypassed") else None
            except Exception:
                flags["bypass"] = None
            child_reports.append({
                "path": child.path(),
                "name": child.name(),
                "type": child.type().name(),
                "errors": errs,
                "warnings": warns,
                "flags": flags,
            })
            if errs:
                error_nodes.append(child.path())
            if warns:
                warning_nodes.append(child.path())

        # display 节点几何 evidence（仅 SOP 容器）
        geom_summary = None
        if display is not None:
            try:
                geo = display.geometry()
                if geo is not None:
                    geom_summary = {
                        "points": int(geo.intrinsicValue("pointcount")),
                        "prims": int(geo.intrinsicValue("primitivecount")),
                        "vertices": int(geo.intrinsicValue("vertexcount")),
                    }
            except Exception:
                pass

        # 格式化输出
        lines = [
            f"## 网络核查报告: {parent.path()}",
            f"子节点数: {len(child_reports)}",
            f"错误节点: {len(error_nodes)}",
            f"警告节点: {len(warning_nodes)}",
            f"健康: {'是' if not error_nodes else '否'}",
        ]
        if display is not None:
            lines.append(f"Display 节点: {display.path()}")
        if geom_summary:
            lines.append(
                f"Display 几何: points={geom_summary['points']}, "
                f"prims={geom_summary['prims']}, vertices={geom_summary['vertices']}")
            # ★ 几何为空 + Manual 模式：0 可能是 stale 缓存假象而非真实空几何。
            #   给 Agent 明确诊断方向，避免把「0」当事实反复死循环。
            if geom_summary['points'] == 0 and geom_summary['prims'] == 0 and manual_mode:
                lines.append(
                    "⚠️ 几何为 0 且当前处于 **Manual 更新模式**：本次已对 display 节点强制 "
                    "cook 后仍为 0，若源节点参数正常，请优先怀疑上游连线/过滤参数问题；"
                    "如需排除缓存干扰，可让用户临时切回 Auto 更新模式再核查。")

        if error_nodes:
            lines.append("")
            lines.append("### 报错节点:")
            for r in child_reports:
                if r["errors"]:
                    for err in r["errors"]:
                        lines.append(f"- **{r['name']}** ({r['type']}): {err}")

        if warning_nodes:
            lines.append("")
            lines.append("### 告警节点:")
            for r in child_reports:
                if r["warnings"]:
                    for warn in r["warnings"]:
                        lines.append(f"- **{r['name']}** ({r['type']}): {warn}")

        if not error_nodes and not warning_nodes:
            lines.append("")
            lines.append("**所有 child 节点无错误、无警告。**")

        # flags 概览（display/render/bypass）
        notable_flags = [
            f"{r['name']}[{','.join(k[0].upper() for k, v in r['flags'].items() if v)}]"
            for r in child_reports
            if any(r['flags'].values())
        ]
        if notable_flags:
            lines.append("")
            lines.append("### 标志:")
            lines.append(", ".join(notable_flags))

        return True, "\n".join(lines)

    # ========================================
    # 选中节点操作
    # ========================================
    
    def describe_selection(self, limit: int = None, include_all_params: bool = False) -> Tuple[bool, str]:
        """读取选中节点的信息"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        nodes = hou.selectedNodes()
        if not nodes:
            return False, "未选择任何节点"
        
        lines: List[str] = []
        target_nodes = nodes if limit is None else nodes[:limit]
        for node in target_nodes:
            ok, text = self.get_node_details_text(node.path())
            if ok:
                lines.append(text)
                lines.append("")
        
        if limit is not None and len(nodes) > limit:
            lines.append(f"（仅展示前 {limit} 个节点，共选择 {len(nodes)} 个）")
        else:
            lines.append(f"（共 {len(nodes)} 个选中节点）")
        
        return True, "\n".join(lines)

    # ========================================
    # 节点搜索（使用缓存）
    # ========================================
    
    def _get_node_types_index(self) -> Dict[str, List[Tuple[str, str, str]]]:
        """获取节点类型索引（带缓存）
        
        返回: {category_lower: [(type_name, description, full_path), ...]}
        """
        import time as _time
        cache_duration = 300  # 5分钟缓存
        
        if (HoudiniMCP._node_types_cache is not None and 
            _time.time() - HoudiniMCP._node_types_cache_time < cache_duration):
            return HoudiniMCP._node_types_cache
        
        if hou is None:
            return {}
        
        index: Dict[str, List[Tuple[str, str, str]]] = {}
        try:
            for cat_name, cat in hou.nodeTypeCategories().items():
                cat_lower = cat_name.lower()
                index[cat_lower] = []
                for type_name, node_type in cat.nodeTypes().items():
                    try:
                        desc = node_type.description()
                        index[cat_lower].append((type_name, desc, f"{cat_lower}/{type_name}"))
                    except Exception:
                        continue
            
            HoudiniMCP._node_types_cache = index
            HoudiniMCP._node_types_cache_time = _time.time()
        except Exception:
            pass
        
        return index
    
    def search_nodes(self, keyword: str, limit: int = 12,
                     category: Optional[str] = None) -> Tuple[bool, str]:
        """搜索节点类型（使用缓存）

        Args:
            keyword: 搜索关键词
            limit: 最大结果数
            category: 节点类别过滤（sop/obj/dop/vop/cop 等），None 或 'all' 表示全部
        """
        if hou is None:
            return False, "未检测到 Houdini API"
        if not keyword:
            return False, "请输入关键字"
        
        kw = keyword.lower()
        cat_filter = category.lower() if category and category.lower() != "all" else None
        matches: List[str] = []
        
        # 使用缓存的节点类型索引
        index = self._get_node_types_index()
        for cat_name, types in index.items():
            if cat_filter and cat_name != cat_filter:
                continue
            for type_name, desc, full_path in types:
                if kw in full_path.lower() or kw in desc.lower():
                    matches.append(f"- `{full_path}` — {desc}")
        
        if not matches:
            scope = f"（类别 '{category}'）" if cat_filter else ""
            return False, f"未找到包含 '{keyword}' 的节点类型{scope}"
        
        if len(matches) > limit:
            extra = len(matches) - limit
            matches = matches[:limit] + [f"… 还有 {extra} 个结果"]
        
        return True, "\n".join(matches)

    def semantic_search_nodes(self, description: str, category: str = "sop") -> Tuple[bool, str]:
        """语义搜索节点 - 通过自然语言描述找到合适的节点
        
        内置常用节点的语义映射
        """
        if hou is None:
            return False, "未检测到 Houdini API"
        
        # 语义映射表：描述关键词 -> 节点类型
        # 格式: "关键词": ["节点1", "节点2", ...]
        semantic_map = {
            # 点操作
            "分布点": ["scatter", "pointsfromvolume"],
            "撒点": ["scatter"],
            "随机点": ["scatter", "add"],
            "删除点": ["blast", "delete"],
            "合并点": ["fuse"],
            "点云": ["scatter"],
            
            # 复制操作
            "复制到点": ["copytopoints"],
            "实例化": ["copytopoints"],
            "复制物体": ["copytopoints"],
            "克隆": ["copytopoints"],
            "instance": ["copytopoints"],
            
            # 变形操作
            "噪波": ["mountain"],
            "noise": ["mountain", "attribnoise"],
            "变形": ["transform", "bend", "twist"],
            "平滑": ["smooth", "relax"],
            "挤出": ["polyextrude"],
            "细分": ["subdivide", "remesh"],
            
            # 创建几何体
            "盒子": ["box"],
            "box": ["box"],
            "球": ["sphere"],
            "圆柱": ["tube"],
            "平面": ["grid"],
            "grid": ["grid"],
            "曲线": ["curve", "line"],
            
            # ⭐ 地形相关（常见需求，详细映射）
            "地形": ["grid", "mountain"],  # 地形 = grid + mountain
            "terrain": ["grid", "mountain"],
            "地面": ["grid"],
            "山": ["mountain"],
            "起伏": ["mountain"],
            "高度场": ["heightfield"],
            "heightfield": ["heightfield"],
            
            # 属性操作
            "设置属性": ["attribwrangle"],
            "颜色": ["color", "attribwrangle"],
            "法线": ["normal"],
            "UV": ["uvproject", "uvunwrap"],
            
            # 连接操作
            "合并": ["merge"],
            "merge": ["merge"],
            "分离": ["split", "blast"],
            "布尔": ["boolean"],
            "交集": ["boolean"],
            
            # 模拟相关
            "刚体": ["rbdmaterialfracture"],
            "破碎": ["voronoifracture"],
            "流体": ["flip", "pyro"],
            "布料": ["vellum"],
            "毛发": ["hairgen"],
        }
        
        desc_lower = description.lower()
        results = []
        scores = {}
        
        # 匹配语义映射
        for keywords, nodes in semantic_map.items():
            if any(k in desc_lower for k in keywords.split()):
                for node in nodes:
                    if node not in scores:
                        scores[node] = 0
                    scores[node] += 1
        
        # 获取匹配的节点详情
        cat_filter = category.lower() if category != "all" else None
        
        for node_name in sorted(scores.keys(), key=lambda x: -scores[x])[:10]:
            for cat_name, cat in hou.nodeTypeCategories().items():
                if cat_filter and cat_name.lower() != cat_filter:
                    continue
                for type_name, node_type in cat.nodeTypes().items():
                    if node_name in type_name.lower():
                        desc = node_type.description()
                        results.append(f"- `{cat_name.lower()}/{type_name}` — {desc}")
                        break
        
        # 如果语义匹配没找到，尝试直接关键词搜索
        if not results:
            for cat_name, cat in hou.nodeTypeCategories().items():
                if cat_filter and cat_name.lower() != cat_filter:
                    continue
                for type_name, node_type in cat.nodeTypes().items():
                    desc = node_type.description().lower()
                    if any(w in desc or w in type_name.lower() for w in desc_lower.split()):
                        results.append(f"- `{cat_name.lower()}/{type_name}` — {node_type.description()}")
                        if len(results) >= 10:
                            break
                if len(results) >= 10:
                    break
        
        if results:
            result_text = f"根据 '{description}' 找到以下节点:\n" + "\n".join(results[:10])
            return True, result_text
        
        return False, f"未找到匹配 '{description}' 的节点"

    def list_children(self, network_path: Optional[str] = None, 
                      recursive: bool = False, 
                      show_flags: bool = True) -> Tuple[bool, str]:
        """列出子节点"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        if network_path:
            network = hou.node(network_path)
            if not network:
                return False, f"未找到网络: {network_path}"
        else:
            network = self._current_network()
            if not network:
                return False, "未找到当前网络"
        
        def format_node(node, indent=0):
            prefix = "  " * indent
            flags = ""
            if show_flags:
                parts = []
                if hasattr(node, 'isDisplayFlagSet') and node.isDisplayFlagSet():
                    parts.append("[disp]")
                if hasattr(node, 'isRenderFlagSet') and node.isRenderFlagSet():
                    parts.append("🎬")
                if hasattr(node, 'isBypassed') and node.isBypassed():
                    parts.append("⏸")
                if parts:
                    flags = f" [{' '.join(parts)}]"
            
            node_type = node.type().name() if node.type() else "unknown"
            return f"{prefix}- {node.name()} ({node_type}){flags}"
        
        lines = [f"## {network.path()}"]
        
        def list_nodes(parent, indent=0):
            for child in parent.children():
                lines.append(format_node(child, indent))
                if recursive and hasattr(child, 'children') and child.children():
                    list_nodes(child, indent + 1)
        
        list_nodes(network)
        
        if len(lines) == 1:
            lines.append("（空网络）")
        
        return True, "\n".join(lines)

    def get_geometry_info(self, node_path: str, output_index: int = 0) -> Tuple[bool, str]:
        """获取几何体信息"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        node = hou.node(node_path)
        if not node:
            return False, f"未找到节点: {node_path}"
        
        try:
            geo = node.geometry()
            if not geo:
                return False, f"节点 {node_path} 没有几何体输出"
            
            info = {
                "点数": geo.intrinsicValue("pointcount"),
                "顶点数": geo.intrinsicValue("vertexcount"),
                "图元数": geo.intrinsicValue("primitivecount"),
            }
            
            # 点属性
            point_attrs = [f"{a.name()} ({a.dataType().name()})" for a in geo.pointAttribs()]
            # 顶点属性
            vertex_attrs = [f"{a.name()} ({a.dataType().name()})" for a in geo.vertexAttribs()]
            # 图元属性
            prim_attrs = [f"{a.name()} ({a.dataType().name()})" for a in geo.primAttribs()]
            # 全局属性
            detail_attrs = [f"{a.name()} ({a.dataType().name()})" for a in geo.globalAttribs()]
            
            lines = [
                f"## 几何体信息: {node_path}",
                f"- 点数: {info['点数']}",
                f"- 顶点数: {info['顶点数']}",
                f"- 图元数: {info['图元数']}",
                "",
                "### 属性",
            ]
            
            if point_attrs:
                lines.append(f"点属性: {', '.join(point_attrs)}")
            if vertex_attrs:
                lines.append(f"顶点属性: {', '.join(vertex_attrs)}")
            if prim_attrs:
                lines.append(f"图元属性: {', '.join(prim_attrs)}")
            if detail_attrs:
                lines.append(f"全局属性: {', '.join(detail_attrs)}")
            
            if not any([point_attrs, vertex_attrs, prim_attrs, detail_attrs]):
                lines.append("（无自定义属性）")
            
            return True, "\n".join(lines)
        except Exception as e:
            return False, f"获取几何体信息失败: {str(e)}"

    def _resolve_geometry_node(self, node_path: str) -> Tuple[Optional[Any], Optional[str]]:
        node = hou.node(node_path) if hou else None
        if node is None:
            return None, f"未找到节点: {node_path}"

        try:
            node.geometry()
            return node, None
        except Exception:
            pass

        try:
            display_node = node.displayNode() if hasattr(node, "displayNode") else None
            if display_node is not None:
                return display_node, None
        except Exception:
            pass

        return node, None

    def _attribute_summary(self, attributes: Any) -> List[Dict[str, Any]]:
        entries = []
        for attrib in attributes:
            try:
                data_type = attrib.dataType()
                entries.append({
                    "name": attrib.name(),
                    "type": data_type.name() if hasattr(data_type, "name") else str(data_type),
                    "size": attrib.size(),
                })
            except Exception:
                continue
        return entries

    def _element_attrib_value(self, element: Any, attrib: Any) -> Any:
        try:
            return self._jsonable_value(element.attribValue(attrib))
        except Exception:
            return None

    def get_geometry_summary(self, node_path: str, max_sample_points: int = 50,
                             include_attributes: bool = True,
                             include_groups: bool = True,
                             sample_attributes: Optional[List[str]] = None,
                             sample_primitives: bool = False) -> Tuple[bool, Dict[str, Any]]:
        """Return structured geometry facts and bounded samples for a SOP node."""
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        if not node_path:
            return False, {"error": "缺少 node_path 参数"}

        node, error = self._resolve_geometry_node(node_path)
        if error:
            return False, {"error": error}

        assert node is not None
        max_sample_points = max(0, min(int(max_sample_points), 500))
        sample_attributes = [str(name) for name in (sample_attributes or []) if str(name).strip()]

        try:
            cook_state = "unknown"
            try:
                if hasattr(node, "needsToCook") and node.needsToCook():
                    cook_state = "dirty"
                    node.cook(force=True)
                cook_state = "cooked"
            except Exception:
                cook_state = "error"

            try:
                geo = node.geometry()
            except Exception as exc:
                return False, {"error": f"节点 {node.path()} 没有可读取几何体: {exc}"}
            if geo is None:
                return False, {"error": f"节点 {node.path()} 没有几何体输出"}

            update_mode = "unknown"
            manual_mode = False
            try:
                mode = hou.updateModeSetting()
                update_mode = mode.name() if hasattr(mode, "name") else str(mode)
                manual_mode = (mode == hou.updateMode.Manual)
            except Exception:
                pass

            point_count = geo.intrinsicValue("pointcount")
            primitive_count = geo.intrinsicValue("primitivecount")
            vertex_count = geo.intrinsicValue("vertexcount")
            is_empty_geometry = (int(point_count) == 0 and int(primitive_count) == 0)
            recommended_next_action = "inspect_wiring_or_parameters"
            validation_confidence = "high"
            if manual_mode and is_empty_geometry:
                recommended_next_action = "temporary_auto_validate"
                validation_confidence = "needs_refresh_validation"

            result: Dict[str, Any] = {
                "node_path": node.path(),
                "requested_path": node_path,
                "node_type": node.type().name() if node.type() else "unknown",
                "cook_state": cook_state,
                "update_mode": update_mode,
                "manual_mode": manual_mode,
                "is_empty_geometry": is_empty_geometry,
                "validation_confidence": validation_confidence,
                "recommended_next_action": recommended_next_action,
                "point_count": point_count,
                "primitive_count": primitive_count,
                "vertex_count": vertex_count,
                "sample_limit": max_sample_points,
            }

            try:
                bbox = geo.boundingBox()
                result["bounding_box"] = {
                    "min": self._jsonable_value(bbox.minvec()),
                    "max": self._jsonable_value(bbox.maxvec()),
                    "size": self._jsonable_value(bbox.sizevec()),
                    "center": self._jsonable_value(bbox.center()),
                }
            except Exception:
                result["bounding_box"] = None

            if include_attributes:
                result["attributes"] = {
                    "point": self._attribute_summary(geo.pointAttribs()),
                    "primitive": self._attribute_summary(geo.primAttribs()),
                    "vertex": self._attribute_summary(geo.vertexAttribs()),
                    "detail": self._attribute_summary(geo.globalAttribs()),
                }

            if include_groups:
                try:
                    point_groups = [group.name() for group in geo.pointGroups()]
                except Exception:
                    point_groups = []
                try:
                    prim_groups = [group.name() for group in geo.primGroups()]
                except Exception:
                    prim_groups = []
                result["groups"] = {"point": point_groups, "primitive": prim_groups}

            if max_sample_points > 0:
                point_attribs = {attrib.name(): attrib for attrib in geo.pointAttribs()}
                selected_names = sample_attributes or (["P"] if "P" in point_attribs else [])
                missing = [name for name in selected_names if name not in point_attribs]
                selected = [point_attribs[name] for name in selected_names if name in point_attribs]
                sample_points = []
                for point in itertools.islice(geo.iterPoints(), max_sample_points):
                    row = {"number": point.number()}
                    for attrib in selected:
                        row[attrib.name()] = self._element_attrib_value(point, attrib)
                    sample_points.append(row)
                result["sample_points"] = sample_points
                if missing:
                    result["missing_sample_attributes"] = missing

                if sample_primitives:
                    prim_attribs = {attrib.name(): attrib for attrib in geo.primAttribs()}
                    prim_selected = [prim_attribs[name] for name in sample_attributes if name in prim_attribs]
                    sample_prims = []
                    for prim in itertools.islice(geo.iterPrims(), max_sample_points):
                        row = {"number": prim.number(), "type": prim.type().name()}
                        for attrib in prim_selected:
                            row[attrib.name()] = self._element_attrib_value(prim, attrib)
                        sample_prims.append(row)
                    result["sample_primitives"] = sample_prims

            return True, result
        except Exception as exc:
            return False, {"error": f"获取几何摘要失败: {exc}"}

    def get_scene_snapshot(self, root_path: str = "/obj", include_params: bool = False,
                           max_depth: int = 6, max_nodes: int = 300) -> Tuple[bool, Dict[str, Any]]:
        """Serialize a bounded, read-only scene tree for planning and comparison."""
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}

        root = hou.node(root_path or "/obj")
        if root is None:
            return False, {"error": f"未找到根节点: {root_path}"}

        max_depth = max(0, min(int(max_depth), 12))
        max_nodes = max(1, min(int(max_nodes), 1000))
        visited = 0
        truncated = False

        def snapshot_node(node: Any, depth: int = 0) -> Dict[str, Any]:
            nonlocal visited, truncated
            visited += 1
            node_type = node.type()
            errors = []
            warnings = []
            try:
                errors = [str(item) for item in node.errors()]
            except Exception:
                pass
            try:
                warnings = [str(item) for item in node.warnings()]
            except Exception:
                pass

            item: Dict[str, Any] = {
                "name": node.name(),
                "path": node.path(),
                "type": node_type.name() if node_type else "unknown",
                "category": node_type.category().name() if node_type else "unknown",
                "child_count": len(node.children()) if hasattr(node, "children") else 0,
                "input_count": len([inp for inp in node.inputs() if inp is not None]) if hasattr(node, "inputs") else 0,
                "output_count": len(node.outputs()) if hasattr(node, "outputs") else 0,
                "has_errors": bool(errors),
                "has_warnings": bool(warnings),
            }

            if errors:
                item["errors"] = errors[:5]
            if warnings:
                item["warnings"] = warnings[:5]

            flags = []
            for attr, label in (("isDisplayFlagSet", "display"), ("isRenderFlagSet", "render"),
                                ("isBypassed", "bypass"), ("isTemplateFlagSet", "template")):
                try:
                    if hasattr(node, attr) and getattr(node, attr)():
                        flags.append(label)
                except Exception:
                    pass
            if flags:
                item["flags"] = flags

            if include_params:
                params = {}
                for parm_tuple in list(node.parmTuples())[:80]:
                    try:
                        params[parm_tuple.name()] = self._parm_tuple_value(parm_tuple)
                    except Exception:
                        continue
                item["parameters"] = params

            if depth >= max_depth:
                if item["child_count"]:
                    item["children_truncated"] = True
                return item

            children = []
            try:
                for child in node.children():
                    if visited >= max_nodes:
                        truncated = True
                        break
                    children.append(snapshot_node(child, depth + 1))
            except Exception:
                pass
            if children:
                item["children"] = children
            return item

        try:
            root_snapshot = snapshot_node(root)
            return True, {
                "root_path": root.path(),
                "include_params": include_params,
                "max_depth": max_depth,
                "max_nodes": max_nodes,
                "node_count": visited,
                "truncated": truncated,
                "scene": root_snapshot,
            }
        except Exception as exc:
            return False, {"error": f"获取场景快照失败: {exc}"}

    def set_display_flag(self, node_path: str, display: bool = True, 
                         render: bool = True) -> Tuple[bool, str]:
        """设置显示/渲染标志"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        node = hou.node(node_path)
        if not node:
            return False, f"未找到节点: {node_path}"
        
        try:
            if display and hasattr(node, 'setDisplayFlag'):
                node.setDisplayFlag(True)
            if render and hasattr(node, 'setRenderFlag'):
                node.setRenderFlag(True)
            
            flags = []
            if display:
                flags.append("显示")
            if render:
                flags.append("渲染")
            
            return True, f"已设置 {node.name()} 为{'/'.join(flags)}节点"
        except Exception as e:
            return False, f"设置标志失败: {str(e)}"

    def copy_node(self, source_path: str, dest_network: Optional[str] = None,
                  new_name: Optional[str] = None) -> Tuple[bool, str]:
        """复制节点"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        source = hou.node(source_path)
        if not source:
            return False, f"未找到源节点: {source_path}"
        
        if dest_network:
            dest = hou.node(dest_network)
            if not dest:
                return False, f"未找到目标网络: {dest_network}"
        else:
            dest = source.parent()
        
        try:
            new_node = hou.copyNodesTo([source], dest)[0]
            if new_name:
                new_node.setName(new_name)
            new_node.moveToGoodPosition()
            return True, f"已复制节点到: {new_node.path()}"
        except Exception as e:
            return False, f"复制失败: {str(e)}"

    def batch_set_parameters(self, node_paths: List[str], param_name: str,
                             value: Any) -> Tuple[bool, Dict[str, Any]]:
        """批量设置参数 (partial-success)。

        语义: 永远尝试设置每个节点；返回结构 {set, failed} 完整列出每条结果。
        success=True 表示"调用流程正常完成"，即使部分节点失败。
        success=False 仅在环境不可用或所有节点都失败时返回。
        """
        if hou is None:
            return False, {"error": "未检测到 Houdini API", "set": [], "failed": []}

        set_results: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        for path in node_paths:
            node = hou.node(path)
            if not node:
                failed.append({"path": path, "error": "节点未找到"})
                continue

            parm = node.parm(param_name)
            if parm is None:
                parm_tuple = node.parmTuple(param_name)
                if parm_tuple and isinstance(value, (list, tuple)):
                    try:
                        parm_tuple.set(tuple(value))
                        set_results.append({"path": node.path(), "value": list(value)})
                    except Exception as e:
                        failed.append({"path": node.path(), "error": str(e)})
                else:
                    # did-you-mean 风格提示
                    try:
                        candidates = [pt.name() for pt in node.parmTuples()]
                        close = difflib.get_close_matches(param_name, candidates, n=3, cutoff=0.5)
                        hint = f"（你是不是想用: {', '.join(close)}?）" if close else ""
                    except Exception:
                        hint = ""
                    failed.append({
                        "path": node.path(),
                        "error": f"节点 {node.type().name()} 无参数 '{param_name}'{hint}",
                    })
                continue

            try:
                parm.set(value)
                set_results.append({"path": node.path(), "value": value})
            except Exception as e:
                failed.append({"path": node.path(), "error": str(e)})

        # 全部失败才算调用整体失败，方便上层区分"完全没成功"与"部分成功"
        overall_ok = bool(set_results) or not node_paths
        return overall_ok, {
            "param_name": param_name,
            "set": set_results,
            "failed": failed,
            "summary": f"成功 {len(set_results)} / 失败 {len(failed)} / 共 {len(node_paths)}",
        }

    def find_nodes_by_param(self, param_name: str, value: Any = None,
                            network_path: Optional[str] = None,
                            recursive: bool = True) -> Tuple[bool, str]:
        """按参数值搜索节点"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        if network_path:
            network = hou.node(network_path)
            if not network:
                return False, f"未找到网络: {network_path}"
        else:
            network = self._current_network() or hou.node('/obj')
        
        results = []
        
        def search_in(parent):
            for node in parent.children():
                parm = node.parm(param_name)
                if parm:
                    parm_value = parm.eval()
                    if value is None or str(parm_value) == str(value):
                        results.append(f"- {node.path()}: {param_name}={parm_value}")
                if recursive and hasattr(node, 'children'):
                    search_in(node)
        
        search_in(network)
        
        if results:
            header = f"找到 {len(results)} 个节点包含参数 '{param_name}'"
            if value is not None:
                header += f" = {value}"
            return True, header + ":\n" + "\n".join(results[:50])
        
        return False, f"未找到包含参数 '{param_name}' 的节点"

    def _jsonable_value(self, value: Any) -> Any:
        """Convert Houdini/Python values to JSON-friendly primitives."""
        try:
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            if isinstance(value, (list, tuple)):
                return [self._jsonable_value(v) for v in value]
            if isinstance(value, dict):
                return {str(k): self._jsonable_value(v) for k, v in value.items()}
            if hou and hasattr(value, "path"):
                return value.path()
            if hou and hasattr(value, "name"):
                return value.name()
            return str(value)
        except Exception:
            return str(value)

    def _parm_tuple_value(self, parm_tuple: Any) -> Any:
        try:
            value = parm_tuple.eval()
        except Exception:
            try:
                value = [parm.eval() for parm in parm_tuple]
            except Exception:
                return None
        value = self._jsonable_value(value)
        if isinstance(value, list) and len(value) == 1:
            return value[0]
        return value

    def _parm_template_info(self, node: Any, parm_tuple: Any) -> Dict[str, Any]:
        template = parm_tuple.parmTemplate()
        entry: Dict[str, Any] = {
            "name": parm_tuple.name(),
            "label": template.label() if hasattr(template, "label") else parm_tuple.name(),
            "type": template.type().name() if hasattr(template, "type") else "Unknown",
            "tuple_size": len(parm_tuple),
            "current_value": self._parm_tuple_value(parm_tuple),
        }

        try:
            default = self._jsonable_value(template.defaultValue())
            if isinstance(default, list) and len(default) == 1:
                default = default[0]
            entry["default"] = default
        except Exception:
            pass

        for method_name, key in (("minValue", "min"), ("maxValue", "max")):
            try:
                entry[key] = self._jsonable_value(getattr(template, method_name)())
            except Exception:
                pass

        try:
            menu_items = list(template.menuItems())
            if menu_items:
                labels = list(template.menuLabels()) if hasattr(template, "menuLabels") else menu_items
                entry["menu_items"] = [
                    {"token": str(token), "label": str(label)}
                    for token, label in zip(menu_items[:40], labels[:40])
                ]
                if len(menu_items) > 40:
                    entry["menu_truncated"] = len(menu_items)
        except Exception:
            pass

        try:
            entry["is_hidden"] = bool(template.isHidden())
        except Exception:
            entry["is_hidden"] = False

        try:
            first_parm = node.parm(parm_tuple.name())
            if first_parm is not None and hasattr(first_parm, "isTimeDependent"):
                entry["is_time_dependent"] = bool(first_parm.isTimeDependent())
        except Exception:
            pass

        return entry

    def get_node_card(self, node_type: str, context: str = "Sop",
                      parm_filter: Optional[str] = None,
                      max_parms: int = 40) -> Tuple[bool, Dict[str, Any]]:
        """节点类型说明卡（无需先建节点）：min/max inputs、连接器 label、参数名+默认值+menu items、是否 generator。

        AI 用陌生节点类型前必查；比 get_parameter_schema 更早 —— 那个需要先建节点。
        """
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}

        try:
            categories = hou.nodeTypeCategories()
        except Exception as exc:
            return False, {"error": f"读取 nodeTypeCategories 失败: {exc}"}

        # context 容错：sop/Sop/SOP 都接受
        category = None
        ctx_norm = (context or "Sop").strip()
        for key in (ctx_norm, ctx_norm.capitalize(), ctx_norm.upper(), ctx_norm.lower()):
            if key in categories:
                category = categories[key]
                break
        if category is None:
            return False, {
                "error": f"未知 context '{context}'。可用: {sorted(categories.keys())}"
            }

        try:
            node_types = category.nodeTypes()
        except Exception as exc:
            return False, {"error": f"读取节点类型失败: {exc}"}

        # 类型解析：精确 → 去版本号匹配 → did-you-mean
        resolved = None
        if node_type in node_types:
            resolved = node_types[node_type]
        else:
            for nt_name, nt_obj in node_types.items():
                if nt_name.split("::", 1)[0] == node_type:
                    resolved = nt_obj
                    break
        if resolved is None:
            from difflib import get_close_matches
            close = get_close_matches(node_type, list(node_types.keys()), n=5, cutoff=0.4)
            return False, {
                "error": f"节点类型 '{node_type}' 在 {category.name()} 中不存在"
                         + (f"。建议: {', '.join(close)}" if close else ""),
                "did_you_mean": close,
            }

        # 连接器 label（实例化一个临时节点读 inputLabels —— Houdini 没有 type-level API）
        # ⚠️ 探针有副作用风险（OnCreated 回调、UI 刷新、潜在死锁），只对 Sop category 做；
        #    其他 category（Object/Lop/Dop 等）直接返回空 label，AI 可改用 get_node_inputs 查端口。
        input_labels: List[str] = []
        output_labels: List[str] = []
        try:
            cat_name = category.name()
            if cat_name == "Sop":
                # 选个临时 parent：obj 下已有的 geo 容器，没有就新建一个空 geo
                temp_parent = None
                for child in hou.node("/obj").children():
                    if child.childTypeCategory() == category:
                        temp_parent = child
                        break
                _probe_container_created = False
                if temp_parent is None:
                    temp_parent = hou.node("/obj").createNode(
                        "geo", "__nodecard_probe__",
                        run_init_scripts=False, load_contents=False, exact_type_name=True)
                    _probe_container_created = True
                if temp_parent is not None:
                    probe = temp_parent.createNode(
                        resolved.name(), "__probe__",
                        run_init_scripts=False, load_contents=False, exact_type_name=True)
                    try:
                        input_labels = [str(l) for l in probe.inputLabels()] if hasattr(probe, "inputLabels") else []
                    except Exception:
                        pass
                    try:
                        output_labels = [str(l) for l in probe.outputLabels()] if hasattr(probe, "outputLabels") else []
                    except Exception:
                        pass
                    try:
                        probe.destroy()
                    except Exception:
                        pass
                    if _probe_container_created:
                        try:
                            temp_parent.destroy()
                        except Exception:
                            pass
        except Exception:
            # 探针失败不影响其余字段
            pass

        # 参数 schema（从 parmTemplateGroup 读，无需实例化）
        parms_out: List[Dict[str, Any]] = []
        try:
            tpl_group = resolved.parmTemplateGroup()
            filter_lc = parm_filter.lower() if parm_filter else None
            for tpl in tpl_group.parmTemplates():
                try:
                    name = tpl.name()
                    label = tpl.label() if hasattr(tpl, "label") else name
                    if filter_lc and filter_lc not in name.lower() and filter_lc not in label.lower():
                        continue
                    if hasattr(tpl, "isHidden") and tpl.isHidden():
                        continue
                    entry: Dict[str, Any] = {
                        "name": name,
                        "label": label,
                        "type": tpl.type().name() if hasattr(tpl, "type") else "Unknown",
                    }
                    try:
                        dv = tpl.defaultValue()
                        if isinstance(dv, tuple):
                            entry["default"] = list(dv)
                        else:
                            entry["default"] = dv
                    except Exception:
                        pass
                    # menu items 是 enum 参数的合法值
                    try:
                        items = tpl.menuItems() if hasattr(tpl, "menuItems") else None
                        if items:
                            entry["menu"] = list(items)[:15]
                    except Exception:
                        pass
                    parms_out.append(entry)
                    if len(parms_out) >= max_parms:
                        break
                except Exception:
                    continue
        except Exception as exc:
            return False, {"error": f"读取 parmTemplateGroup 失败: {exc}"}

        min_in = resolved.minNumInputs() if hasattr(resolved, "minNumInputs") else 0
        max_in = resolved.maxNumInputs() if hasattr(resolved, "maxNumInputs") else 0
        max_out = resolved.maxNumOutputs() if hasattr(resolved, "maxNumOutputs") else 0

        return True, {
            "type": resolved.name(),
            "label": resolved.description() if hasattr(resolved, "description") else resolved.name(),
            "context": category.name(),
            "min_inputs": min_in,
            "max_inputs": max_in,
            "max_outputs": max_out,
            "is_generator": min_in == 0,
            "input_labels": input_labels,
            "output_labels": output_labels,
            "parm_count": len(parms_out),
            "parms": parms_out,
        }

    def get_parameter_schema(self, node_path: str, pattern: Optional[str] = None,
                             offset: int = 0, limit: int = 80,
                             include_hidden: bool = False) -> Tuple[bool, Dict[str, Any]]:
        """Return structured parameter metadata for safe parameter editing."""
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}

        node = hou.node(node_path)
        if node is None:
            return False, {"error": f"未找到节点: {node_path}"}

        offset = max(0, offset)
        limit = max(1, min(limit, 200))
        pattern_lc = pattern.lower() if pattern else None

        try:
            parm_tuples = []
            for parm_tuple in node.parmTuples():
                try:
                    template = parm_tuple.parmTemplate()
                    hidden = bool(template.isHidden()) if hasattr(template, "isHidden") else False
                    if hidden and not include_hidden:
                        continue
                    name = parm_tuple.name()
                    label = template.label() if hasattr(template, "label") else name
                    if pattern_lc:
                        name_lc = name.lower()
                        label_lc = label.lower()
                        if not (fnmatch.fnmatch(name_lc, pattern_lc) or fnmatch.fnmatch(label_lc, pattern_lc)):
                            continue
                    parm_tuples.append(parm_tuple)
                except Exception:
                    continue

            sliced = parm_tuples[offset:offset + limit]
            node_type = node.type()
            parameters = [self._parm_template_info(node, parm_tuple) for parm_tuple in sliced]
            next_offset = offset + len(parameters) if offset + len(parameters) < len(parm_tuples) else None
            return True, {
                "node_path": node.path(),
                "node_type": node_type.name() if node_type else "unknown",
                "node_category": node_type.category().name() if node_type else "unknown",
                "pattern": pattern,
                "include_hidden": include_hidden,
                "total": len(parm_tuples),
                "offset": offset,
                "limit": limit,
                "count": len(parameters),
                "has_more": next_offset is not None,
                "next_offset": next_offset,
                "parameters": parameters,
            }
        except Exception as e:
            return False, {"error": f"获取参数 schema 失败: {str(e)}"}

    def find_nodes(self, root_path: str = "/obj", name_pattern: str = "*",
                   node_type: Optional[str] = None, category: Optional[str] = None,
                   recursive: bool = True, max_results: int = 100,
                   offset: int = 0) -> Tuple[bool, Dict[str, Any]]:
        """Find nodes by name glob, type, and category without mutating the scene."""
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}

        root = hou.node(root_path or "/obj")
        if root is None:
            return False, {"error": f"未找到根节点: {root_path}"}

        offset = max(0, offset)
        max_results = max(1, min(max_results, 500))
        name_pattern = name_pattern or "*"
        name_pattern_lc = name_pattern.lower()
        type_filter = node_type.lower() if node_type else None
        category_filter = category.lower() if category else None

        def type_matches(node: Any) -> bool:
            if not type_filter:
                return True
            try:
                node_type_obj = node.type()
                type_name = node_type_obj.name().lower()
                type_key = f"{node_type_obj.category().name().lower()}/{type_name}"
                if any(ch in type_filter for ch in "*?["):
                    return fnmatch.fnmatch(type_name, type_filter) or fnmatch.fnmatch(type_key, type_filter)
                return type_filter in (type_name, type_key) or type_filter in type_name
            except Exception:
                return False

        def category_matches(node: Any) -> bool:
            if not category_filter:
                return True
            try:
                return node.type().category().name().lower() == category_filter
            except Exception:
                return False

        def node_summary(node: Any) -> Dict[str, Any]:
            node_type_obj = node.type()
            flags = []
            for attr, label in (("isDisplayFlagSet", "display"), ("isRenderFlagSet", "render"),
                                ("isBypassed", "bypass"), ("isLocked", "locked")):
                try:
                    if hasattr(node, attr) and getattr(node, attr)():
                        flags.append(label)
                except Exception:
                    pass
            errors = []
            warnings = []
            try:
                errors = list(node.errors())
            except Exception:
                pass
            try:
                warnings = list(node.warnings())
            except Exception:
                pass
            return {
                "name": node.name(),
                "path": node.path(),
                "type": node_type_obj.name() if node_type_obj else "unknown",
                "category": node_type_obj.category().name() if node_type_obj else "unknown",
                "flags": flags,
                "input_count": len([inp for inp in node.inputs() if inp is not None]) if hasattr(node, "inputs") else 0,
                "output_count": len(node.outputs()) if hasattr(node, "outputs") else 0,
                "child_count": len(node.children()) if hasattr(node, "children") else 0,
                "has_errors": bool(errors),
                "has_warnings": bool(warnings),
            }

        try:
            candidates = list(root.allSubChildren()) if recursive else list(root.children())
            matches = [
                node for node in candidates
                if fnmatch.fnmatch(node.name().lower(), name_pattern_lc)
                and type_matches(node)
                and category_matches(node)
            ]
            page_nodes = matches[offset:offset + max_results]
            nodes = [node_summary(node) for node in page_nodes]
            next_offset = offset + len(nodes) if offset + len(nodes) < len(matches) else None
            return True, {
                "root_path": root.path(),
                "name_pattern": name_pattern,
                "node_type": node_type,
                "category": category,
                "recursive": recursive,
                "total_matches": len(matches),
                "offset": offset,
                "max_results": max_results,
                "count": len(nodes),
                "has_more": next_offset is not None,
                "next_offset": next_offset,
                "nodes": nodes,
            }
        except Exception as e:
            return False, {"error": f"查找节点失败: {str(e)}"}

    def save_hip(self, file_path: Optional[str] = None) -> Tuple[bool, str]:
        """保存 HIP 文件"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        try:
            if file_path:
                hou.hipFile.save(file_path)
                return True, f"已保存到: {file_path}"
            else:
                hou.hipFile.save()
                return True, f"已保存: {hou.hipFile.path()}"
        except Exception as e:
            return False, f"保存失败: {str(e)}"

    def undo_redo(self, action: str) -> Tuple[bool, str]:
        """撤销/重做"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        try:
            if action == "undo":
                hou.undos.performUndo()
                return True, "已撤销"
            elif action == "redo":
                hou.undos.performRedo()
                return True, "已重做"
            else:
                return False, f"未知操作: {action}"
        except Exception as e:
            return False, f"操作失败: {str(e)}"

    def search_documentation(self, node_type: str, category: str = "sop") -> Tuple[bool, str]:
        """查询节点文档"""
        if requests is None:
            return False, "requests 模块未安装"
        
        base_url = "https://www.sidefx.com/docs/houdini/nodes"
        doc_node_type = node_type.replace("::", "--")
        doc_url = f"{base_url}/{category}/{doc_node_type}.html"
        
        settings = read_settings()
        tries = max(1, settings.request_retries + 1)
        
        for _ in range(tries):
            try:
                response = requests.get(doc_url, timeout=settings.request_timeout)
                if response.status_code == 404:
                    return False, f"未找到文档: {category}/{node_type}"
                response.raise_for_status()
                
                content = response.text
                title_match = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE)
                title = title_match.group(1) if title_match else f"{node_type} node"
                
                summary = ""
                summary_match = re.search(r'<div[^>]*class="[^"]*summary[^"]*"[^>]*>(.*?)</div>', content, re.DOTALL | re.IGNORECASE)
                if summary_match:
                    summary = re.sub(r'<[^>]+>', '', summary_match.group(1)).strip()
                
                result = f"## {title}\n\n**文档链接**: {doc_url}\n\n"
                if summary:
                    result += f"**描述**: {summary}\n"
                
                return True, result
            except Exception as e:
                time.sleep(settings.request_backoff)
        
        return False, f"查询失败: {doc_url}"

    # ========================================
    # Wrangle 节点创建（VEX 优先）
    # ========================================
    
    def create_wrangle_node(self, vex_code: str, 
                            wrangle_type: str = "attribwrangle",
                            node_name: Optional[str] = None,
                            run_over: str = "Points",
                            parent_path: Optional[str] = None) -> Tuple[bool, str]:
        """创建 Wrangle 节点并设置 VEX 代码
        
        这是解决几何处理问题的首选方式。
        
        Args:
            vex_code: VEX 代码
            wrangle_type: Wrangle 类型，默认 attribwrangle
            node_name: 节点名称（可选）
            run_over: 运行模式 (Points/Vertices/Primitives/Detail)
            parent_path: 父网络路径（可选）
        
        Returns:
            (success, message)
        """
        if hou is None:
            return False, "未检测到 Houdini API"
        
        if not vex_code or not vex_code.strip():
            return False, "VEX 代码为空"
        
        # 获取父网络
        if parent_path:
            network = hou.node(parent_path)
            if network is None:
                return False, f"未找到父网络: {parent_path}"
        else:
            network = self._current_network()
            if network is None:
                return False, "未找到当前网络"
        
        # 按父网络类别推断合适的 wrangle 类型（全自动）
        try:
            cat_name = network.childTypeCategory().name().lower()
        except Exception:
            cat_name = "sop"

        # 每个类别的合法 wrangle 类型 + 默认值（列表首项为默认）
        _wrangle_by_cat = {
            "sop":  ["attribwrangle", "pointwrangle", "primitivewrangle",
                     "volumewrangle", "vertexwrangle"],
            "dop":  ["popwrangle", "gaswrangle", "volumewrangle"],
            "chop": ["channelwrangle"],
            "lop":  ["attribwrangle"],
        }
        # childTypeCategory().name() 形如 Sop/Dop/Chop/Lop；其余类别（Object 等）回退 sop 处理
        _cat_key = next((k for k in _wrangle_by_cat if cat_name.startswith(k)), "sop")
        _valid = _wrangle_by_cat[_cat_key]

        # 用户显式传入且在当前类别合法 → 尊重用户；否则用该类别默认值
        if wrangle_type not in _valid:
            wrangle_type = _valid[0]

        # 仅 SOP 需要确保/自动创建 geo 容器；DOP/CHOP/LOP 网络本身已是正确类别
        if _cat_key == "sop":
            network = self._ensure_target_network(network, self._category_from_hint("sop"))
        
        # 创建节点
        safe_name = self._sanitize_node_name(node_name)
        
        try:
            # run_init_scripts=False 防止 OnCreated 递归调用崩溃
            # 不使用 force_valid_node_name（旧版 Houdini <19.5 不支持）
            new_node = network.createNode(
                wrangle_type,
                safe_name,
                run_init_scripts=False,
                load_contents=True,
                exact_type_name=True,  # wrangle 类型名固定，精确匹配避免误匹配
            )
        except Exception as exc:
            return False, f"创建 Wrangle 节点失败: {exc}"
        
        # 设置 VEX 代码
        try:
            # 大多数 Wrangle 节点的代码参数名是 "snippet"
            snippet_parm = new_node.parm("snippet")
            if snippet_parm:
                snippet_parm.set(vex_code)
            else:
                # 某些节点可能用 "code" 或 "vexcode"
                for parm_name in ["code", "vexcode", "vex_code"]:
                    parm = new_node.parm(parm_name)
                    if parm:
                        parm.set(vex_code)
                        break
        except Exception as exc:
            return False, f"设置 VEX 代码失败: {exc}"
        
        # 设置运行模式（与 Houdini Attrib Wrangle parm("class") 菜单一致：0=Detail, 1=Primitives, 2=Points, 3=Vertices, 4=Numbers）
        run_over_map = {
            "Detail": 0,
            "Primitives": 1,
            "Points": 2,
            "Vertices": 3,
            "Numbers": 4,
        }
        run_over_value = run_over_map.get(run_over, 2)  # 默认 Points
        
        try:
            class_parm = new_node.parm("class")
            if class_parm:
                class_parm.set(run_over_value)
        except Exception:
            pass  # 某些 wrangle 类型可能没有 class 参数
        
        # 布局和选择
        self._place_new_node(new_node, network)
        new_node.setSelected(True, clear_all_selected=True)
        
        try:
            new_node.setDisplayFlag(True)
            new_node.setRenderFlag(True)
        except Exception:
            pass
        
        try:
            editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor:
                editor.homeToSelection()
        except Exception:
            pass
        
        # 主动 cook + 收集编译诊断（不 cook 的话 errors() 经常拿到空 list 错过 VEX 编译错误）
        report = self._cook_and_report(new_node, force=True)
        if report["errors"]:
            return True, (f"已创建 Wrangle 节点: {new_node.path()}\n"
                          f"VEX 编译错误: {'; '.join(report['errors'])}")
        if report["warnings"]:
            return True, (f"已创建 Wrangle 节点: {new_node.path()}\n"
                          f"VEX 警告: {'; '.join(report['warnings'])}")

        return True, f"已创建 Wrangle 节点: {new_node.path()}"

    # ========================================
    # 节点创建
    # ========================================

    def _manual_mode_hint(self) -> str:
        """若 Houdini 当前处于 Manual 更新模式，返回一句提醒串，否则返回空串。

        Agent 运行期间会主动将 Houdini 切到 Manual 模式（防 cook 阻塞死锁），
        此时创建/修改节点不会自动 cook。将此提示附到工具返回消息，
        让模型知道 success 仅代表已排队，需 verify_network 确认真实结果。
        """
        if hou is None:
            return ""
        try:
            if hou.updateModeSetting() == hou.updateMode.Manual:
                return " ⚠Manual模式：数据未自动cook，success仅表示已排队，需verify_network确认"
        except Exception:
            pass
        return ""

    def create_node(self, type_hint: str, node_name: Optional[str] = None, 
                    parameters: Optional[Dict[str, Any]] = None,
                    parent_path: Optional[str] = None) -> Tuple[bool, str]:
        """创建单个节点"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        # 获取父网络
        if parent_path:
            network = hou.node(parent_path)
            if network is None:
                return False, f"未找到父网络: {parent_path}"
        else:
            network = self._current_network()
            if network is None:
                # 尝试使用默认网络
                try:
                    network = hou.node('/obj')
                    if network is None:
                        return False, "未找到当前网络，且无法访问默认网络 /obj。请确保Houdini已正确启动，或在网络编辑器中打开一个网络。"
                except Exception:
                    return False, "未找到当前网络，且无法访问默认网络。请确保Houdini已正确启动，或在网络编辑器中打开一个网络。"
        
        if not type_hint:
            return False, "未提供节点类型"
        
        # 根据文档，createNode 可以直接处理节点类型匹配，无需预先解析
        # 但我们需要确保网络类型正确
        desired_cat = self._desired_category_from_hint(type_hint, network)
        if desired_cat is None:
            # 如果无法识别类别，尝试根据节点类型推断（常见SOP节点）
            common_sop_nodes = ['box', 'sphere', 'grid', 'tube', 'line', 'circle', 'noise', 'mountain', 
                              'scatter', 'copytopoints', 'attribwrangle', 'pointwrangle', 'primitivewrangle',
                              'delete', 'blast', 'fuse', 'transform', 'subdivide', 'remesh']
            if type_hint.lower() in common_sop_nodes:
                # 这是一个SOP节点，需要SOP网络
                desired_cat = hou.sopNodeTypeCategory()
            else:
                # 如果无法识别类别，尝试使用当前网络的类别
                desired_cat = network.childTypeCategory() if network else None
                if desired_cat is None:
                    return False, f"无法识别节点类别: {type_hint}"
        
        # 确保目标网络类型正确（会自动创建容器）
        network = self._ensure_target_network(network, desired_cat)
        if network is None:
            return False, f"无法获取或创建目标网络: {type_hint}"
        
        # 清理节点名（但保留原始值用于错误提示）
        safe_name = self._sanitize_node_name(node_name)
        
        # 注意：
        # - run_init_scripts=False 防止 OnCreated 回调递归调用 createNode 导致崩溃
        # - 不传 force_valid_node_name，旧版 Houdini（<19.5）不支持该参数
        # - 已由 _sanitize_node_name 保证 safe_name 合法
        # - type_hint 剥离 sop/ 等前缀，防止模糊匹配时 C++ 层崩溃
        
        # 剥离类别前缀（如 "sop/box" → "box"）
        clean_type = type_hint.split("/", 1)[-1] if "/" in (type_hint or "") else type_hint
        
        try:
            new_node = network.createNode(
                clean_type,
                safe_name,
                run_init_scripts=False,
                load_contents=True,
                exact_type_name=False,
            )
        except hou.OperationFailed as exc:
            # 提供更详细的错误信息
            error_detail = str(exc)
            current_cat = network.childTypeCategory() if network else None
            cat_name = current_cat.name().lower() if current_cat else "unknown"
            network_path = network.path() if network else "unknown"
            
            # 尝试提供建议
            suggestions = []
            try:
                if current_cat:
                    node_types = list(current_cat.nodeTypes().keys())
                    hint_lower = type_hint.lower()
                    for nt in node_types:
                        if hint_lower in nt.lower() or nt.lower() in hint_lower:
                            suggestions.append(nt)
                            if len(suggestions) >= 5:
                                break
            except Exception:
                pass
            
            error_msg = f"创建节点失败: {type_hint}\n"
            error_msg += f"错误详情: {error_detail}\n"
            error_msg += f"当前网络: {network_path} (类别: {cat_name})"
            if suggestions:
                error_msg += f"\n建议的节点类型: {', '.join(suggestions[:5])}"
            return False, error_msg
        except Exception as exc:
            import traceback
            error_detail = str(exc)
            network_path = network.path() if network else "unknown" if network else "None"
            error_msg = f"创建节点失败: {type_hint}\n"
            error_msg += f"错误: {error_detail}\n"
            error_msg += f"网络: {network_path}"
            # 只在调试时输出完整traceback
            if "DEBUG" in os.environ:
                error_msg += f"\n{traceback.format_exc()}"
            return False, error_msg
        
        # 设置参数：任何失败 → 销毁节点回滚，返回硬错误（原子语义）
        if parameters and isinstance(parameters, dict):
            parm_errors = []
            for parm_name, parm_value in parameters.items():
                parm = new_node.parm(parm_name)
                if parm is None:
                    parm_tuple = new_node.parmTuple(parm_name)
                    if parm_tuple:
                        if isinstance(parm_value, (list, tuple)):
                            try:
                                parm_tuple.set(parm_value)
                            except Exception as exc:
                                parm_errors.append(f"{parm_name}: set 失败 - {exc}")
                        else:
                            parm_errors.append(
                                f"{parm_name}: 是 parm tuple，需传列表/元组（如 [x,y,z]），收到 {type(parm_value).__name__}")
                    else:
                        parm_errors.append(
                            f"{parm_name}: 未知参数名（用 get_parameter_schema 查节点 {new_node.type().name()} 的有效参数）")
                    continue
                try:
                    parm.set(parm_value)
                except Exception as exc:
                    parm_errors.append(f"{parm_name}: set 失败 - {exc}")
            if parm_errors:
                node_path_for_msg = new_node.path()
                try:
                    new_node.destroy()
                except Exception:
                    pass
                return False, (
                    f"创建节点 {node_path_for_msg} 后参数设置失败，已回滚销毁节点:\n  - "
                    + "\n  - ".join(parm_errors))
        
        self._place_new_node(new_node, network)
        new_node.setSelected(True, clear_all_selected=True)
        
        try:
            editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor:
                editor.homeToSelection()
        except Exception:
            pass
        
        # 返回节点路径 + diff 信息（让 AI 了解变化）
        node_path = new_node.path()
        diff_parts = [f"✓{node_path}"]
        try:
            parent = new_node.parent()
            if parent:
                siblings = len(parent.children())
                diff_parts.append(f"(父网络: {parent.path()}, 子节点数: {siblings})")
            # 输入连接信息
            inputs = new_node.inputs()
            if inputs:
                connected = [n.path() for n in inputs if n is not None]
                if connected:
                    diff_parts.append(f"输入: {', '.join(connected)}")
        except Exception:
            pass
        return True, ' '.join(diff_parts) + self._manual_mode_hint()

    def create_network(self, plan: Dict[str, Any]) -> Tuple[bool, str]:
        """批量创建节点网络

        plan 支持的字段：
            parent_path (str, optional) — 显式父网络路径；缺省走当前网络。
            nodes (list[dict], required) — 节点规范列表。
            connections (list[dict], optional) — 节点间连接。
            dry_run (bool, optional) — 只跑预校验、不创建任何节点，返回校验报告。
        """
        if hou is None:
            return False, "未检测到 Houdini API"

        parent_path = plan.get("parent_path") if isinstance(plan, dict) else None
        if parent_path:
            network = hou.node(parent_path)
            if network is None:
                return False, f"未找到父网络: {parent_path}"
        else:
            network = self._current_network()
            if network is None:
                return False, "未找到当前网络，请显式传入 parent_path"

        node_specs = plan.get("nodes") if isinstance(plan, dict) else None
        if not node_specs:
            return False, "缺少 nodes 字段"

        dry_run = bool(plan.get("dry_run")) if isinstance(plan, dict) else False

        # ========== Phase 1: 预校验（永远跑，dry_run 也跑） ==========
        # 校验项：type resolve + did-you-mean / spec 内 id 重复 / name 已存在子节点 /
        #         connections 端点指向 spec 内 id
        from difflib import get_close_matches
        validation_errors: List[str] = []

        # 若当前 network 是 obj 且 spec 中含 sop 节点 → Phase 2 会建 geo 容器
        # 这种情况下 name 冲突检查对原 network 没意义（容器里啥都没有），跳过
        _current_cat_name = ""
        try:
            _cur_cat = network.childTypeCategory()
            _current_cat_name = _cur_cat.name().lower() if _cur_cat else ""
        except Exception:
            pass
        _will_auto_container = _current_cat_name.startswith("object") and any(
            isinstance(s, dict) and str(s.get("type", "")).lower().startswith("sop/")
            for s in node_specs
        )
        existing_child_names = (
            set() if _will_auto_container else {child.name() for child in network.children()}
        )
        spec_ids_seen: List[str] = []
        spec_id_to_label: Dict[str, str] = {}  # 校验通过的 id -> 给 connections 用
        validated_types: List[str] = []

        for idx, spec in enumerate(node_specs):
            if not isinstance(spec, dict):
                validation_errors.append(f"节点 #{idx} 不是 dict: {spec!r}")
                continue
            node_id = spec.get("id") or spec.get("name") or f"node_{idx+1}"
            label = f"[{node_id}]"
            type_hint = spec.get("type") or spec.get("node_type")
            if not type_hint:
                validation_errors.append(f"{label} 缺少 type")
                continue

            # type resolve：剥离 sop/ 前缀，查 category 看节点类型是否存在
            clean_type = type_hint.split("/", 1)[-1] if "/" in type_hint else type_hint
            desired_cat = self._desired_category_from_hint(type_hint, network)
            if desired_cat is None:
                desired_cat = network.childTypeCategory() if network else None
            resolved = None
            if desired_cat is not None:
                try:
                    node_types = desired_cat.nodeTypes()
                    # 精确匹配
                    if clean_type in node_types:
                        resolved = clean_type
                    else:
                        # 带版本号的匹配（如 'filecache' → 'filecache::2.0'）
                        for nt_name in node_types:
                            base = nt_name.split("::", 1)[0]
                            if base == clean_type:
                                resolved = nt_name
                                break
                        if resolved is None:
                            close = get_close_matches(
                                clean_type, list(node_types.keys()), n=3, cutoff=0.5)
                            hint = f"，建议: {', '.join(close)}" if close else ""
                            validation_errors.append(
                                f"{label} 节点类型 '{type_hint}' 在 {desired_cat.name()} "
                                f"中不存在{hint}（用 search_node_types 查询）")
                            continue
                except Exception as exc:
                    validation_errors.append(f"{label} 解析类型失败: {exc}")
                    continue
            else:
                validation_errors.append(f"{label} 无法识别节点类别: {type_hint}")
                continue
            validated_types.append(f"{desired_cat.name()}/{resolved}")

            # id 重复检查
            if node_id in spec_ids_seen:
                validation_errors.append(f"{label} id 在 nodes 内重复")
            else:
                spec_ids_seen.append(node_id)
                spec_id_to_label[node_id] = label

            # 显式 name 与父网络下已有节点重名 → 报错
            wanted_name = spec.get("name")
            if wanted_name and wanted_name in existing_child_names:
                validation_errors.append(
                    f"{label} name='{wanted_name}' 与 {network.path()} 下已有节点冲突")

        # connections 端点必须指向 spec 内 id（校验通过的）
        connections_in = plan.get("connections") or []
        for cidx, conn in enumerate(connections_in):
            if not isinstance(conn, dict):
                validation_errors.append(f"connections[{cidx}] 不是 dict: {conn!r}")
                continue
            src_id = conn.get("from") or conn.get("src")
            dst_id = conn.get("to") or conn.get("dst")
            missing = []
            if not src_id or src_id not in spec_id_to_label:
                missing.append(f"from='{src_id}'")
            if not dst_id or dst_id not in spec_id_to_label:
                missing.append(f"to='{dst_id}'")
            if missing:
                available = ", ".join(spec_id_to_label.keys()) or "(无)"
                validation_errors.append(
                    f"connections[{cidx}] 端点不在 nodes 内: {', '.join(missing)}；"
                    f"可用 id: {available}")

        if validation_errors:
            return False, (
                f"预校验失败（共 {len(validation_errors)} 项），未创建任何节点:\n  - "
                + "\n  - ".join(validation_errors))

        if dry_run:
            return True, (
                f"dry_run 通过：{len(spec_ids_seen)} 个节点 / {len(connections_in)} 个连接\n"
                f"已校验类型: {', '.join(validated_types)}\n"
                f"父网络: {network.path()}")

        created: Dict[str, Any] = {}
        creation_order: List[str] = []
        messages: List[str] = []
        node_errors: List[str] = []  # 节点级硬失败，决定最终 success
        
        try:
            # 检测是否需要自动创建容器
            current_cat = network.childTypeCategory()
            current_cat_name = current_cat.name().lower() if current_cat else ""
            
            has_sop_node = any(
                isinstance(spec, dict) and 
                str(spec.get("type", "")).lower().startswith("sop/")
                for spec in node_specs
            )
            
            if has_sop_node and current_cat_name.startswith("object"):
                try:
                    # run_init_scripts=False 防止 OnCreated 递归导致崩溃
                    auto_container = network.createNode(
                        "geo",
                        None,
                        run_init_scripts=False,
                        load_contents=False,
                        exact_type_name=True,
                    )
                    auto_container.moveToGoodPosition()
                    messages.append(f"自动创建容器: {auto_container.name()}")
                    network = auto_container
                except Exception as exc:
                    messages.append(f"创建容器失败: {exc}")
            
            # 创建节点
            for idx, spec in enumerate(node_specs):
                if not isinstance(spec, dict):
                    node_errors.append(f"节点 #{idx} 不是 dict: {spec!r}")
                    continue
                
                node_id = spec.get("id") or spec.get("name") or f"node_{idx+1}"
                type_hint = spec.get("type") or spec.get("node_type")
                
                if not type_hint:
                    node_errors.append(f"[{node_id}] 缺少 type")
                    continue
                
                # 根据文档，createNode 可以直接处理节点类型匹配
                desired_cat = self._desired_category_from_hint(type_hint, network)
                if desired_cat is None:
                    # 如果无法识别类别，尝试使用当前网络的类别
                    desired_cat = network.childTypeCategory() if network else None
                    if desired_cat is None:
                        node_errors.append(f"[{node_id}] 无法识别类别: {type_hint}")
                        continue
                
                network = self._ensure_target_network(network, desired_cat)
                
                node_name = spec.get("name")
                safe_name = self._sanitize_node_name(node_name)
                
                # 剥离类别前缀（如 "sop/box" → "box"），防止模糊匹配崩溃
                clean_type = type_hint.split("/", 1)[-1] if "/" in (type_hint or "") else type_hint
                try:
                    new_node = network.createNode(
                        clean_type,
                        safe_name,
                        run_init_scripts=False,
                        load_contents=True,
                        exact_type_name=False,
                    )
                except hou.OperationFailed as exc:
                    node_errors.append(f"[{node_id}] 创建失败: {type_hint} - {exc}")
                    continue
                except Exception as exc:
                    node_errors.append(f"[{node_id}] 创建失败: {exc}")
                    continue
                
                # 设置参数（兼容 parameters 与 parms 两种字段名）
                params = spec.get("parameters")
                if params is None:
                    params = spec.get("parms", {})
                if isinstance(params, dict):
                    for parm_name, parm_value in params.items():
                        parm = new_node.parm(parm_name)
                        if parm is None:
                            # 尝试 parm tuple（多分量参数，如 size/t/r/s）
                            parm_tuple = new_node.parmTuple(parm_name)
                            if parm_tuple is not None and isinstance(parm_value, (list, tuple)):
                                try:
                                    parm_tuple.set(parm_value)
                                    continue
                                except Exception as exc:
                                    node_errors.append(
                                        f"[{node_id}] 参数 {parm_name} 设置失败: {exc}"
                                    )
                                    continue
                            node_errors.append(
                                f"[{node_id}] 未知参数: {parm_name}（请用 "
                                f"get_parameter_schema 查阅 {clean_type} 的参数名）"
                            )
                            continue
                        try:
                            parm.set(parm_value)
                        except Exception as exc:
                            node_errors.append(
                                f"[{node_id}] 参数 {parm_name}={parm_value!r} 设置失败: {exc}"
                            )
                
                created[node_id] = new_node
                creation_order.append(node_id)
            
            # 建立连接
            connections = plan.get("connections", [])
            connection_errors: List[str] = []
            for conn in connections:
                if not isinstance(conn, dict):
                    connection_errors.append(f"连接项不是 dict: {conn!r}")
                    continue

                src_id = conn.get("from") or conn.get("src")
                dst_id = conn.get("to") or conn.get("dst")
                input_index = int(conn.get("input", 0))

                src_node = created.get(src_id)
                dst_node = created.get(dst_id)

                # 找不到 id 时硬报错，不再静默跳过
                missing = []
                if src_node is None:
                    missing.append(f"from='{src_id}'")
                if dst_node is None:
                    missing.append(f"to='{dst_id}'")
                if missing:
                    available = ", ".join(created.keys()) or "(无)"
                    connection_errors.append(
                        f"连接 {src_id}->{dst_id} 失败: 未找到 {', '.join(missing)}；"
                        f"可用 id: {available}"
                    )
                    continue

                try:
                    dst_node.setInput(input_index, src_node)
                except Exception as exc:
                    connection_errors.append(f"连接 {src_id}->{dst_id} 失败: {exc}")

            # 合并到 messages，让最终摘要可见
            if connection_errors:
                messages.extend(connection_errors)
            
            # 自动布局：只整理本次创建的节点，避免破坏用户已有的手动布局。
            if created:
                try:
                    from . import hou_core
                    anchor_position = None
                    try:
                        editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
                        if editor and editor.pwd() == network:
                            center = editor.visibleBounds().center()
                            anchor_position = (float(center[0]), float(center[1]))
                    except Exception:
                        anchor_position = None
                    created_paths = [
                        created[nid].path()
                        for nid in creation_order
                        if nid in created and created[nid]
                    ]
                    hou_core.layout_nodes(
                        parent_path=network.path(),
                        node_paths=created_paths,
                        method="tidy",
                        spacing=1.0,
                        anchor_position=anchor_position,
                    )
                except Exception:
                    pass  # 布局失败不影响节点创建结果
                if creation_order:
                    last_node = created[creation_order[-1]]
                    last_node.setSelected(True, clear_all_selected=True)
                    try:
                        last_node.setDisplayFlag(True)
                        last_node.setRenderFlag(True)
                    except Exception:
                        pass
            
            summary = ", ".join(created[nid].path() for nid in creation_order if nid in created)
            has_hard_errors = bool(node_errors) or bool(connection_errors)

            if not created:
                # 全军覆没：硬失败
                err_text = "; ".join(node_errors + connection_errors) or "未创建任何节点"
                return False, f"批量创建失败: {err_text}"

            if has_hard_errors:
                # 部分成功 = 整体失败：让 AI 看见问题、决定回退或继续
                msg = (
                    f"批量创建部分失败（已创建 {len(created)} 个: {summary}）\n"
                    f"错误清单:\n  - " + "\n  - ".join(node_errors + connection_errors)
                )
                if messages:
                    msg += "\n备注: " + "; ".join(messages)
                return False, msg

            # 全部成功
            msg = f"已创建 {len(created)} 个节点: {summary}"
            if messages:
                msg += f"\n备注: {'; '.join(messages)}"
            msg += self._manual_mode_hint()
            return True, msg
        except Exception as exc:
            # 回滚：删除已创建的节点以保持场景干净
            if created:
                print(f"[MCP Client] 创建网络异常，回滚已创建的 {len(created)} 个节点...")
                for nid in reversed(creation_order):
                    try:
                        node = created.get(nid)
                        if node and node.path():
                            node.destroy()
                    except Exception:
                        pass
            return False, f"创建网络失败（已回滚）: {exc}"

    # ========================================
    # 节点连接
    # ========================================
    
    def connect_nodes(self, output_node_path: str, input_node_path: str,
                      input_index: int = 0, output_index: int = 0,
                      replace: bool = True) -> Tuple[bool, str]:
        """连接两个节点"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        out_node = hou.node(output_node_path)
        if out_node is None:
            return False, f"未找到输出节点: {output_node_path}"
        
        in_node = hou.node(input_node_path)
        if in_node is None:
            return False, f"未找到输入节点: {input_node_path}"
        
        try:
            input_idx = int(input_index)
            output_idx = int(output_index)
            max_inputs = in_node.type().maxNumInputs()
            if input_idx < 0 or input_idx >= max_inputs:
                return False, f"输入端口索引 {input_idx} 无效 (有效范围 0~{max_inputs - 1})"
            if output_idx < 0:
                return False, f"输出端口索引 {output_idx} 无效"
            if not replace and in_node.input(input_idx) is not None:
                return False, f"{input_node_path}[{input_idx}] 已有输入；如需替换请设置 replace=true"
            in_node.setInput(input_idx, out_node, output_idx)
            return True, f"已连接: {output_node_path}[{output_idx}] → {input_node_path}[{input_idx}]"
        except Exception as exc:
            return False, f"连接失败: {exc}"

    def disconnect_nodes(self, node_path: str,
                         input_index: Optional[int] = None) -> Tuple[bool, str]:
        """断开节点的一个或全部输入连接"""
        if hou is None:
            return False, "未检测到 Houdini API"
        node = hou.node(node_path)
        if node is None:
            return False, f"未找到节点: {node_path}"
        try:
            max_inputs = node.type().maxNumInputs()
            if input_index is not None:
                idx = int(input_index)
                if idx < 0 or idx >= max_inputs:
                    return False, f"输入端口索引 {idx} 无效 (有效范围 0~{max_inputs - 1})"
                node.setInput(idx, None)
                return True, f"已断开 {node_path}[{idx}] 的输入连接"
            else:
                disconnected = []
                for i in range(max_inputs):
                    if node.input(i) is not None:
                        node.setInput(i, None)
                        disconnected.append(i)
                if disconnected:
                    return True, f"已断开 {node_path} 的全部输入连接（端口: {disconnected}）"
                return True, f"节点 {node_path} 无活跃输入连接，无需操作"
        except Exception as exc:
            return False, f"断开连接失败: {exc}"

    def get_node_connections(self, node_path: str) -> Tuple[bool, Dict[str, Any]]:
        """读取节点输入/输出连接细节。"""
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        node = hou.node(node_path)
        if node is None:
            return False, {"error": f"未找到节点: {node_path}"}

        try:
            node_type = node.type()
            max_inputs = node_type.maxNumInputs() if node_type else 0
            inputs = []
            input_connections = {}
            try:
                input_connections = {conn.inputIndex(): conn for conn in node.inputConnections()}
            except Exception:
                input_connections = {}

            for index in range(max_inputs):
                source = None
                try:
                    source = node.input(index)
                except Exception:
                    pass
                entry: Dict[str, Any] = {
                    "index": index,
                    "label": "",
                    "connected": source is not None,
                    "source_path": source.path() if source is not None else None,
                    "source_type": source.type().name() if source is not None else None,
                    "source_output_index": 0,
                }
                try:
                    entry["label"] = node.inputLabel(index)
                except Exception:
                    pass
                conn = input_connections.get(index)
                if conn is not None:
                    try:
                        entry["source_output_index"] = conn.outputIndex()
                    except Exception:
                        pass
                inputs.append(entry)

            outputs = []
            try:
                for conn in node.outputConnections():
                    dst = conn.outputNode()
                    outputs.append({
                        "target_path": dst.path() if dst is not None else None,
                        "target_type": dst.type().name() if dst is not None else None,
                        "output_index": conn.outputIndex(),
                        "target_input_index": conn.inputIndex(),
                    })
            except Exception:
                for dst in node.outputs():
                    outputs.append({"target_path": dst.path(), "target_type": dst.type().name()})

            return True, {
                "path": node.path(),
                "type": node_type.name() if node_type else "unknown",
                "category": node_type.category().name() if node_type else "unknown",
                "inputs": inputs,
                "outputs": outputs,
                "input_count": len(inputs),
                "output_connection_count": len(outputs),
            }
        except Exception as exc:
            return False, {"error": f"读取连接失败: {exc}"}

    def suggest_connection(self, from_path: str, to_path: str) -> Tuple[bool, Dict[str, Any]]:
        """根据目标输入标签和现有连接推荐 input_index。"""
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        from_node = hou.node(from_path)
        to_node = hou.node(to_path)
        if from_node is None:
            return False, {"error": f"未找到上游节点: {from_path}"}
        if to_node is None:
            return False, {"error": f"未找到下游节点: {to_path}"}

        ok, data = self.get_node_connections(to_path)
        if not ok:
            return ok, data

        from_text = " ".join([
            from_node.name().lower(),
            from_node.type().name().lower(),
            from_node.type().description().lower() if from_node.type() else "",
        ])
        to_type = to_node.type().name().lower() if to_node.type() else ""
        suggestions = []
        for entry in data.get("inputs", []):
            index = int(entry.get("index", 0))
            label = str(entry.get("label") or "").lower()
            score = 100 - index
            reasons = []
            if not entry.get("connected"):
                score += 50
                reasons.append("input is empty")
            if index == 0:
                score += 10
                reasons.append("primary input")
            if any(word in from_text for word in ("point", "scatter", "pop")) and any(word in label for word in ("point", "template", "target")):
                score += 80
                reasons.append("point-like source matches point/template input")
            if any(word in label for word in ("geometry", "geo", "source", "input")) and index == 0:
                score += 30
                reasons.append("geometry/source primary input")
            if "merge" in to_type and not entry.get("connected"):
                score += 60
                reasons.append("merge prefers next empty input")
            suggestions.append({
                "input_index": index,
                "label": entry.get("label", ""),
                "connected": bool(entry.get("connected")),
                "current_source": entry.get("source_path"),
                "score": score,
                "reasons": reasons,
            })

        suggestions.sort(key=lambda item: item["score"], reverse=True)
        recommended = suggestions[0] if suggestions else {"input_index": 0, "reasons": ["fallback"]}
        return True, {
            "from_path": from_node.path(),
            "to_path": to_node.path(),
            "recommended_input_index": recommended.get("input_index", 0),
            "output_index": 0,
            "replace_needed": bool(recommended.get("connected", False)),
            "recommended": recommended,
            "candidates": suggestions,
        }

    def preview_node_operation(self, operation: str, args: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Dry-run 预览节点操作影响范围。"""
        op = (operation or "").strip()
        if not op:
            return False, {"error": "缺少 operation"}

        if op == "connect_nodes":
            from_path = args.get("from_path", "")
            to_path = args.get("to_path", "")
            input_index = int(args.get("input_index", 0) or 0)
            output_index = int(args.get("output_index", 0) or 0)
            ok, conns = self.get_node_connections(to_path)
            if not ok:
                return ok, conns
            target_input = next((item for item in conns.get("inputs", []) if item.get("index") == input_index), None)
            return True, {
                "operation": op,
                "will_modify": True,
                "action": "connect",
                "from_path": from_path,
                "to_path": to_path,
                "input_index": input_index,
                "output_index": output_index,
                "will_replace": bool(target_input and target_input.get("connected")),
                "current_source": target_input.get("source_path") if target_input else None,
            }
        if op == "disconnect_nodes":
            node_path = args.get("node_path", "")
            input_index = args.get("input_index")
            ok, conns = self.get_node_connections(node_path)
            if not ok:
                return ok, conns
            affected = [item for item in conns.get("inputs", []) if item.get("connected")]
            if input_index is not None:
                idx = int(input_index)
                affected = [item for item in affected if item.get("index") == idx]
            return True, {"operation": op, "will_modify": bool(affected), "affected_inputs": affected}
        if op == "set_node_flags":
            node_path = args.get("node_path", "")
            ok, data = self.inspect_node(node_path, include_params=False, compact=True)
            if not ok:
                return ok, data
            requested = {key: args.get(key) for key in ("display", "render", "bypass", "template", "lock", "select", "current") if args.get(key) is not None}
            return True, {"operation": op, "will_modify": bool(requested), "node_path": node_path, "current_flags": data.get("flags", {}), "requested_flags": requested}
        if op in ("delete_node", "cook_node"):
            node_path = args.get("node_path", "")
            ok, conns = self.get_node_connections(node_path)
            if not ok:
                return ok, conns
            return True, {"operation": op, "will_modify": op == "delete_node", "node_path": node_path, "connections": conns}
        if op == "create_named_null":
            return True, {"operation": op, "will_modify": True, "node_name": args.get("name"), "parent_path": args.get("parent_path"), "connect_from": args.get("connect_from")}
        return False, {"error": f"不支持预览操作: {operation}"}

    def create_named_null(self, parent_path: str = "", name: str = "OUT", connect_from: str = "",
                          input_index: int = 0, output_index: int = 0,
                          display: bool = False, render: bool = False) -> Tuple[bool, Dict[str, Any]]:
        """创建语义化 null，可选连接上游。"""
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        parent = hou.node(parent_path) if parent_path else self._current_network()
        if parent is None:
            return False, {"error": "未找到目标网络"}
        safe_name = self._sanitize_node_name(name or "OUT")
        if not safe_name.upper().startswith(("IN_", "OUT_", "CTRL_", "CACHE_")):
            safe_name = f"OUT_{safe_name}"
        try:
            node = parent.createNode("null", safe_name, run_init_scripts=False, load_contents=True, exact_type_name=False)
            if connect_from:
                ok, msg = self.connect_nodes(connect_from, node.path(), input_index, output_index, replace=True)
                if not ok:
                    node.destroy()
                    return False, {"error": msg}
                try:
                    source = hou.node(connect_from)
                    if source is not None:
                        pos = source.position()
                        # 偏移 2.5 单位（约 Houdini 1 格）避免与上游节点重叠
                        node.setPosition(hou.Vector2(pos[0], pos[1] - 2.5))
                except Exception:
                    pass
            else:
                try:
                    node.moveToGoodPosition()
                except Exception:
                    pass
            if display and hasattr(node, "setDisplayFlag"):
                node.setDisplayFlag(True)
            if render and hasattr(node, "setRenderFlag"):
                node.setRenderFlag(True)
            return True, {"path": node.path(), "name": node.name(), "parent_path": parent.path(), "connected_from": connect_from or None}
        except Exception as exc:
            return False, {"error": f"创建 named null 失败: {exc}"}

    def validate_node_network(self, root_path: str = "/obj", node_paths: Optional[List[str]] = None,
                              max_nodes: int = 200) -> Tuple[bool, Dict[str, Any]]:
        """验证节点网络的常见结构问题。"""
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        if node_paths:
            nodes = [hou.node(path) for path in node_paths if hou.node(path) is not None]
        else:
            root = hou.node(root_path)
            if root is None:
                return False, {"error": f"未找到 root: {root_path}"}
            nodes = list(root.allSubChildren())[:max_nodes]
        node_set = {node.path() for node in nodes}
        issues: List[Dict[str, Any]] = []
        display_nodes = []
        render_nodes = []
        isolated = []

        for node in nodes:
            path = node.path()
            try:
                if node.errors():
                    issues.append({"severity": "error", "node": path, "kind": "node_errors", "messages": list(node.errors())})
                if node.warnings():
                    issues.append({"severity": "warning", "node": path, "kind": "node_warnings", "messages": list(node.warnings())})
            except Exception:
                pass
            try:
                min_inputs = node.type().minNumInputs()
                for index in range(min_inputs):
                    if node.input(index) is None:
                        issues.append({"severity": "warning", "node": path, "kind": "missing_required_input", "input_index": index})
            except Exception:
                pass
            try:
                has_inputs = any(inp is not None for inp in (node.inputs() or []))
                has_outputs = any(out is not None and out.path() in node_set for out in (node.outputs() or []))
                if not has_inputs and not has_outputs:
                    isolated.append(path)
            except Exception:
                pass
            try:
                if hasattr(node, "isDisplayFlagSet") and node.isDisplayFlagSet():
                    display_nodes.append(path)
                if hasattr(node, "isRenderFlagSet") and node.isRenderFlagSet():
                    render_nodes.append(path)
            except Exception:
                pass

        if isolated:
            issues.append({"severity": "info", "kind": "isolated_nodes", "nodes": isolated[:50], "count": len(isolated)})
        return True, {
            "root_path": root_path,
            "node_count": len(nodes),
            "issue_count": len(issues),
            "issues": issues,
            "display_nodes": display_nodes,
            "render_nodes": render_nodes,
            "truncated": not node_paths and len(nodes) >= max_nodes,
        }

    def set_node_flags(self, node_path: str,
                       bypass: Optional[bool] = None,
                       template: Optional[bool] = None,
                       lock: Optional[bool] = None,
                       display: Optional[bool] = None,
                       render: Optional[bool] = None,
                       select: Optional[bool] = None,
                       current: Optional[bool] = None) -> Tuple[bool, str]:
        """设置节点的 display / render / bypass / template / lock / select/current 标志"""
        if hou is None:
            return False, "未检测到 Houdini API"
        node = hou.node(node_path)
        if node is None:
            return False, f"未找到节点: {node_path}"
        if all(value is None for value in (bypass, template, lock, display, render, select, current)):
            return False, "至少需要指定一个标志（display / render / bypass / template / lock / select / current）"
        try:
            applied = []
            if display is not None and hasattr(node, 'setDisplayFlag'):
                node.setDisplayFlag(display)
                applied.append(f"display={'on' if display else 'off'}")
            if render is not None and hasattr(node, 'setRenderFlag'):
                node.setRenderFlag(render)
                applied.append(f"render={'on' if render else 'off'}")
            if bypass is not None and hasattr(node, 'bypass'):
                node.bypass(bypass)
                applied.append(f"bypass={'on' if bypass else 'off'}")
            if template is not None and hasattr(node, 'setTemplateFlag'):
                node.setTemplateFlag(template)
                applied.append(f"template={'on' if template else 'off'}")
            if lock is not None and hasattr(node, 'setHardLocked'):
                node.setHardLocked(lock)
                applied.append(f"lock={'on' if lock else 'off'}")
            if select is not None and hasattr(node, 'setSelected'):
                node.setSelected(select, clear_all_selected=bool(select))
                applied.append(f"select={'on' if select else 'off'}")
            if current is not None and bool(current) and hasattr(node, 'setCurrent'):
                node.setCurrent(True, clear_all_selected=True)
                applied.append("current=on")
            if applied:
                return True, f"已设置 {node_path}: {', '.join(applied)}"
            return False, f"节点类型 {node.type().name()} 不支持请求的标志"
        except Exception as exc:
            return False, f"设置标志失败: {exc}"

    def cook_node(self, node_path: str, force: bool = False) -> Tuple[bool, Dict[str, Any]]:
        """Cook 节点并返回 cook 后诊断。

        force=False: 普通 cook（依赖 Houdini 自身的脏标记判断）。
        force=True : 硬复位 cook。流程：bypass on → off → 清缓存的 user data →
                    重新打 display flag → force cook。用于打破"上游引用已变但
                    下游节点缓存了 stale handle / VOP cache 导致 cook 跳过"的卡死。
                    对应用户手动操作里的"先 bypass 再激活，再选回 display"小技巧。
        """
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        node = hou.node(node_path)
        if node is None:
            return False, {"error": f"未找到节点: {node_path}"}
        steps: List[str] = []
        try:
            if force:
                # 1) bypass 触发上游引用复位（即使节点本来未 bypass 也走一遍）
                if hasattr(node, 'setBypassFlag') and hasattr(node, 'isBypassed'):
                    prev_bypass = bool(node.isBypassed())
                    try:
                        node.setBypassFlag(True)
                        node.setBypassFlag(False)
                        if prev_bypass:
                            node.setBypassFlag(True)  # 还原用户原始状态
                        steps.append("bypass-toggle")
                    except Exception as e:
                        steps.append(f"bypass-skip:{e}")
                # 2) 清掉 SOP 缓存的 user data（包括内部 VOP cache）
                if hasattr(node, 'destroyCachedUserData'):
                    try:
                        node.destroyCachedUserData()
                        steps.append("cache-clear")
                    except Exception:
                        pass
                # 3) 重打 display flag（如果当前已是 display，重设会触发 viewport 重新订阅）
                if hasattr(node, 'setDisplayFlag') and hasattr(node, 'isDisplayFlagSet'):
                    try:
                        was_display = bool(node.isDisplayFlagSet())
                        if was_display:
                            node.setDisplayFlag(False)
                            node.setDisplayFlag(True)
                            steps.append("display-reset")
                    except Exception:
                        pass

            node.cook(force=bool(force))
            steps.append("cook")
            data = {
                "path": node.path(),
                "force": bool(force),
                "steps": steps,
                "errors": list(node.errors()) if hasattr(node, "errors") else [],
                "warnings": list(node.warnings()) if hasattr(node, "warnings") else [],
                "messages": list(node.messages()) if hasattr(node, "messages") else [],
            }
            return True, data
        except Exception as exc:
            return False, {"error": f"Cook 失败: {exc}", "steps": steps}

    # ========================================
    # 参数设置
    # ========================================
    
    def set_parameter(self, node_path: str, param_name: str, value: Any) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """设置节点参数（设置前自动快照旧值，支持撤销）
        
        Returns:
            (success, message, undo_snapshot)
            undo_snapshot 包含 node_path, param_name, old_value, new_value
        """
        if hou is None:
            return False, "未检测到 Houdini API", None
        
        node = hou.node(node_path)
        if node is None:
            return False, f"未找到节点: {node_path}", None

        def parameter_not_found_message() -> str:
            try:
                candidates = sorted({parm_tuple.name() for parm_tuple in node.parmTuples()})
                close = difflib.get_close_matches(param_name, candidates, n=5, cutoff=0.45)
                hint_lower = param_name.lower()
                contains = [name for name in candidates if hint_lower in name.lower() or name.lower() in hint_lower]
                suggestions = []
                for name in close + contains:
                    if name not in suggestions:
                        suggestions.append(name)
                err = f"节点 {node_path} 不存在参数 '{param_name}'"
                if suggestions:
                    err += f"\nDid you mean: {', '.join(suggestions[:8])}?"
                else:
                    sample = candidates[:15]
                    err += f"\n该节点可用参数(前15): {', '.join(sample)}"
                    if len(candidates) > 15:
                        err += f" ... 共 {len(candidates)} 个"
                return err
            except Exception:
                return f"未找到参数: {param_name}"

        def resolve_menu_value(parm_obj: Any, raw_value: Any) -> Any:
            try:
                template = parm_obj.parmTemplate()
                menu_items = list(template.menuItems())
                if not menu_items or not isinstance(raw_value, str):
                    return raw_value
                labels = list(template.menuLabels()) if hasattr(template, "menuLabels") else menu_items
                raw_lc = raw_value.lower()
                for index, token in enumerate(menu_items):
                    if raw_lc == str(token).lower():
                        return token
                    if index < len(labels) and raw_lc == str(labels[index]).lower():
                        return token
                for index, label in enumerate(labels):
                    if raw_lc in str(label).lower() or raw_lc in str(menu_items[index]).lower():
                        return menu_items[index]
            except Exception:
                pass
            return raw_value
        
        # 尝试获取参数
        parm = node.parm(param_name)
        if parm is None:
            # 尝试作为元组参数
            parm_tuple = node.parmTuple(param_name)
            if parm_tuple is None:
                return False, parameter_not_found_message(), None
            
            if isinstance(value, (list, tuple)):
                try:
                    if len(value) != len(parm_tuple):
                        return False, f"参数 {param_name} 是 {len(parm_tuple)} 维 tuple，但收到 {len(value)} 个值", None
                    # 快照旧值（元组参数）
                    old_value = list(parm_tuple.eval())
                    resolved_value = []
                    for index, component in enumerate(parm_tuple):
                        resolved_value.append(resolve_menu_value(component, value[index]))
                    parm_tuple.set(resolved_value)
                    new_value = list(parm_tuple.eval())
                    snapshot = {
                        "node_path": node_path,
                        "param_name": param_name,
                        "old_value": old_value,
                        "new_value": new_value,
                        "is_tuple": True,
                    }
                    return True, f"已设置 {node_path} {param_name}: {old_value} → {new_value}", snapshot
                except Exception as exc:
                    return False, f"设置失败: {exc}", None
            else:
                return False, f"参数 {param_name} 需要列表或元组值", None
        
        try:
            # 快照旧值（标量参数）
            try:
                old_expr = parm.expression()
                old_lang = str(parm.expressionLanguage())
                old_value = {"expr": old_expr, "lang": old_lang}
            except Exception:
                old_value = parm.eval()
            
            resolved_value = resolve_menu_value(parm, value)
            parm.set(resolved_value)
            actual_value = parm.eval()
            snapshot = {
                "node_path": node_path,
                "param_name": param_name,
                "old_value": old_value,
                "new_value": actual_value,
                "is_tuple": False,
            }
            return True, f"已设置 {node_path} {param_name}: {old_value} → {actual_value}", snapshot
        except Exception as exc:
            return False, f"设置失败: {exc}", None

    def set_parameter_expression(self, node_path: str, param_name: str,
                                 expression: str, language: str = "hscript"
                                 ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """给节点参数设置表达式/通道引用（如 ch("../size")、$F、fit01(...)）。

        与 set_parameter 的区别：set_parameter 写入静态值，本方法建立可求值的
        表达式链接（HScript 或 Python）。设置前自动快照旧状态以支持撤销。

        Args:
            node_path: 节点完整路径
            param_name: 参数名（必须是标量参数，不能是 tuple 名）
            expression: 表达式字符串
            language: "hscript"（默认）或 "python"

        Returns:
            (success, message, undo_snapshot)
        """
        if hou is None:
            return False, "未检测到 Houdini API", None
        if not expression or not str(expression).strip():
            return False, "expression 不能为空", None

        node = hou.node(node_path)
        if node is None:
            return False, f"未找到节点: {node_path}", None

        parm = node.parm(param_name)
        if parm is None:
            # tuple 参数需逐分量设置，提示用户改用分量名
            parm_tuple = node.parmTuple(param_name)
            if parm_tuple is not None:
                comp_names = ", ".join(p.name() for p in parm_tuple)
                return False, (
                    f"'{param_name}' 是 tuple 参数，表达式需按分量设置。"
                    f"请对以下分量分别调用：{comp_names}"
                ), None
            return False, f"节点 {node_path} 不存在参数 '{param_name}'", None

        lang_key = str(language).strip().lower()
        if lang_key in ("python", "py"):
            expr_lang = hou.exprLanguage.Python
        elif lang_key in ("hscript", "hs", ""):
            expr_lang = hou.exprLanguage.Hscript
        else:
            return False, f"未知表达式语言: {language}（应为 hscript 或 python）", None

        # 快照旧状态（可能是表达式，也可能是静态值）
        try:
            old_expr = parm.expression()
            old_lang = str(parm.expressionLanguage())
            old_state = {"expr": old_expr, "lang": old_lang}
        except Exception:
            try:
                old_state = {"value": parm.eval()}
            except Exception:
                old_state = None

        try:
            parm.setExpression(str(expression), language=expr_lang)
        except Exception as exc:
            return False, f"设置表达式失败: {exc}", None

        snapshot = {
            "node_path": node_path,
            "param_name": param_name,
            "old_value": old_state,
            "new_value": {"expr": str(expression), "lang": lang_key or "hscript"},
            "is_expression": True,
        }
        return True, (
            f"已为 {node_path} {param_name} 设置{lang_key or 'hscript'}表达式: {expression}"
        ), snapshot

    # ========================================
    # 节点删除
    # ========================================
    
    @staticmethod
    def _snapshot_node(node, _depth: int = 0) -> Optional[Dict[str, Any]]:
        """在删除前快照节点状态（用于撤销重建）
        
        ★ 递归快照：自动保存所有子节点树，确保删除父节点后可完整恢复。
        
        Args:
            node: 要快照的 Houdini 节点
            _depth: 递归深度（内部使用，防止无限递归）
        
        Returns:
            快照字典，包含重建节点及其完整子树所需的全部信息；失败返回 None
        """
        if _depth > 20:  # 防止极端嵌套导致栈溢出
            return None
        try:
            node_type = node.type()
            parent = node.parent()
            if not node_type or not parent:
                return None
            
            # 基本信息
            snapshot: Dict[str, Any] = {
                "parent_path": parent.path(),
                "node_type": node_type.name(),
                "node_name": node.name(),
                "position": [node.position()[0], node.position()[1]],
            }
            
            # 非默认参数值
            params = {}
            try:
                for parm in node.parms():
                    try:
                        # 跳过锁定/不可写参数
                        if parm.isLocked():
                            continue
                        # 只保存与默认值不同的参数
                        default = parm.parmTemplate().defaultValue()
                        current = parm.eval()
                        # 表达式优先保存
                        try:
                            expr = parm.expression()
                            if expr:
                                params[parm.name()] = {"expr": expr, "lang": str(parm.expressionLanguage())}
                                continue
                        except Exception:
                            pass
                        # 比较 float 时容忍精度误差
                        if isinstance(current, float) and isinstance(default, (float, int)):
                            if abs(current - float(default)) > 1e-9:
                                params[parm.name()] = current
                        elif current != default:
                            params[parm.name()] = current
                    except Exception:
                        continue
            except Exception:
                pass
            snapshot["params"] = params
            
            # 输入连接
            input_connections = []
            try:
                for i, conn in enumerate(node.inputs()):
                    if conn is not None:
                        input_connections.append({
                            "input_index": i,
                            "source_path": conn.path(),
                        })
            except Exception:
                pass
            snapshot["input_connections"] = input_connections
            
            # 输出连接
            output_connections = []
            try:
                for conn in node.outputConnections():
                    output_connections.append({
                        "output_index": conn.outputIndex(),
                        "dest_path": conn.outputNode().path() if conn.outputNode() else "",
                        "dest_input_index": conn.inputIndex(),
                    })
            except Exception:
                pass
            snapshot["output_connections"] = output_connections
            
            # 标志位
            try:
                snapshot["display_flag"] = node.isDisplayFlagSet() if hasattr(node, 'isDisplayFlagSet') else False
                snapshot["render_flag"] = node.isRenderFlagSet() if hasattr(node, 'isRenderFlagSet') else False
            except Exception:
                snapshot["display_flag"] = False
                snapshot["render_flag"] = False
            
            # ★ 递归快照子节点树 — 确保删除父节点后可完整恢复子节点
            children_snapshots = []
            try:
                children = node.children()
                if children:
                    for child in children:
                        try:
                            child_snap = HoudiniMCP._snapshot_node(child, _depth + 1)
                            if child_snap:
                                children_snapshots.append(child_snap)
                        except Exception:
                            continue
            except Exception:
                pass
            if children_snapshots:
                snapshot["children"] = children_snapshots
            
            # ★ 快照子节点间的内部连接（兄弟节点之间的连线）
            # 外部连接已在各子节点的 input_connections / output_connections 中记录，
            # 但恢复时子节点是逐个创建的，内部连接需要在所有子节点创建完毕后单独恢复。
            internal_connections = []
            try:
                if children:
                    child_paths = set(c.path() for c in children)
                    for child in children:
                        try:
                            for i, inp in enumerate(child.inputs()):
                                if inp is not None and inp.path() in child_paths:
                                    internal_connections.append({
                                        "src_name": inp.name(),
                                        "dest_name": child.name(),
                                        "dest_input": i,
                                    })
                        except Exception:
                            continue
            except Exception:
                pass
            if internal_connections:
                snapshot["internal_connections"] = internal_connections
            
            return snapshot
        except Exception:
            return None

    def delete_node_by_path(self, node_path: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """按路径删除节点（删除前自动快照，支持撤销重建）
        
        Returns:
            (success, message, undo_snapshot)
        """
        if hou is None:
            return False, "未检测到 Houdini API", None
        
        node = hou.node(node_path)
        if node is None:
            return False, f"未找到节点: {node_path}", None
        
        try:
            # 删除前快照（用于撤销）
            snapshot = self._snapshot_node(node)
            
            full_path = node.path()
            name = node.name()
            parent = node.parent()
            parent_path = parent.path() if parent else ""
            
            # 收集连接信息（删除前）
            input_nodes = [n.path() for n in node.inputs() if n is not None] if node.inputs() else []
            output_conns = []
            try:
                for conn in node.outputConnections():
                    out_node = conn.outputNode()
                    if out_node:
                        output_conns.append(out_node.path())
            except Exception:
                pass
            
            node.destroy()
            
            # 返回完整路径 + diff 信息
            diff_parts = [f"已删除节点: {full_path}"]
            if parent_path:
                try:
                    remaining = len(hou.node(parent_path).children()) if hou.node(parent_path) else 0
                    diff_parts.append(f"(父网络: {parent_path}, 剩余子节点: {remaining})")
                except Exception:
                    diff_parts.append(f"(父网络: {parent_path})")
            if input_nodes:
                diff_parts.append(f"原输入: {', '.join(input_nodes)}")
            if output_conns:
                diff_parts.append(f"原输出到: {', '.join(output_conns[:3])}")
            
            return True, ' '.join(diff_parts), snapshot
        except Exception as exc:
            return False, f"删除失败: {exc}", None

    def delete_selected(self) -> Tuple[bool, str]:
        """删除选中的节点"""
        if hou is None:
            return False, "未检测到 Houdini API"
        
        nodes = list(hou.selectedNodes())
        if not nodes:
            return False, "没有选中的节点"
        
        paths = [n.path() for n in nodes]
        for n in nodes:
            try:
                n.destroy()
            except Exception:
                pass
        
        return True, f"已删除 {len(paths)} 个节点"

    # ========================================
    # 节点重命名
    # ========================================

    def rename_node(self, node_path: str, new_name: str) -> Tuple[bool, str]:
        """重命名节点

        Args:
            node_path: 节点完整路径，如 '/obj/geo1/box1'
            new_name:  新名称（仅允许字母、数字和下划线）

        Returns:
            (success, message)  message 包含 "旧路径 → 新路径" 或错误详情
        """
        if hou is None:
            return False, "未检测到 Houdini API"

        if not new_name or not new_name.strip():
            return False, "新名称不能为空"

        node = hou.node(node_path)
        if node is None:
            return False, f"未找到节点: {node_path}"

        safe_name = self._sanitize_node_name(new_name)
        if not safe_name:
            return False, f"名称 '{new_name}' 包含非法字符，清理后为空，无法使用"

        old_name = node.name()
        old_path = node.path()

        if old_name == safe_name:
            return True, f"节点名称未变更: {old_path}"

        try:
            node.setName(safe_name)
            new_path = node.path()
            return True, f"已重命名: {old_path} → {new_path}"
        except Exception as exc:
            return False, f"重命名失败: {exc}"

    # ========================================
    # Python 代码执行（类似 Cursor 终端）
    # ========================================
    
    class _ExecInterrupt(Exception):
        """execute_python / run_skill 超时或用户停止时抛出的中断异常"""
        pass

    @contextlib.contextmanager
    def _timeout_guard(self, timeout: float, check_interval: float = 0.5):
        """在代码块执行期间安装超时/停止监控（sys.settrace 逐行检查）。

        用于保护在 Houdini 主线程上执行、可能挂起的纯 Python 代码路径
        （execute_python / run_skill）。超时或用户点击停止时抛出
        HoudiniMCP._ExecInterrupt 中断执行，避免无限期卡住主线程。

        ★ 局限：仅能在下一条 Python 字节码执行前中断，无法中断 C 扩展
        内部的阻塞调用（如 hou.node().cook()、网络请求的底层 socket 等待）。
        """
        start_time = time.time()
        deadline = start_time + max(timeout, 5)
        stop_event = self._stop_event
        last_check = [start_time]

        def _trace_timeout(frame, event, arg):
            now = time.time()
            if now - last_check[0] < check_interval:
                return _trace_timeout
            last_check[0] = now
            if stop_event and stop_event.is_set():
                raise HoudiniMCP._ExecInterrupt("用户已停止执行")
            if now > deadline:
                raise HoudiniMCP._ExecInterrupt(
                    f"代码执行超时（{timeout}s），已中断。如需更长时间，请增加 timeout 参数。"
                )
            return _trace_timeout

        old_trace = sys.gettrace()
        sys.settrace(_trace_timeout)
        try:
            yield
        finally:
            sys.settrace(old_trace)

    def execute_python(self, code: str, timeout: int = 30) -> Tuple[bool, Dict[str, Any]]:
        """在 Houdini Python 环境中执行代码
        
        类似 Cursor 的终端功能，可以执行任意 Python 代码。
        
        Args:
            code: 要执行的 Python 代码
            timeout: 超时时间（秒）
        
        Returns:
            (success, result) 其中 result 包含:
            {
                "output": str,      # 输出内容
                "return_value": Any, # 最后一个表达式的返回值
                "error": str,       # 错误信息（如果有）
                "execution_time": float  # 执行时间（秒）
            }
        
        安全注意：
        - 此功能允许执行任意代码，应谨慎使用
        - 危险操作（如删除文件）需要用户确认
        
        ★ 超时保护（v1.4.5）：
        使用 sys.settrace 在每行 Python 代码执行前检查超时和停止标志。
        超时或用户停止时抛出 _ExecInterrupt 中断代码执行，防止卡死主线程。
        注意：对 C 扩展内部的阻塞（如 hou.node.cook）无法中断，
        但能在 C 调用返回后的下一行 Python 代码处中断。
        """
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        
        if not code or not code.strip():
            return False, {"error": "代码为空"}
        
        import io
        import traceback
        
        start_time = time.time()
        
        # 捕获输出
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        captured_output = io.StringIO()
        captured_error = io.StringIO()
        
        result = {
            "output": "",
            "return_value": None,
            "error": "",
            "execution_time": 0.0
        }
        
        try:
            sys.stdout = captured_output
            sys.stderr = captured_error
            
            # 准备执行环境
            exec_globals = {
                'hou': hou,
                '__builtins__': __builtins__,
            }
            exec_locals = {}
            
            # ★ 安装超时/停止监控，再执行代码
            with self._timeout_guard(timeout):
                # 尝试作为表达式求值（返回最后一个值）
                try:
                    # 先尝试 eval（单个表达式）
                    return_value = eval(code.strip(), exec_globals, exec_locals)
                    result["return_value"] = self._safe_repr(return_value)
                except SyntaxError:
                    # 不是单个表达式，用 exec 执行
                    exec(code, exec_globals, exec_locals)
                    
                    # 尝试获取最后一个赋值的值
                    if exec_locals:
                        last_var = list(exec_locals.keys())[-1]
                        if not last_var.startswith('_'):
                            result["return_value"] = self._safe_repr(exec_locals[last_var])
            
            result["output"] = captured_output.getvalue()
            
            # 检查 stderr
            stderr_content = captured_error.getvalue()
            if stderr_content:
                result["output"] += f"\n[stderr]\n{stderr_content}"
            
            result["execution_time"] = time.time() - start_time
            return True, result
        
        except HoudiniMCP._ExecInterrupt as e:
            result["error"] = str(e)
            result["output"] = captured_output.getvalue()
            result["execution_time"] = time.time() - start_time
            return False, result
            
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            result["output"] = captured_output.getvalue()
            result["execution_time"] = time.time() - start_time
            return False, result
            
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
    
    def _safe_repr(self, value: Any, max_length: int = 1000) -> str:
        """安全地获取对象的字符串表示"""
        try:
            # 处理常见类型
            if value is None:
                return "None"
            if isinstance(value, (int, float, bool)):
                return str(value)
            if isinstance(value, str):
                if len(value) > max_length:
                    return repr(value[:max_length] + "...")
                return repr(value)
            if isinstance(value, (list, tuple)):
                if len(value) > 10:
                    items = [self._safe_repr(v, 100) for v in value[:10]]
                    return f"[{', '.join(items)}, ... ({len(value)} items total)]"
                items = [self._safe_repr(v, 100) for v in value]
                return f"[{', '.join(items)}]"
            if isinstance(value, dict):
                if len(value) > 10:
                    items = [f"{k}: {self._safe_repr(v, 100)}" for k, v in list(value.items())[:10]]
                    return f"{{{', '.join(items)}, ... ({len(value)} items total)}}"
                items = [f"{k}: {self._safe_repr(v, 100)}" for k, v in value.items()]
                return f"{{{', '.join(items)}}}"
            
            # Houdini 对象
            if hou and hasattr(value, 'path'):
                return f"<{type(value).__name__}: {value.path()}>"
            if hou and hasattr(value, 'name'):
                return f"<{type(value).__name__}: {value.name()}>"
            
            # 默认
            s = repr(value)
            if len(s) > max_length:
                return s[:max_length] + "..."
            return s
        except Exception:
            return f"<{type(value).__name__}>"

    # ========================================
    # 工具分派处理器（每个工具一个方法）
    # ========================================

    def _tool_create_wrangle_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        vex_code = args.get("vex_code", "")
        if not vex_code:
            return {"success": False, "error": "缺少 vex_code 参数"}
        ok, msg = self.create_wrangle_node(
            vex_code, args.get("wrangle_type", "attribwrangle"),
            args.get("node_name"), args.get("run_over", "Points"),
            args.get("parent_path"))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_get_network_structure(self, args: Dict[str, Any]) -> Dict[str, Any]:
        network_path = args.get("network_path")
        box_name = args.get("box_name")  # NetworkBox 钻入参数
        page = int(args.get("page", 1))

        # 分页快速路径（box_name 也参与缓存键）
        cache_suffix = f":{box_name}" if box_name else ""
        cache_key = f"get_network_structure:{network_path or '_current'}{cache_suffix}"
        if page > 1 and cache_key in self._tool_page_cache:
            np_arg = f'network_path="{network_path}", ' if network_path else ''
            bx_arg = f'box_name="{box_name}", ' if box_name else ''
            hint = f'get_network_structure({np_arg}{bx_arg}page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                self._tool_page_cache[cache_key], cache_key, hint, page)}

        ok, data = self.get_network_structure(network_path)
        if ok:
            _, text = self.get_network_structure_text(network_path, box_name=box_name)
            np_arg = f'network_path="{network_path}", ' if network_path else ''
            bx_arg = f'box_name="{box_name}", ' if box_name else ''
            hint = f'get_network_structure({np_arg}{bx_arg}page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                text, cache_key, hint, page)}
        return {"success": False, "error": data.get("error", "未知错误")}

    def _tool_get_node_parameters(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """获取节点的所有可用参数（名称、类型、默认值、当前值），支持分页"""
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}
        page = int(args.get("page", 1))

        if hou is None:
            return {"success": False, "error": "未检测到 Houdini API"}

        # 分页快速路径：缓存中已有完整结果
        cache_key = f"get_node_parameters:{node_path}"
        if page > 1 and cache_key in self._tool_page_cache:
            hint = f'get_node_parameters(node_path="{node_path}", page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                self._tool_page_cache[cache_key], cache_key, hint, page)}

        node = hou.node(node_path)
        if node is None:
            return {"success": False, "error": f"未找到节点: {node_path}"}

        try:
            node_type = node.type()
            type_key = f"{node_type.category().name().lower()}/{node_type.name()}"
            lines = [
                f"## {node.name()} ({node.path()})",
                f"类型: {type_key} ({node_type.description()})",
            ]

            # ★ 节点概况（原 get_node_details 功能合并） ★
            # 状态标志
            flags = []
            is_bypassed = False
            if hasattr(node, 'isDisplayFlagSet') and node.isDisplayFlagSet():
                flags.append('display')
            if hasattr(node, 'isRenderFlagSet') and node.isRenderFlagSet():
                flags.append('render')
            if hasattr(node, 'isBypassed') and node.isBypassed():
                flags.append('bypass')
                is_bypassed = True
            if hasattr(node, 'isLocked') and node.isLocked():
                flags.append('locked')
            if flags:
                lines.append(f"标志: {', '.join(flags)}")
            if is_bypassed:
                lines.append("⚠ 此节点已 BYPASSED：参数仍存在但对下游无影响，不要据此推理网络行为。")

            # 错误信息
            try:
                errs = node.errors()
                if errs:
                    lines.append(f"⚠ 错误: {'; '.join(errs[:3])}")
            except Exception:
                pass

            # 输入连接
            inputs = []
            for i, inp in enumerate(node.inputs()):
                if inp is not None:
                    inputs.append(f"[{i}]{inp.path()}")
            if inputs:
                lines.append(f"输入: {', '.join(inputs)}")

            # 输出连接
            outputs = [o.path() for o in node.outputs()] if node.outputs() else []
            if outputs:
                lines.append(f"输出: {', '.join(outputs[:5])}")

            lines.append("")  # 空行分隔

            # 遍历所有参数模板（完整列表）
            parm_group = node_type.parmTemplateGroup()
            if not parm_group:
                lines.append("(无参数)")
                return {"success": True, "result": "\n".join(lines)}

            count = 0
            for pt in parm_group.parmTemplates():
                try:
                    if pt.isHidden():
                        continue
                    name = pt.name()
                    ptype = pt.type().name() if hasattr(pt, 'type') else "?"
                    label = pt.label() if hasattr(pt, 'label') else ""

                    # 获取默认值
                    default = None
                    try:
                        default = pt.defaultValue()
                        if isinstance(default, float):
                            default = round(default, 4)
                        elif isinstance(default, tuple):
                            default = tuple(round(v, 4) if isinstance(v, float) else v for v in default)
                    except Exception:
                        pass

                    # 获取当前值
                    current = None
                    try:
                        parm = node.parm(name)
                        if parm:
                            current = parm.eval()
                            if isinstance(current, float):
                                current = round(current, 4)
                            elif isinstance(current, tuple):
                                current = tuple(round(v, 4) if isinstance(v, float) else v for v in current)
                    except Exception:
                        pass

                    # 菜单选项（如果有）
                    menu_items = ""
                    if ptype == "Menu" and hasattr(pt, 'menuItems'):
                        try:
                            items = pt.menuItems()
                            labels = pt.menuLabels() if hasattr(pt, 'menuLabels') else items
                            if items and len(items) <= 10:
                                pairs = [f"{it}({lb})" if lb != it else it
                                         for it, lb in zip(items, labels)]
                                menu_items = f" options=[{', '.join(pairs)}]"
                            elif items:
                                menu_items = f" options=[{', '.join(items[:8])}...]"
                        except Exception:
                            pass

                    is_default = (current == default) if current is not None and default is not None else None
                    marker = "" if is_default else " *"  # * 标记非默认值

                    lines.append(
                        f"- {name} ({ptype}, {label}): "
                        f"default={default}, current={current}{marker}{menu_items}"
                    )
                    count += 1
                except Exception:
                    continue

            lines.insert(2, f"参数数量: {count}")
            full_text = "\n".join(lines)

            # 分页返回
            hint = f'get_node_parameters(node_path="{node_path}", page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                full_text, cache_key, hint, page)}

        except Exception as e:
            return {"success": False, "error": f"获取参数失败: {str(e)}"}

    def _tool_get_parameter_schema(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}

        ok, data = self.get_parameter_schema(
            node_path=node_path,
            pattern=args.get("pattern"),
            offset=int(args.get("offset", 0) or 0),
            limit=int(args.get("limit", 80) or 80),
            include_hidden=bool(args.get("include_hidden", False)),
        )
        if ok:
            stale = bool(data.get("manual_mode") and data.get("is_empty_geometry"))
            return {
                "success": True,
                "result": json.dumps(data, ensure_ascii=False, indent=2),
                "data": data,
                "health": "unknown" if stale else "healthy",
                "freshness": {
                    "status": "stale" if stale else "fresh",
                    "target": node_path,
                    "cook_succeeded": None,
                    "read_succeeded": True,
                },
            }
        return {"success": False, "error": str(data.get("error", "获取参数 schema 失败"))}

    def _tool_get_node_card(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_type = args.get("node_type", "")
        if not node_type:
            return {"success": False, "error": "缺少 node_type 参数（如 'scatter', 'copytopoints'）"}
        context = args.get("context", "Sop")
        parm_filter = args.get("parm_filter")
        ok, data = self.get_node_card(
            node_type=node_type,
            context=context,
            parm_filter=parm_filter,
            max_parms=int(args.get("max_parms", 40) or 40),
        )
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "获取节点 card 失败"))}

    def _tool_inspect_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}

        ok, data = self.inspect_node(
            node_path=node_path,
            include_params=bool(args.get("include_params", True)),
            max_params=int(args.get("max_params", 40) or 40),
            include_errors=bool(args.get("include_errors", True)),
            include_connections=bool(args.get("include_connections", True)),
            compact=bool(args.get("compact", False)),
        )
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "读取节点状态失败"))}

    def _tool_set_node_parameter(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        param_name = args.get("param_name", "")
        value = args.get("value")
        missing = []
        if not node_path:
            missing.append("node_path(节点路径)")
        if not param_name:
            missing.append("param_name(参数名)")
        if missing:
            return {"success": False, "error": f"缺少必要参数: {', '.join(missing)}"}
        ok, msg, snapshot = self.set_parameter(node_path, param_name, value)
        result = {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}
        if ok and snapshot:
            # ★ 参数前后值一致时不生成 checkpoint，避免显示无意义的"修改"
            old_v = snapshot.get("old_value")
            new_v = snapshot.get("new_value")
            if old_v != new_v:
                result["_undo_snapshot"] = snapshot  # 供 UI 撤销使用，不会发给 AI
        return result

    def _tool_set_parameter_expression(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        param_name = args.get("param_name", "")
        expression = args.get("expression", "")
        language = args.get("language", "hscript")
        missing = []
        if not node_path:
            missing.append("node_path(节点路径)")
        if not param_name:
            missing.append("param_name(参数名)")
        if not expression:
            missing.append("expression(表达式)")
        if missing:
            return {"success": False, "error": f"缺少必要参数: {', '.join(missing)}"}
        ok, msg, snapshot = self.set_parameter_expression(node_path, param_name, expression, language)
        result = {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}
        if ok and snapshot:
            result["_undo_snapshot"] = snapshot  # 供 UI 撤销使用，不会发给 AI
        return result

    def _tool_create_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_type = args.get("node_type", "")
        if not node_type:
            return {"success": False, "error": "缺少 node_type 参数"}
        ok, msg = self.create_node(
            node_type, args.get("node_name"),
            args.get("parameters"), args.get("parent_path"))
        if ok:
            return {"success": True, "result": msg, "error": ""}
        error_msg = msg if msg else f"创建节点失败: {node_type}"
        print(f"[MCP Client] create_node 失败: {error_msg[:200]}")
        return {"success": False, "result": "", "error": error_msg}

    def _tool_create_nodes_batch(self, args: Dict[str, Any]) -> Dict[str, Any]:
        nodes = args.get("nodes", [])
        if not nodes:
            return {"success": False, "error": "缺少 nodes 参数"}
        plan = {
            "nodes": nodes,
            "connections": args.get("connections", []),
            "parent_path": args.get("parent_path"),  # 透传父网络路径
            "dry_run": bool(args.get("dry_run", False)),  # 只校验、不创建
        }
        with _SuspendHoudiniUIRedraw():
            ok, msg = self.create_network(plan)
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_connect_nodes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from_path = args.get("from_path", "")
        to_path = args.get("to_path", "")
        missing = []
        if not from_path:
            missing.append("from_path(上游节点路径)")
        if not to_path:
            missing.append("to_path(下游节点路径)")
        if missing:
            return {"success": False, "error": f"缺少必要参数: {', '.join(missing)}"}
        with _SuspendHoudiniUIRedraw():
            ok, msg = self.connect_nodes(
                from_path,
                to_path,
                args.get("input_index", 0),
                args.get("output_index", 0),
                bool(args.get("replace", True)),
            )
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_disconnect_nodes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}
        input_index = args.get("input_index")
        if input_index is not None:
            input_index = int(input_index)
        ok, msg = self.disconnect_nodes(node_path, input_index)
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_get_node_connections(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}
        ok, data = self.get_node_connections(node_path)
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "读取节点连接失败"))}

    def _tool_suggest_connection(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from_path = args.get("from_path", "")
        to_path = args.get("to_path", "")
        if not from_path or not to_path:
            return {"success": False, "error": "缺少 from_path 或 to_path 参数"}
        ok, data = self.suggest_connection(from_path, to_path)
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "推荐连接失败"))}

    def _tool_preview_node_operation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        operation = args.get("operation", "")
        operation_args = args.get("args", {})
        if not isinstance(operation_args, dict):
            operation_args = {}
        ok, data = self.preview_node_operation(operation, operation_args)
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "预览操作失败"))}

    def _tool_create_named_null(self, args: Dict[str, Any]) -> Dict[str, Any]:
        ok, data = self.create_named_null(
            parent_path=args.get("parent_path", "") or args.get("network_path", ""),
            name=args.get("name", "OUT"),
            connect_from=args.get("connect_from", ""),
            input_index=int(args.get("input_index", 0) or 0),
            output_index=int(args.get("output_index", 0) or 0),
            display=bool(args.get("display", False)),
            render=bool(args.get("render", False)),
        )
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "创建 named null 失败"))}

    def preview_layout_nodes(
        self,
        parent_path: str = "",
        node_paths: Optional[List[str]] = None,
        method: str = "tidy",
        spacing: float = 1.0,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Dry-run 预览布局：返回当前位置和计划位置，不实际移动节点。"""
        if hou is None:
            return False, {"error": "未检测到 Houdini API"}
        from .hou_core import _layout_columns, _compute_tidy_layout
        parent = hou.node(parent_path) if parent_path else self._current_network()
        if parent is None:
            return False, {"error": "未找到目标网络"}
        if node_paths:
            nodes = [hou.node(p) for p in node_paths if hou.node(p)]
        else:
            nodes = list(parent.children())
        if not nodes:
            return False, {"error": "没有可布局的节点"}

        # 当前位置快照
        before = {}
        for n in nodes:
            pos = n.position()
            before[n.path()] = {"name": n.name(), "x": round(float(pos[0]), 3), "y": round(float(pos[1]), 3)}

        # 计算目标位置（纯 Python，不移动节点）
        node_ids = [n.path() for n in nodes]
        node_set = set(node_ids)
        edges = []
        original_positions = {}
        for n in nodes:
            try:
                pos = n.position()
                original_positions[n.path()] = (float(pos[0]), float(pos[1]))
            except Exception:
                original_positions[n.path()] = (0.0, 0.0)
            try:
                for idx, inp in enumerate(n.inputs() or []):
                    if inp is not None and inp.path() in node_set:
                        edges.append((inp.path(), n.path(), idx))
            except Exception:
                pass
        planned = _compute_tidy_layout(node_ids, edges, spacing=spacing, original_positions=original_positions)

        after = {}
        for n in nodes:
            x, y = planned.get(n.path(), (0.0, 0.0))
            after[n.path()] = {"name": n.name(), "x": round(x, 3), "y": round(y, 3)}

        # 检测潜在重叠（估算节点宽度）
        def _est_w(name: str) -> float:
            return max(3.5, len(name) * 0.13 + 2.5)

        overlap_warnings = []
        after_list = list(after.items())
        for i in range(len(after_list)):
            for j in range(i + 1, len(after_list)):
                p1, d1 = after_list[i]
                p2, d2 = after_list[j]
                if abs(d1["y"] - d2["y"]) < 1.0:  # 同层
                    gap = abs(d1["x"] - d2["x"])
                    min_gap = (_est_w(d1["name"]) + _est_w(d2["name"])) / 2.0
                    if gap < min_gap:
                        overlap_warnings.append({"a": d1["name"], "b": d2["name"], "gap": round(gap, 2), "min_gap": round(min_gap, 2)})

        moves = []
        for path in node_ids:
            b = before.get(path, {})
            a = after.get(path, {})
            dx = round(a.get("x", 0) - b.get("x", 0), 3)
            dy = round(a.get("y", 0) - b.get("y", 0), 3)
            moves.append({"path": path, "name": b.get("name", ""), "from": {"x": b.get("x"), "y": b.get("y")}, "to": {"x": a.get("x"), "y": a.get("y")}, "delta": {"dx": dx, "dy": dy}})

        return True, {
            "node_count": len(nodes),
            "method": method,
            "spacing": spacing,
            "moves": moves,
            "overlap_warnings": overlap_warnings,
            "will_move_count": sum(1 for m in moves if m["delta"]["dx"] != 0 or m["delta"]["dy"] != 0),
        }

    def _tool_preview_layout_nodes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_paths = args.get("node_paths")
        if isinstance(node_paths, str):
            node_paths = [p.strip() for p in node_paths.split(",") if p.strip()]
        ok, data = self.preview_layout_nodes(
            parent_path=args.get("parent_path", ""),
            node_paths=node_paths or None,
            method=args.get("method", "tidy"),
            spacing=float(args.get("spacing", 1.0) or 1.0),
        )
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "预览布局失败"))}

    def _tool_validate_node_network(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_paths = args.get("node_paths")
        if isinstance(node_paths, str):
            node_paths = [path.strip() for path in node_paths.split(",") if path.strip()]
        ok, data = self.validate_node_network(
            root_path=args.get("root_path", "/obj"),
            node_paths=node_paths,
            max_nodes=int(args.get("max_nodes", 200) or 200),
        )
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "验证网络失败"))}

    def _tool_set_node_flags(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}
        bypass = args.get("bypass")
        template = args.get("template")
        lock = args.get("lock")
        display = args.get("display")
        render = args.get("render")
        select = args.get("select")
        current = args.get("current")
        if all(value is None for value in (bypass, template, lock, display, render, select, current)):
            return {"success": False, "error": "至少需要指定一个标志（display / render / bypass / template / lock / select / current）"}
        ok, msg = self.set_node_flags(
            node_path,
            bypass=bypass,
            template=template,
            lock=lock,
            display=display,
            render=render,
            select=select,
            current=current,
        )
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_cook_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}
        ok, data = self.cook_node(node_path, bool(args.get("force", False)))
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "Cook 节点失败"))}

    def _tool_delete_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}
        ok, msg, snapshot = self.delete_node_by_path(node_path)
        result = {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}
        if ok and snapshot:
            result["_undo_snapshot"] = snapshot  # 供 UI 撤销使用，不会发给 AI
        return result

    def _tool_rename_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        new_name = args.get("new_name", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}
        if not new_name:
            return {"success": False, "error": "缺少 new_name 参数"}
        ok, msg = self.rename_node(node_path, new_name)
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_search_node_types(self, args: Dict[str, Any]) -> Dict[str, Any]:
        keyword = args.get("keyword", "")
        if not keyword:
            return {"success": False, "error": "缺少 keyword 参数"}
        ok, msg = self.search_nodes(
            keyword, args.get("limit", 10), category=args.get("category"))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_semantic_search_nodes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        description = args.get("description", "")
        if not description:
            return {"success": False, "error": "缺少 description 参数"}
        ok, msg = self.semantic_search_nodes(description, args.get("category", "sop"))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_list_children(self, args: Dict[str, Any]) -> Dict[str, Any]:
        network_path = args.get("network_path")
        recursive = args.get("recursive", False)
        page = int(args.get("page", 1))

        # 分页快速路径
        cache_key = f"list_children:{network_path or '_current'}:r={recursive}"
        if page > 1 and cache_key in self._tool_page_cache:
            np_arg = f'network_path="{network_path}", ' if network_path else ''
            hint = f'list_children({np_arg}recursive={recursive}, page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                self._tool_page_cache[cache_key], cache_key, hint, page)}

        ok, msg = self.list_children(network_path, recursive, args.get("show_flags", True))
        if not ok:
            return {"success": False, "error": msg}

        np_arg = f'network_path="{network_path}", ' if network_path else ''
        hint = f'list_children({np_arg}recursive={recursive}, page={page})'
        return {"success": True, "result": self._paginate_tool_result(
            msg, cache_key, hint, page)}

    def _tool_find_nodes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        ok, data = self.find_nodes(
            root_path=args.get("root_path", "/obj"),
            name_pattern=args.get("name_pattern", "*"),
            node_type=args.get("node_type"),
            category=args.get("category"),
            recursive=bool(args.get("recursive", True)),
            max_results=int(args.get("max_results", 100) or 100),
            offset=int(args.get("offset", 0) or 0),
        )
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "查找节点失败"))}

    def _tool_get_geometry_summary(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}

        sample_attributes = args.get("sample_attributes")
        if sample_attributes is not None and not isinstance(sample_attributes, list):
            sample_attributes = [str(sample_attributes)]

        ok, data = self.get_geometry_summary(
            node_path=node_path,
            max_sample_points=int(args.get("max_sample_points", 50) or 50),
            include_attributes=bool(args.get("include_attributes", True)),
            include_groups=bool(args.get("include_groups", True)),
            sample_attributes=sample_attributes,
            sample_primitives=bool(args.get("sample_primitives", False)),
        )
        if ok:
            stale = bool(data.get("manual_mode") and data.get("is_empty_geometry"))
            return {
                "success": True,
                "result": json.dumps(data, ensure_ascii=False, indent=2),
                "data": data,
                "health": "unknown" if stale else "healthy",
                "freshness": {
                    "status": "stale" if stale else "fresh",
                    "target": node_path,
                    "cook_succeeded": None,
                    "read_succeeded": True,
                },
            }
        return {"success": False, "error": str(data.get("error", "获取几何摘要失败"))}

    def _tool_get_scene_snapshot(self, args: Dict[str, Any]) -> Dict[str, Any]:
        ok, data = self.get_scene_snapshot(
            root_path=args.get("root_path", "/obj"),
            include_params=bool(args.get("include_params", False)),
            max_depth=int(args.get("max_depth", 6) or 6),
            max_nodes=int(args.get("max_nodes", 300) or 300),
        )
        if ok:
            return {"success": True, "result": json.dumps(data, ensure_ascii=False, indent=2)}
        return {"success": False, "error": str(data.get("error", "获取场景快照失败"))}

    def _tool_get_geometry_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}
        ok, msg = self.get_geometry_info(node_path, args.get("output_index", 0))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_read_selection(self, args: Dict[str, Any]) -> Dict[str, Any]:
        include_params = args.get("include_params", True)
        include_geometry = args.get("include_geometry", False)
        ok, msg = self.describe_selection(limit=5, include_all_params=include_params)
        if ok and include_geometry and hou:
            nodes = hou.selectedNodes()
            for node in nodes[:3]:
                geo_ok, geo_msg = self.get_geometry_info(node.path())
                if geo_ok:
                    msg += f"\n\n{geo_msg}"
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_set_display_flag(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = args.get("node_path", "")
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}
        ok, msg = self.set_display_flag(
            node_path, args.get("display", True), args.get("render", True))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_copy_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        source_path = args.get("source_path", "")
        if not source_path:
            return {"success": False, "error": "缺少 source_path 参数"}
        with _SuspendHoudiniUIRedraw():
            ok, msg = self.copy_node(
                source_path, args.get("dest_network"), args.get("new_name"))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_batch_set_parameters(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_paths = args.get("node_paths", [])
        param_name = args.get("param_name", "")
        missing = []
        if not node_paths:
            missing.append("node_paths(节点路径列表)")
        if not param_name:
            missing.append("param_name(参数名)")
        if missing:
            return {"success": False, "error": f"缺少必要参数: {', '.join(missing)}"}
        with _SuspendHoudiniUIRedraw():
            ok, data = self.batch_set_parameters(node_paths, param_name, args.get("value"))

        # 完全失败：保持 success=False，错误清单回传
        if not ok:
            if isinstance(data, dict) and data.get("failed"):
                lines = [f"  - {item['path']}: {item['error']}" for item in data["failed"]]
                msg = f"批量设置全部失败 ({data.get('summary', '')}):\n" + "\n".join(lines)
            else:
                msg = data.get("error", "批量设置失败") if isinstance(data, dict) else str(data)
            return {"success": False, "error": msg}

        # 部分或全部成功：success=True，结构化数据 + 人类可读摘要
        summary = data["summary"]
        result_lines = [summary]
        if data["set"]:
            result_lines.append("已设置: " + ", ".join(item["path"] for item in data["set"]))
        if data["failed"]:
            result_lines.append("失败清单:")
            result_lines.extend(f"  - {item['path']}: {item['error']}" for item in data["failed"])
        return {
            "success": True,
            "result": "\n".join(result_lines),
            "data": data,
        }

    def _tool_find_nodes_by_param(self, args: Dict[str, Any]) -> Dict[str, Any]:
        param_name = args.get("param_name", "")
        if not param_name:
            return {"success": False, "error": "缺少 param_name 参数"}
        ok, msg = self.find_nodes_by_param(
            param_name, args.get("value"),
            args.get("network_path"), args.get("recursive", True))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_save_hip(self, args: Dict[str, Any]) -> Dict[str, Any]:
        ok, msg = self.save_hip(args.get("file_path"))
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_undo_redo(self, args: Dict[str, Any]) -> Dict[str, Any]:
        action = args.get("action", "")
        if not action:
            return {"success": False, "error": "缺少 action 参数"}
        ok, msg = self.undo_redo(action)
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_execute_python(self, args: Dict[str, Any]) -> Dict[str, Any]:
        code = args.get("code", "")
        if not code:
            return {"success": False, "error": "缺少 code 参数"}
        page = int(args.get("page", 1))

        # 分页快速路径（只对成功的输出缓存）
        # 用 code 的 hash 作为缓存键，避免 key 过长
        import hashlib
        code_hash = hashlib.md5(code.encode()).hexdigest()[:12]
        cache_key = f"execute_python:{code_hash}"
        if page > 1 and cache_key in self._tool_page_cache:
            hint = f'execute_python(code="...同上...", page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                self._tool_page_cache[cache_key], cache_key, hint, page)}

        # 安全检查：检测危险操作
        security_msg = self._check_code_security(code)
        if security_msg:
            return {"success": False, "error": security_msg}
        timeout = int(args.get("timeout", 30))
        ok, result = self.execute_python(code, timeout=timeout)
        if ok:
            output_parts = []
            if result.get("output"):
                output_parts.append(f"输出:\n{result['output']}")
            if result.get("return_value") is not None:
                output_parts.append(f"返回值: {result['return_value']}")
            output_parts.append(f"执行时间: {result['execution_time']:.3f}s")
            full_text = "\n".join(output_parts)

            hint = f'execute_python(code="...同上...", page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                full_text, cache_key, hint, page)}
        # 失败：包含部分输出（如果有）+ 完整错误 + 执行时间
        error_parts = []
        partial_output = result.get("output", "")
        if partial_output:
            error_parts.append(f"[部分输出]\n{partial_output}")
        error_parts.append(result.get("error", "执行失败"))
        error_parts.append(f"执行时间: {result.get('execution_time', 0):.3f}s")
        return {"success": False, "error": "\n".join(error_parts), "result": partial_output}

    def _tool_temporary_auto_validate_geometry(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = str(args.get("node_path") or "").strip()
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数（要验证的 SOP 节点路径）"}
        if hou is None:
            return {"success": False, "error": "未检测到 Houdini API"}

        transaction = ScopedValidationTransaction(
            hou.updateModeSetting,
            hou.setUpdateMode,
            lambda: (
                getattr(hou.updateMode, "AutoUpdate", None)
                or getattr(hou.updateMode, "AlwaysUpdate", None)
                or getattr(hou.updateMode, "Auto", None)
            ),
        )

        def validate_target():
            node, error = self._resolve_geometry_node(node_path)
            if error:
                return ScopedValidationOperationResult(success=False, error=error)
            assert node is not None
            try:
                node.cook(force=True)
            except Exception as exc:
                return ScopedValidationOperationResult(
                    success=False, error=f"临时 Auto 验证 cook 失败: {exc}"
                )

            ok, result = self.get_geometry_summary(
                node_path,
                max_sample_points=int(args.get("max_sample_points", 0) or 0),
                include_attributes=bool(args.get("include_attributes", False)),
                include_groups=bool(args.get("include_groups", False)),
                sample_attributes=args.get("sample_attributes"),
                sample_primitives=bool(args.get("sample_primitives", False)),
            )
            if not ok:
                error_text = result.get("error", "临时 Auto 验证失败") if isinstance(result, dict) else str(result)
                return ScopedValidationOperationResult(
                    success=False, cook_succeeded=True, error=error_text
                )
            return ScopedValidationOperationResult(
                success=True,
                payload=result,
                health="unhealthy" if result.get("errors") else "healthy",
                cook_succeeded=True,
                read_succeeded=True,
            )

        outcome = transaction.run(node_path, validate_target)
        result = outcome.pop("payload", None)
        outcome["temporary_auto_validation"] = True
        outcome["result"] = result if result is not None else ""
        outcome["data"] = result if result is not None else {}
        if outcome["success"] and isinstance(result, dict):
            outcome["summary"] = (
                f"临时 Auto 验证完成: {node_path} points={result.get('point_count', '?')}, "
                f"prims={result.get('primitive_count', '?')}, "
                f"verification_update_mode={result.get('update_mode', 'unknown')}; "
                f"已恢复 update mode={outcome['restored_update_mode']}"
            )
        return outcome

    def _tool_set_update_mode(self, args: Dict[str, Any]) -> Dict[str, Any]:
        mode_text = str(args.get("mode") or "").strip().lower().replace("_", "-").replace(" ", "-")
        if not mode_text:
            return {"success": False, "error": "缺少 mode 参数（auto 或 manual）"}
        if hou is None:
            return {"success": False, "error": "未检测到 Houdini API"}

        if mode_text in {"auto", "auto-update", "autoupdate", "always", "alwaysupdate", "always-update"}:
            target_mode = (
                getattr(hou.updateMode, "AutoUpdate", None)
                or getattr(hou.updateMode, "AlwaysUpdate", None)
                or getattr(hou.updateMode, "Auto", None)
            )
        elif mode_text == "manual":
            target_mode = getattr(hou.updateMode, "Manual", None)
        else:
            return {"success": False, "error": "mode 必须是 auto 或 manual"}
        if target_mode is None:
            return {"success": False, "error": f"无法解析 update mode 枚举: {mode_text}"}

        try:
            previous = hou.updateModeSetting()
            previous_name = previous.name() if hasattr(previous, "name") else str(previous)
        except Exception:
            previous_name = "unknown"
        try:
            hou.setUpdateMode(target_mode)
            current = hou.updateModeSetting()
            current_name = current.name() if hasattr(current, "name") else str(current)
            return {
                "success": True,
                "result": f"Update Mode 已设置为 {current_name}（之前: {previous_name}）",
                "data": {
                    "requested": "auto" if mode_text != "manual" else "manual",
                    "effective": current_name,
                    "mode_kind": "auto" if mode_text != "manual" else "manual",
                    "persistent": True,
                },
                "previous_mode": previous_name,
                "mode": current_name,
                "persistent_update_mode_change": True,
            }
        except Exception as exc:
            return {"success": False, "error": f"设置 Update Mode 失败: {exc}"}

    # ========================================
    # 系统 Shell 沙盒执行
    # ========================================

    # Shell 命令黑名单（正则，忽略大小写）
    _SHELL_DANGEROUS_PATTERNS = [
        # 文件/目录批量删除
        (r'\brm\s+.*-r', "禁止递归删除 (rm -r)"),
        (r'\brm\s+.*-f', "禁止强制删除 (rm -f)"),
        (r'\brmdir\s+/s', "禁止递归删除目录 (rmdir /s)"),
        (r'\bdel\s+/s', "禁止递归删除 (del /s)"),
        (r'\bdel\s+/q', "禁止静默删除 (del /q)"),
        (r'\brd\s+/s', "禁止递归删除 (rd /s)"),
        # 格式化
        (r'\bformat\s+[a-zA-Z]:', "禁止格式化磁盘"),
        # 注册表
        (r'\breg\s+(delete|add)', "禁止修改注册表"),
        # 关机/重启
        (r'\bshutdown\b', "禁止关机"),
        (r'\breboot\b', "禁止重启"),
        # 权限提升
        (r'\brunas\b', "禁止 runas 提权"),
        (r'\bsudo\b', "禁止 sudo 提权"),
        # 网络配置
        (r'\bnetsh\b', "禁止修改网络配置"),
        # 进程注入
        (r'\btaskkill\s+/f', "禁止强制结束进程"),
        # 危险 PowerShell
        (r'Remove-Item\s+.*-Recurse', "禁止 PowerShell 递归删除"),
        (r'Invoke-Expression', "禁止 Invoke-Expression"),
        (r'\biex\b', "禁止 iex (Invoke-Expression 别名)"),
        # 磁盘操作
        (r'\bdiskpart\b', "禁止 diskpart"),
        # fork bomb
        (r'%0\|%0', "禁止 fork bomb"),
        (r':\(\)\{.*\}', "禁止 fork bomb"),
    ]

    # 允许的命令前缀白名单（粗粒度，不在名单中的也可以执行，只有黑名单才拦截）
    # 这个白名单仅用于日志提示
    _SHELL_COMMON_COMMANDS = frozenset({
        'pip', 'python', 'git', 'dir', 'ls', 'cd', 'echo', 'type', 'cat',
        'where', 'which', 'whoami', 'hostname', 'ipconfig', 'ifconfig',
        'curl', 'wget', 'ffmpeg', 'ffprobe', 'magick', 'convert',
        'hython', 'hbatch', 'mantra', 'hcmd',
        'node', 'npm', 'npx', 'conda', 'env', 'set', 'tree',
        'find', 'grep', 'rg', 'awk', 'sed', 'head', 'tail', 'wc',
        'mkdir', 'copy', 'cp', 'move', 'mv', 'ren', 'rename',
        'tar', 'zip', 'unzip', '7z',
    })

    def _check_shell_security(self, command: str) -> Optional[str]:
        """检查 Shell 命令是否包含危险操作"""
        for pattern, msg in self._SHELL_DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return f"安全拦截: {msg}\n命令: {command}\n如确需执行，请在系统终端中手动运行。"
        return None

    def _tool_execute_shell(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """在系统 Shell 中执行命令（沙盒环境）
        
        ★ v1.4.4 改进：使用 Popen + 轮询替代 subprocess.run
        - 支持用户通过停止按钮中断正在执行的命令
        - Windows 上正确杀死整个进程树（不只是 cmd.exe 父进程）
        - 防止 pipe buffer 满导致的死锁（使用 communicate 分块读取）
        """
        import subprocess
        import hashlib

        command = args.get("command", "").strip()
        if not command:
            return {"success": False, "error": "缺少 command 参数"}

        page = int(args.get("page", 1))
        timeout = min(int(args.get("timeout", 30)), 120)  # 最大 120 秒

        # 分页快速路径
        cmd_hash = hashlib.md5(command.encode()).hexdigest()[:12]
        cache_key = f"shell:{cmd_hash}"
        if page > 1 and cache_key in self._tool_page_cache:
            hint = f'execute_shell(command="...同上...", page={page})'
            return {"success": True, "result": self._paginate_tool_result(
                self._tool_page_cache[cache_key], cache_key, hint, page)}

        # 安全检查
        security_msg = self._check_shell_security(command)
        if security_msg:
            return {"success": False, "error": security_msg}

        # 工作目录
        cwd = args.get("cwd", "")
        if not cwd:
            # 默认：项目根目录
            cwd = str(Path(__file__).parent.parent.parent.parent)
        if not os.path.isdir(cwd):
            return {"success": False, "error": f"工作目录不存在: {cwd}"}

        # ★ 获取停止事件引用（从 AIClient 传入，用于检测用户中断）
        stop_event = getattr(self, '_stop_event', None)

        start_time = time.time()
        proc = None
        try:
            # 启动子进程（非阻塞）
            popen_kwargs = dict(
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
            )
            if sys.platform == 'win32':
                popen_kwargs.update(
                    encoding='utf-8',
                    errors='replace',
                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                popen_kwargs.update(text=True)
            
            proc = subprocess.Popen(command, **popen_kwargs)
            
            # ★ 轮询等待：每 0.5s 检查一次停止标志和超时
            deadline = start_time + timeout
            while proc.poll() is None:
                # 检查用户中断
                if stop_event and stop_event.is_set():
                    self._kill_process_tree(proc)
                    elapsed = time.time() - start_time
                    return {"success": False, "error": f"命令被用户中断\n命令: {command}\n已运行: {elapsed:.1f}s"}
                
                # 检查超时
                if time.time() > deadline:
                    self._kill_process_tree(proc)
                    elapsed = time.time() - start_time
                    return {"success": False, "error": f"命令超时（{timeout}s 限制）\n命令: {command}\n耗时: {elapsed:.2f}s"}
                
                # 短暂等待避免 CPU 空转
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
            
            # 进程已结束，读取输出
            stdout, stderr = proc.communicate(timeout=5)
            elapsed = time.time() - start_time

            # 组装输出
            parts = []
            if stdout:
                parts.append(stdout.rstrip())
            if stderr:
                parts.append(f"[stderr]\n{stderr.rstrip()}")
            parts.append(f"[退出码: {proc.returncode}, 耗时: {elapsed:.2f}s]")
            full_text = "\n".join(parts)

            success = proc.returncode == 0
            hint = f'execute_shell(command="...同上...", page={page})'
            return {"success": success, "result": self._paginate_tool_result(
                full_text, cache_key, hint, page)}

        except Exception as e:
            if proc and proc.poll() is None:
                self._kill_process_tree(proc)
            return {"success": False, "error": f"Shell 执行失败: {e}"}

    @staticmethod
    def _kill_process_tree(proc):
        """杀死进程及其所有子进程
        
        Windows 上使用 taskkill /F /T 杀死整个进程树，
        避免只杀 cmd.exe 而子进程继续运行导致挂起。
        """
        import subprocess as _sp
        try:
            if sys.platform == 'win32':
                # /F = 强制  /T = 杀死整个进程树  /PID = 进程 ID
                _sp.run(
                    f'taskkill /F /T /PID {proc.pid}',
                    shell=True,
                    capture_output=True,
                    timeout=5,
                    creationflags=_sp.CREATE_NO_WINDOW,
                )
            else:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ========================================
    # 节点布局工具
    # ========================================

    def _tool_layout_nodes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """布局节点 — 多策略自动整理节点位置"""
        from . import hou_core

        parent_path = args.get("network_path", "") or args.get("parent_path", "")
        if not parent_path:
            net = self._current_network()
            if net is not None:
                parent_path = net.path()

        node_paths = args.get("node_paths", None)
        if isinstance(node_paths, str):
            node_paths = [p.strip() for p in node_paths.split(",") if p.strip()]
        if node_paths is not None and len(node_paths) == 0:
            node_paths = None

        method = args.get("method", "auto")
        spacing = float(args.get("spacing", 1.0))

        with _SuspendHoudiniUIRedraw():
            ok, msg, positions = hou_core.layout_nodes(
                parent_path=parent_path,
                node_paths=node_paths,
                method=method,
                spacing=spacing,
            )
        if ok:
            # 构建可读的位置摘要
            lines = [msg]
            if positions and len(positions) <= 20:
                lines.append("节点位置:")
                for p in positions:
                    lines.append(f"  {p['path']}: ({p['x']}, {p['y']})")
            elif positions:
                lines.append(f"(共 {len(positions)} 个节点，仅显示前 10 个)")
                for p in positions[:10]:
                    lines.append(f"  {p['path']}: ({p['x']}, {p['y']})")
            return {"success": True, "result": "\n".join(lines)}
        return {"success": False, "error": msg}

    def _tool_get_node_positions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """获取节点位置信息"""
        from . import hou_core

        parent_path = args.get("network_path", "") or args.get("parent_path", "")
        if not parent_path:
            net = self._current_network()
            if net is not None:
                parent_path = net.path()

        node_paths = args.get("node_paths", None)
        if isinstance(node_paths, str):
            node_paths = [p.strip() for p in node_paths.split(",") if p.strip()]
        if node_paths is not None and len(node_paths) == 0:
            node_paths = None

        ok, msg, positions = hou_core.get_node_positions(
            parent_path=parent_path,
            node_paths=node_paths,
        )
        if ok:
            lines = [msg]
            for p in positions:
                lines.append(f"  {p['path']} ({p['type']}): ({p['x']}, {p['y']})")
            return {"success": True, "result": "\n".join(lines)}
        return {"success": False, "error": msg}

    # ========================================
    # NetworkBox 操作
    # ========================================

    def _tool_create_network_box(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """创建 NetworkBox 并可选地将节点加入其中"""
        from . import hou_core

        parent_path = args.get("parent_path", "")
        if not parent_path:
            # 默认使用当前网络
            net = self._current_network()
            if net is None:
                return {"success": False, "error": "未找到当前网络，请指定 parent_path"}
            parent_path = net.path()

        name = args.get("name", "")
        comment = args.get("comment", "")
        color_preset = args.get("color_preset", "")
        node_paths = args.get("node_paths", [])
        if isinstance(node_paths, str):
            node_paths = [p.strip() for p in node_paths.split(",") if p.strip()]

        with _SuspendHoudiniUIRedraw():
            ok, msg, box = hou_core.create_network_box(
                parent_path, name, comment, color_preset, node_paths
            )
        if ok:
            result_data = {"box_name": box.name() if box else name, "message": msg}
            return {"success": True, "result": msg}
        return {"success": False, "error": msg}

    def _tool_add_nodes_to_box(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """将节点添加到已有的 NetworkBox"""
        from . import hou_core

        parent_path = args.get("parent_path", "")
        if not parent_path:
            net = self._current_network()
            if net is None:
                return {"success": False, "error": "未找到当前网络，请指定 parent_path"}
            parent_path = net.path()

        box_name = args.get("box_name", "")
        if not box_name:
            return {"success": False, "error": "缺少 box_name 参数"}

        node_paths = args.get("node_paths", [])
        if isinstance(node_paths, str):
            node_paths = [p.strip() for p in node_paths.split(",") if p.strip()]
        if not node_paths:
            return {"success": False, "error": "缺少 node_paths 参数"}

        auto_fit = args.get("auto_fit", True)
        with _SuspendHoudiniUIRedraw():
            ok, msg = hou_core.add_nodes_to_box(parent_path, box_name, node_paths, auto_fit)
        return {"success": ok, "result": msg if ok else "", "error": "" if ok else msg}

    def _tool_list_network_boxes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """列出网络中所有 NetworkBox 及其内容"""
        from . import hou_core

        parent_path = args.get("parent_path", "")
        if not parent_path:
            net = self._current_network()
            if net is None:
                return {"success": False, "error": "未找到当前网络，请指定 parent_path"}
            parent_path = net.path()

        ok, msg, boxes_info = hou_core.list_network_boxes(parent_path)
        if ok:
            if not boxes_info:
                return {"success": True, "result": f"{parent_path} 中没有 NetworkBox"}
            lines = [f"{parent_path} 中有 {len(boxes_info)} 个 NetworkBox:\n"]
            for box in boxes_info:
                status = "📦" if not box["minimized"] else "📦(折叠)"
                lines.append(f"{status} {box['name']}: {box['comment'] or '(无注释)'}")
                lines.append(f"   包含 {box['node_count']} 个节点: {', '.join(box['nodes'][:10])}")
                if box['node_count'] > 10:
                    lines.append(f"   ...及另外 {box['node_count'] - 10} 个节点")
            return {"success": True, "result": "\n".join(lines)}
        return {"success": False, "error": msg}

    # ========================================
    # Skill 系统
    # ========================================

    def _tool_list_skills(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """列出所有可用 Skill（按分类分组）"""
        if not HAS_SKILLS or _list_skills is None:
            return {"success": False, "error": "Skill 系统未加载"}
        try:
            category = (args or {}).get("category") or None
            skills = _list_skills(category) if category else _list_skills()
            if not skills:
                if category:
                    return {"success": True, "result": f"分类 '{category}' 下没有可用的 Skill。"}
                return {"success": True, "result": "当前没有可用的 Skill。"}
            # 结构化输出：每个 skill 的 name/description/parameters 一次性给全，
            # AI 拿到后可直接调 run_skill，无需二次探索。
            import json as _json
            grouped: Dict[str, list] = {}
            for s in skills:
                params = s.get('parameters', {})
                param_list = []
                for pname, pinfo in params.items():
                    param_list.append({
                        "name": pname,
                        "type": pinfo.get("type", "string"),
                        "description": pinfo.get("description", ""),
                        "required": bool(pinfo.get("required", False)),
                    })
                cat = s.get("category", "other")
                grouped.setdefault(cat, []).append({
                    "name": s.get("name", ""),
                    "description": s.get("description", ""),
                    "risk_level": s.get("risk_level", "low"),
                    "parameters": param_list,
                })
            total = sum(len(v) for v in grouped.values())
            cats = ", ".join(f"{c}({len(v)})" for c, v in sorted(grouped.items()))
            hint = (
                f"共 {total} 个 Skill，分 {len(grouped)} 类：{cats}。"
                f"调用方式：run_skill(skill_name=\"<name>\", params={{...}})。"
                f"可用 list_skills(category=\"<类名>\") 只看某一类。"
                f"risk_level != low 的 Skill 会改场景/建图，Plan 规划阶段不可用（仅执行阶段）。"
            )
            payload = {c: grouped[c] for c in sorted(grouped)}
            return {
                "success": True,
                "result": hint + "\n\n" + _json.dumps(payload, ensure_ascii=False, indent=2),
            }
        except Exception as e:
            return {"success": False, "error": f"列出 Skill 失败: {e}"}

    def _tool_run_skill(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """执行指定 Skill

        ★ 超时保护（与 execute_python 共用 _timeout_guard）：
        Skill 代码同样运行在 Houdini 主线程上，一旦其中出现死循环/挂起
        （包括第三方/用户自定义 skill），此前完全没有超时保护，会导致
        主线程一直卡死直到用户强杀 Houdini。现在与 execute_python 一样
        通过 sys.settrace 逐行检查超时/停止标志来尽快中断纯 Python 代码。
        """
        if not HAS_SKILLS or _run_skill is None:
            return {"success": False, "error": "Skill 系统未加载"}

        skill_name = args.get("skill_name", "")
        if not skill_name:
            return {"success": False, "error": "缺少 skill_name 参数"}

        params = args.get("params", {})
        if not isinstance(params, dict):
            try:
                params = json.loads(str(params))
            except Exception:
                return {"success": False, "error": "params 必须是 JSON 对象"}

        try:
            timeout = int(args.get("timeout", 60))
        except (TypeError, ValueError):
            timeout = 60
        timeout = max(5, min(timeout, 300))

        try:
            with self._timeout_guard(timeout):
                result = _run_skill(skill_name, params)
            if "error" in result:
                return {"success": False, "error": result["error"]}

            # 格式化输出
            import json as _json
            formatted = _json.dumps(result, ensure_ascii=False, indent=2)
            return {"success": True, "result": formatted}
        except HoudiniMCP._ExecInterrupt as e:
            return {"success": False, "error": f"Skill '{skill_name}' 执行被中断：{e}"}
        except Exception as e:
            import traceback
            return {"success": False, "error": f"Skill 执行异常: {e}\n{traceback.format_exc()[:500]}"}

    def _tool_check_errors(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_path = str(args.get("node_path") or "").strip()
        if not node_path:
            return {"success": False, "error": "缺少 node_path 参数"}

        original_mode = None
        original_mode_name = "unknown"
        target = hou.node(node_path) if hou is not None else None
        if target is None:
            return {"success": False, "error": f"未找到节点: {node_path}", "health": "unknown"}

        try:
            original_mode = hou.updateModeSetting()
            original_mode_name = original_mode.name() if hasattr(original_mode, "name") else str(original_mode)
        except Exception:
            original_mode = None

        manual_mode = original_mode is not None and original_mode == getattr(hou.updateMode, "Manual", None)
        if manual_mode:
            transaction = ScopedValidationTransaction(
                hou.updateModeSetting,
                hou.setUpdateMode,
                lambda: (
                    getattr(hou.updateMode, "AutoUpdate", None)
                    or getattr(hou.updateMode, "AlwaysUpdate", None)
                    or getattr(hou.updateMode, "Auto", None)
                ),
            )

            def validate_target():
                if hasattr(target, "needsToCook") and target.needsToCook():
                    reason = "Target may contain uncooked Volume/VDB geometry; scoped cook was skipped for safety."
                    return ScopedValidationOperationResult(
                        success=False, validation_blocked=True,
                        block_reason=reason, error=reason,
                    )
                target.cook(force=True)
                ok, text = self.check_node_errors_text(node_path)
                lower_text = text.lower()
                unhealthy = "error" in lower_text or "错误" in text and "无错误" not in text
                return ScopedValidationOperationResult(
                    success=bool(ok), payload=text,
                    health="unhealthy" if unhealthy else "healthy",
                    cook_succeeded=True, read_succeeded=bool(ok),
                    error="" if ok else text,
                )

            outcome = transaction.run(node_path, validate_target)
            text = outcome.pop("payload", None)
            outcome["result"] = text if outcome["success"] else "验证状态未知；目标健康状态未确认。"
            outcome["recovery_hint"] = outcome.get("block_reason", "")
            return outcome

        ok, text = self.check_node_errors_text(node_path)
        lower_text = text.lower()
        unhealthy = "error" in lower_text or "错误" in text and "无错误" not in text
        return {
            "success": ok,
            "result": text,
            "health": "unhealthy" if unhealthy else "healthy",
            "freshness": {
                "status": "fresh",
                "target": node_path,
                "cook_succeeded": True,
                "read_succeeded": bool(ok),
            },
            "restore_attempted": False,
            "restore_succeeded": True,
            "restored_update_mode": original_mode_name,
        }

    def _tool_verify_network(self, args: Dict[str, Any]) -> Dict[str, Any]:
        parent_path = args.get("parent_path", "")
        if not parent_path:
            return {"success": False, "error": "缺少 parent_path 参数（要核查的网络路径，如 '/obj/geo1'）"}
        cook = bool(args.get("cook_display", True))
        ok, text = self.verify_network(parent_path, cook_display=cook)
        result = {"success": ok, "result": text if ok else "", "error": "" if ok else text}
        if ok:
            result["validation_signal"] = self._verify_network_validation_signal(parent_path)
        return result

    def _verify_network_validation_signal(self, parent_path: str) -> Dict[str, Any]:
        signal = {
            "manual_mode_detected": False,
            "display_geometry_empty": None,
            "recommended_next_action": "inspect_wiring_or_parameters",
        }
        if hou is None:
            return signal
        try:
            mode = hou.updateModeSetting()
            signal["update_mode"] = mode.name() if hasattr(mode, "name") else str(mode)
            signal["manual_mode_detected"] = (mode == hou.updateMode.Manual)
        except Exception:
            signal["update_mode"] = "unknown"
        try:
            parent = hou.node(parent_path)
            display = parent.displayNode() if parent is not None and hasattr(parent, "displayNode") else None
            if display is None:
                return signal
            geo = display.geometry()
            if geo is None:
                return signal
            points = int(geo.intrinsicValue("pointcount"))
            prims = int(geo.intrinsicValue("primitivecount"))
            signal["display_geometry"] = {
                "points": points,
                "prims": prims,
                "vertices": int(geo.intrinsicValue("vertexcount")),
            }
            signal["display_geometry_empty"] = (points == 0 and prims == 0)
            if signal["manual_mode_detected"] and signal["display_geometry_empty"]:
                signal["recommended_next_action"] = "temporary_auto_validate"
        except Exception:
            pass
        return signal

    def _tool_search_local_doc(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not HAS_DOC_RAG:
            return {"success": False, "error": "DocIndex 模块未加载"}
        # 兼容旧参数 keyword，统一收敛到 query。
        query = args.get("query") or args.get("keyword", "")
        if not query:
            return {"success": False, "error": "缺少 query 参数（或旧参数 keyword）"}

        def _confidence_band(score: float) -> str:
            if score >= 0.80:
                return "high"
            if score >= 0.55:
                return "medium"
            return "low"

        try:
            index = get_doc_rag()
            results = index.search(query, top_k=min(args.get("top_k", 5), 10))
            if not results:
                return {
                    "success": True,
                    "query": query,
                    "count": 0,
                    "items": [],
                    "result": f"未找到与 '{query}' 相关的文档",
                }

            parts = [f"找到 {len(results)} 个相关条目:\n"]
            items = []
            for idx, r in enumerate(results, 1):
                parts.append(f"{idx}. [{r['type'].upper()}] {r['name']} (score={r['score']:.1f})")
                src = r.get("source", "")
                if src:
                    parts.append(f"   source: {src}")
                rank_reason = r.get("rank_reason", "")
                if rank_reason:
                    parts.append(f"   reason: {rank_reason}")
                parts.append(f"   {r['snippet']}\n")

                items.append({
                    "rank": idx,
                    "type": r.get("type", "unknown"),
                    "name": r.get("name", ""),
                    "score": round(float(r.get("score", 0.0)), 3),
                    "confidence_band": _confidence_band(float(r.get("score", 0.0))),
                    "source": r.get("source", ""),
                    "matched_terms": r.get("matched_terms", []),
                    "rank_reason": r.get("rank_reason", ""),
                    "snippet": r.get("snippet", ""),
                })

            return {
                "success": True,
                "query": query,
                "count": len(items),
                "items": items,
                "result": "\n".join(parts),
            }
        except Exception as e:
            import traceback
            return {"success": False, "error": f"文档检索失败: {e}\n{traceback.format_exc()}"}

    def _tool_get_houdini_node_doc(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_type = args.get("node_type", "")
        if not node_type:
            return {"success": False, "error": "缺少 node_type 参数"}
        page = int(args.get("page", 1))
        ok, doc_text = self._get_houdini_local_doc(node_type, args.get("category", "sop"), page)
        return {"success": ok, "result": doc_text if ok else "", "error": "" if ok else doc_text}

    def _tool_get_node_inputs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        node_type = args.get("node_type", "")
        if not node_type:
            return {"success": False, "error": "缺少 node_type 参数"}
        ok, info = self.get_node_input_info(node_type, args.get("category", "sop"))
        return {"success": ok, "result": info if ok else "", "error": "" if ok else info}

    # ========================================
    # 性能分析 (perfMon) 工具
    # ========================================

    def _tool_perf_start_profile(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """启动 hou.perfMon 性能 profile"""
        if hou is None:
            return {"success": False, "error": "Houdini 环境不可用"}

        title = args.get("title", "AI Performance Analysis")
        force_cook_node = args.get("force_cook_node", "")

        # 如果已有活跃 profile，先停止旧的
        if self._active_perf_profile is not None:
            try:
                self._active_perf_profile.stop()
            except Exception:
                pass
            self._active_perf_profile = None

        try:
            profile = hou.perfMon.startProfile(title)
            self._active_perf_profile = profile
        except Exception as e:
            return {"success": False, "error": f"启动 perfMon profile 失败: {e}"}

        result_msg = f"已启动性能 profile: {title}"

        # 可选：启动后立即强制 cook 指定节点
        if force_cook_node:
            node = hou.node(force_cook_node)
            if node:
                try:
                    node.cook(force=True)
                    result_msg += f"\n已强制 cook 节点: {force_cook_node}"
                except Exception as e:
                    result_msg += f"\n强制 cook {force_cook_node} 失败: {e}"
            else:
                result_msg += f"\n警告: 节点 {force_cook_node} 不存在，跳过 cook"

        result_msg += "\n提示: 完成操作后调用 perf_stop_and_report 获取分析报告。"
        return {"success": True, "result": result_msg}

    def _tool_perf_stop_and_report(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """停止 perfMon profile 并返回分析报告"""
        if hou is None:
            return {"success": False, "error": "Houdini 环境不可用"}

        if self._active_perf_profile is None:
            return {"success": False, "error": "没有活跃的性能 profile。请先调用 perf_start_profile 启动。"}

        save_path = args.get("save_path", "")

        profile = self._active_perf_profile
        self._active_perf_profile = None

        try:
            profile.stop()
        except Exception as e:
            return {"success": False, "error": f"停止 profile 失败: {e}"}

        # 获取统计数据
        stats_data = None
        try:
            stats_data = profile.stats()
        except Exception as e:
            return {"success": False, "error": f"获取 profile 统计数据失败: {e}"}

        # 可选：保存到磁盘
        save_msg = ""
        if save_path:
            try:
                hou.perfMon.saveProfile(profile, save_path)
                save_msg = f"\n已保存 profile 到: {save_path}"
            except Exception as e:
                save_msg = f"\n保存 profile 失败: {e}"

        # 解析统计数据，提取关键指标
        report_parts = ["=== 性能分析报告 ==="]

        if isinstance(stats_data, dict):
            # 尝试提取 cook 事件统计
            cook_stats = stats_data.get("cookStats", stats_data.get("cook_stats", {}))
            script_stats = stats_data.get("scriptStats", stats_data.get("script_stats", {}))
            memory_stats = stats_data.get("memoryStats", stats_data.get("memory_stats", {}))

            if cook_stats:
                report_parts.append("\n--- Cook 统计 ---")
                # 解析节点 cook 时间
                node_times = []
                if isinstance(cook_stats, dict):
                    for key, val in cook_stats.items():
                        if isinstance(val, dict):
                            t = val.get("time", val.get("selfTime", 0))
                            node_times.append((key, t))
                        elif isinstance(val, (int, float)):
                            node_times.append((key, val))
                node_times.sort(key=lambda x: x[1], reverse=True)
                for name, t in node_times[:15]:
                    report_parts.append(f"  {name}: {t:.2f}ms")
                if len(node_times) > 15:
                    report_parts.append(f"  ... 还有 {len(node_times) - 15} 个条目")

            if script_stats:
                report_parts.append("\n--- 脚本统计 ---")
                if isinstance(script_stats, dict):
                    for key, val in list(script_stats.items())[:10]:
                        report_parts.append(f"  {key}: {val}")

            if memory_stats:
                report_parts.append("\n--- 内存统计 ---")
                if isinstance(memory_stats, dict):
                    for key, val in list(memory_stats.items())[:10]:
                        report_parts.append(f"  {key}: {val}")

            if not cook_stats and not script_stats and not memory_stats:
                # 统计格式未知，输出原始数据的摘要
                import json as _json
                raw = _json.dumps(stats_data, indent=2, default=str, ensure_ascii=False)
                if len(raw) > 2000:
                    raw = raw[:2000] + "\n... (truncated)"
                report_parts.append("\n--- 原始统计数据 ---")
                report_parts.append(raw)
        elif isinstance(stats_data, str):
            report_parts.append(stats_data[:3000])
        else:
            report_parts.append(f"统计数据类型: {type(stats_data).__name__}")
            report_parts.append(str(stats_data)[:3000])

        if save_msg:
            report_parts.append(save_msg)

        full_report = "\n".join(report_parts)

        # 使用分页返回
        page = int(args.get("page", 1))
        cache_key = "perf_stop_and_report:latest"
        hint = f'perf_stop_and_report(page={page})'
        return {"success": True, "result": self._paginate_tool_result(
            full_report, cache_key, hint, page)}

    # ========================================
    # 工具分派表 & 用法提示 & 安全检查
    # ========================================

    # 工具用法提示：参数缺失或调用出错时附带正确调用方式
    _TOOL_USAGE: Dict[str, str] = {
        "get_network_structure": 'get_network_structure(network_path="/obj/geo1", page=1)',
        "get_node_parameters": 'get_node_parameters(node_path="/obj/geo1/box1", page=1)',
        "set_node_parameter": 'set_node_parameter(node_path="/obj/geo1/box1", param_name="sizex", value=2.0)',
        "set_parameter_expression": 'set_parameter_expression(node_path="/obj/geo1/copy1", param_name="ncy", expression="ch(\\"../box1/sizex\\")", language="hscript")  # 设表达式/通道引用，非静态值',
        "create_node": 'create_node(parent_path="/obj/geo1", node_type="box", node_name="box1")',
        "get_node_card": 'get_node_card(node_type="scatter", context="Sop")  # 用陌生节点前查：min/max inputs + 参数 + menu items',
        "create_nodes_batch": 'create_nodes_batch(parent_path="/obj/geo1", nodes=[{"id":"a","type":"box","parameters":{"sizex":2}},{"id":"b","type":"scatter"}], connections=[{"from":"a","to":"b","input":0}])  # 陌生节点先用 dry_run=True 校验',
        "create_wrangle_node": 'create_wrangle_node(parent_path="/obj/geo1", code="@P.y += 1;", name="my_wrangle")',
        "connect_nodes": 'connect_nodes(from_path="/obj/geo1/box1", to_path="/obj/geo1/merge1", input_index=0)',
        "delete_node": 'delete_node(node_path="/obj/geo1/box1")',
        "rename_node": 'rename_node(node_path="/obj/geo1/box1", new_name="my_box")',
        "search_node_types": 'search_node_types(keyword="scatter", category="sop")',
        "semantic_search_nodes": 'semantic_search_nodes(query="随机散布点", category="sop")',
        "list_children": 'list_children(path="/obj/geo1", page=1)',
        "read_selection": 'read_selection()',
        "set_display_flag": 'set_display_flag(node_path="/obj/geo1/box1")',
        "copy_node": 'copy_node(source_path="/obj/geo1/box1", dest_parent="/obj/geo1", new_name="box1_copy")',
        "batch_set_parameters": 'batch_set_parameters(node_path="/obj/geo1/box1", parameters={"sizex":2,"sizey":3})',
        "find_nodes_by_param": 'find_nodes_by_param(network_path="/obj/geo1", param_name="file", param_value="*.bgeo")',
        "save_hip": 'save_hip(file_path="C:/path/to/file.hip")',
        "undo_redo": 'undo_redo(action="undo")',
        "execute_python": 'execute_python(code="import hou; print(hou.node(\\"/obj\\").children())")',
        "execute_shell": 'execute_shell(command="pip list", cwd="C:/project", timeout=30)',
        "check_errors": 'check_errors(node_path="/obj/geo1/box1")',
        "set_update_mode": 'set_update_mode(mode="auto")  # 将当前 hip 切到 Auto Update；mode 仅支持 "auto"/"manual"',
        "verify_network": 'verify_network(parent_path="/obj/geo1")  # 建完一组节点后，一次性核查整个网络（errors/warnings/flags/display 几何）',
        "search_local_doc": 'search_local_doc(query="scatter")',
        "get_houdini_node_doc": 'get_houdini_node_doc(node_type="scatter", page=1)',
        "get_node_inputs": 'get_node_inputs(node_type="copytopoints", category="sop")',
        "run_skill": 'run_skill(skill_name="analyze_geometry_attribs", params={"node_path":"/obj/geo1/box1"})',
        "list_skills": 'list_skills()',
        # 节点布局
        "layout_nodes": 'layout_nodes(network_path="/obj/geo1", method="auto")',
        "get_node_positions": 'get_node_positions(network_path="/obj/geo1")',
        # NetworkBox
        "create_network_box": 'create_network_box(parent_path="/obj/geo1", name="input_stage", comment="数据输入", color_preset="input", node_paths=["/obj/geo1/box1"])',
        "add_nodes_to_box": 'add_nodes_to_box(parent_path="/obj/geo1", box_name="input_stage", node_paths=["/obj/geo1/box1"])',
        "list_network_boxes": 'list_network_boxes(parent_path="/obj/geo1")',
        # PerfMon 性能分析
        "perf_start_profile": 'perf_start_profile(title="Cook Analysis", force_cook_node="/obj/geo1/output0")',
        "perf_stop_and_report": 'perf_stop_and_report(save_path="C:/tmp/profile.hperf")',
    }

    # 工具名称 -> 处理方法名的映射表
    _TOOL_DISPATCH: Dict[str, str] = {
        "create_wrangle_node": "_tool_create_wrangle_node",
        "get_network_structure": "_tool_get_network_structure",
        "get_node_parameters": "_tool_get_node_parameters",
        "get_parameter_schema": "_tool_get_parameter_schema",
        "get_node_card": "_tool_get_node_card",
        "inspect_node": "_tool_inspect_node",
        "set_node_parameter": "_tool_set_node_parameter",
        "set_parameter_expression": "_tool_set_parameter_expression",
        "create_node": "_tool_create_node",
        "create_nodes_batch": "_tool_create_nodes_batch",
        "connect_nodes": "_tool_connect_nodes",
        "disconnect_nodes": "_tool_disconnect_nodes",
        "get_node_connections": "_tool_get_node_connections",
        "suggest_connection": "_tool_suggest_connection",
        "preview_node_operation": "_tool_preview_node_operation",
        "create_named_null": "_tool_create_named_null",
        "validate_node_network": "_tool_validate_node_network",
        "preview_layout_nodes": "_tool_preview_layout_nodes",
        "cook_node": "_tool_cook_node",
        "delete_node": "_tool_delete_node",
        "rename_node": "_tool_rename_node",
        "search_node_types": "_tool_search_node_types",
        "semantic_search_nodes": "_tool_semantic_search_nodes",
        "list_children": "_tool_list_children",
        "find_nodes": "_tool_find_nodes",
        "get_geometry_summary": "_tool_get_geometry_summary",
        "temporary_auto_validate_geometry": "_tool_temporary_auto_validate_geometry",
        "set_update_mode": "_tool_set_update_mode",
        "get_scene_snapshot": "_tool_get_scene_snapshot",
        # "get_geometry_info" 已移除，由 skill 替代
        "read_selection": "_tool_read_selection",
        "set_display_flag": "_tool_set_display_flag",
        "set_node_flags": "_tool_set_node_flags",
        "copy_node": "_tool_copy_node",
        "batch_set_parameters": "_tool_batch_set_parameters",
        "find_nodes_by_param": "_tool_find_nodes_by_param",
        "save_hip": "_tool_save_hip",
        "undo_redo": "_tool_undo_redo",
        "execute_python": "_tool_execute_python",
        "execute_shell": "_tool_execute_shell",
        "check_errors": "_tool_check_errors",
        "verify_network": "_tool_verify_network",
        "search_local_doc": "_tool_search_local_doc",
        "get_houdini_node_doc": "_tool_get_houdini_node_doc",
        "get_node_inputs": "_tool_get_node_inputs",
        "run_skill": "_tool_run_skill",
        "list_skills": "_tool_list_skills",
        # 节点布局
        "layout_nodes": "_tool_layout_nodes",
        "get_node_positions": "_tool_get_node_positions",
        # NetworkBox
        "create_network_box": "_tool_create_network_box",
        "add_nodes_to_box": "_tool_add_nodes_to_box",
        "list_network_boxes": "_tool_list_network_boxes",
        # PerfMon 性能分析
        "perf_start_profile": "_tool_perf_start_profile",
        "perf_stop_and_report": "_tool_perf_stop_and_report",
        # 长期记忆主动搜索
        "search_memory": "_tool_search_memory",
        "remember_memory": "_tool_remember_memory",
        # 视口截图
        "capture_viewport": "_tool_capture_viewport",
    }

    @contextlib.contextmanager
    def _undo_group(self, tool_name: str):
        """统一为写操作包一个 undo group。读操作和无 hou 环境时直接 pass-through。"""
        use_undo = False
        try:
            from ..tool_registry import get_tool_registry
            use_undo = bool(
                (get_tool_registry().get_execution_semantics(tool_name) or {}).get("undo")
            )
        except Exception:
            use_undo = False
        if hou is not None and use_undo and hasattr(hou, "undos"):
            try:
                with hou.undos.group(f"Agent: {tool_name}"):
                    yield
                return
            except Exception:
                # undos.group 在某些上下文（如非主线程 / hython）下不可用，
                # 回退到不分组执行，不影响功能。
                pass
        yield

    @staticmethod
    def _cook_and_report(node: Any, force: bool = True) -> Dict[str, Any]:
        """Cook 节点并返回结构化报告: {cooked, cook_time_ms, errors, warnings}。

        统一所有"主动 cook + 看错误"路径的返回结构，避免散落各处的
        node.errors()/node.warnings() 重复块。
        """
        start = time.time()
        cook_exc: Optional[str] = None
        try:
            node.cook(force=bool(force))
        except Exception as e:
            cook_exc = str(e)
        elapsed_ms = round((time.time() - start) * 1000.0, 1)

        errors: List[str] = []
        warnings: List[str] = []
        try:
            errors = [str(e).strip() for e in node.errors() if str(e).strip()]
        except Exception:
            pass
        try:
            warnings = [str(w).strip() for w in node.warnings() if str(w).strip()]
        except Exception:
            pass
        if cook_exc and not errors:
            errors.append(cook_exc)

        return {
            "node": node.path() if hasattr(node, "path") else "",
            "cooked": not errors,
            "cook_time_ms": elapsed_ms,
            "errors": errors,
            "warnings": warnings,
        }

    # Python 代码安全黑名单
    _DANGEROUS_PATTERNS = [
        (r'\bos\.remove\b', "禁止使用 os.remove 删除文件"),
        (r'\bos\.rmdir\b', "禁止使用 os.rmdir 删除目录"),
        (r'\bshutil\.rmtree\b', "禁止使用 shutil.rmtree 递归删除"),
        (r'\bos\.system\b', "禁止使用 os.system 执行系统命令"),
        (r'\bsubprocess\b', "禁止使用 subprocess 执行外部进程"),
        (r'\b__import__\b', "禁止使用 __import__ 动态导入"),
        (r'\bopen\s*\([^)]*["\']w["\']', "禁止以写入模式打开文件（可用读取模式）"),
        (r'\bhou\.exit\b', "禁止使用 hou.exit 退出 Houdini"),
        (r'\bhou\.hipFile\.clear\b', "禁止使用 hou.hipFile.clear 清空场景"),
    ]

    def _check_code_security(self, code: str) -> Optional[str]:
        """检查代码是否包含危险操作，返回警告消息或 None"""
        for pattern, msg in self._DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                return f"⛔ 安全拦截: {msg}\n如确需执行，请在 Houdini Python Shell 中手动运行。"
        return None

    # 这些工具出错时应提示 AI 先查阅文档再重试，不要盲目重试
    _DOC_CHECK_TOOLS: frozenset = frozenset({
        'create_node',
        'create_nodes_batch',
        'create_wrangle_node',
        'set_node_parameter',
        'batch_set_parameters',
        'connect_nodes',
    })

    def _append_usage_hint(self, tool_name: str, error_msg: str) -> str:
        """在错误消息末尾附加工具的正确调用方式，以及查阅文档的建议"""
        parts = [error_msg]

        usage = self._TOOL_USAGE.get(tool_name)
        if usage:
            parts.append(f"正确调用方式: {usage}")

        # 节点创建/参数设置类工具出错 → 强烈建议查阅文档再重试
        if tool_name in self._DOC_CHECK_TOOLS:
            parts.append(
                "⚠️ 请不要盲目重试！先通过以下方式确认正确信息再重新调用:\n"
                "  1. search_node_types(keyword=\"...\") — 搜索正确的节点类型名\n"
                "  2. get_houdini_node_doc(node_type=\"...\") — 查阅该节点的参数文档\n"
                "  3. get_node_parameters(node_path=\"...\") — 查看已有节点的实际参数名和当前值\n"
                "确认节点类型名、参数名、参数值类型无误后，再重新调用本工具。"
            )

        return "\n\n".join(parts)

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any], mode: str = "agent") -> Dict[str, Any]:
        """执行工具调用 - AI Agent 的统一工具入口（基于分派表）
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数
        
        Returns:
            {"success": bool, "result": str, "error": str}
        """
        print(f"[MCP Client] 执行工具: {tool_name}, 参数: {list(arguments.keys())}")

        if tool_name != "scene_info":
            try:
                from ..tool_registry import get_tool_registry
                authorization = get_tool_registry().authorize_dispatch(tool_name, mode, "houdini")
            except Exception as exc:
                return {"success": False, "error": f"Tool Registry unavailable: {exc}"}
            if not authorization.get("allowed"):
                return {"success": False, "error": authorization.get("error", "Tool dispatch denied")}
        
        # ★ Hook: on_before_tool — 允许插件拦截/审计/修改参数
        try:
            from ..hooks import get_hook_manager as _ghm
            _hm = _ghm()
            _hm.fire('on_before_tool', tool_name=tool_name, args=arguments)
        except Exception:
            pass
        
        handler_name = self._TOOL_DISPATCH.get(tool_name)
        
        # Non-core tools are resolved exclusively through ToolRegistry.
        if handler_name is None:
            try:
                from ..tool_registry import get_tool_registry
                _reg = get_tool_registry()
                _handler = _reg.get_handler_for_execution(tool_name, mode, "houdini")
                if _handler:
                    result = _reg.execute(tool_name, arguments, mode=mode, runtime="houdini")
                    if not isinstance(result, dict):
                        result = {"success": True, "result": str(result)}
                    try:
                        from ..hooks import get_hook_manager as _ghm
                        _ghm().fire('on_after_tool', tool_name=tool_name, args=arguments, result=result)
                    except Exception:
                        pass
                    return result
            except Exception:
                pass
            return self._tool_unknown(tool_name)
        
        handler = getattr(self, handler_name, None)
        if handler is None:
            return {"success": False, "error": f"工具处理器未实现: {handler_name}"}
        
        try:
            with self._undo_group(tool_name):
                result = handler(arguments)
            # 工具返回失败时，自动附加用法提示
            if not result.get("success") and result.get("error"):
                result["error"] = self._append_usage_hint(tool_name, result["error"])
            # ★ Hook: on_after_tool — 通知插件工具执行完成
            try:
                from ..hooks import get_hook_manager as _ghm
                _ghm().fire('on_after_tool', tool_name=tool_name, args=arguments, result=result)
            except Exception:
                pass
            return result
        except Exception as e:
            import traceback
            print(f"[MCP Client] 工具执行异常: {traceback.format_exc()}")
            err = f"工具 {tool_name} 执行异常: {str(e)}"
            return {"success": False, "error": self._append_usage_hint(tool_name, err)}

    # ========================================
    # 长期记忆主动搜索
    # ========================================

    def _tool_remember_memory(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Persist an explicit user-requested long-term memory."""
        content = str(args.get("content") or "").strip()
        if not content:
            return {"success": False, "error": "content 参数不能为空"}
        try:
            from ..explicit_memory import remember_explicit_memory
            result = remember_explicit_memory(
                username=self._username,
                content=content,
                session_id=str(getattr(self, "_session_id", "") or ""),
            )
        except Exception as exc:
            return {"success": False, "error": f"写入长期记忆失败: {exc}"}
        if result.status in {"created", "already_exists"}:
            return {
                "success": True,
                "result": {
                    "status": result.status,
                    "memory_id": result.memory_id,
                    "message": result.message,
                },
            }
        return {"success": False, "error": result.message or "未保存长期记忆。"}

    def _tool_search_memory(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """搜索长期记忆库 — 联合检索 semantic / episodic / procedural"""
        query = args.get("query", "")
        print(f"[search_memory] 收到搜索请求: query={query!r}, args={args}")
        if not query:
            return {"success": False, "error": "query 参数不能为空"}

        category = args.get("category")
        top_k = min(max(args.get("top_k", 5), 1), 10)

        try:
            from ..memory_store import get_memory_store, ABSTRACTION_LEVELS
            store = get_memory_store(self._username)
            sem_total = store.count_semantic()
            epi_total = store.count_episodic()
            proc_total = store.count_procedural()
            print(
                f"[search_memory] 记忆库统计: semantic={sem_total}, "
                f"episodic={epi_total}, procedural={proc_total}"
            )

            sem_results = store.search_all_levels(
                query=query,
                category=category,
                top_k=top_k,
                min_confidence=0.1,
            )
            # Episodic/Procedural 通常作为辅助记忆，默认数量略小，降低噪音。
            epi_results = store.search_episodic(
                query=query,
                top_k=min(3, top_k),
                min_importance=0.2,
            )
            proc_results = store.search_procedural(
                query=query,
                top_k=min(3, top_k),
            )

            is_semantic_backend = store.embedder.is_semantic
            epi_threshold = 0.3 if is_semantic_backend else 0.05
            proc_threshold = 0.25 if is_semantic_backend else 0.04

            semantic_memories = []
            for rec, score in sem_results:
                level_name = ABSTRACTION_LEVELS.get(rec.abstraction_level, "unknown")
                semantic_memories.append({
                    "type": "semantic",
                    "source": "personal",
                    "rule": rec.rule,
                    "category": rec.category,
                    "abstraction_level": rec.abstraction_level,
                    "level_name": level_name,
                    "confidence": round(rec.confidence, 2),
                    "relevance": round(score, 3),
                    "activation_count": rec.activation_count,
                })

            episodic_memories = []
            for rec, score in epi_results:
                if score < epi_threshold:
                    continue
                episodic_memories.append({
                    "type": "episodic",
                    "task_description": rec.task_description,
                    "result_summary": rec.result_summary,
                    "success": rec.success,
                    "importance": round(rec.importance, 2),
                    "error_count": rec.error_count,
                    "retry_count": rec.retry_count,
                    "relevance": round(score, 3),
                })

            procedural_memories = []
            for rec, score in proc_results:
                if score < proc_threshold:
                    continue
                procedural_memories.append({
                    "type": "procedural",
                    "source": "personal",
                    "strategy_name": rec.strategy_name,
                    "description": rec.description,
                    "priority": round(rec.priority, 2),
                    "success_rate": round(rec.success_rate, 2),
                    "usage_count": rec.usage_count,
                    "relevance": round(score, 3),
                })

            # ★ 团队记忆（只读）：与个人库联合检索，结果标注 source=team + contributors。
            try:
                from ..team_memory_store import get_team_memory_store
                team_store = get_team_memory_store()
                for rec, score in team_store.search_semantic(query=query, top_k=min(3, top_k), category=category):
                    if score < epi_threshold:
                        continue
                    level_name = ABSTRACTION_LEVELS.get(rec.abstraction_level, "unknown")
                    semantic_memories.append({
                        "type": "semantic",
                        "source": "team",
                        "rule": rec.rule,
                        "category": rec.category,
                        "abstraction_level": rec.abstraction_level,
                        "level_name": level_name,
                        "confidence": round(rec.confidence, 2),
                        "relevance": round(score, 3),
                        "contributors": rec.source_users,
                    })
                for rec, score in team_store.search_procedural(query=query, top_k=min(2, top_k)):
                    if score < proc_threshold:
                        continue
                    procedural_memories.append({
                        "type": "procedural",
                        "source": "team",
                        "strategy_name": rec.strategy_name,
                        "description": rec.description,
                        "priority": round(rec.priority, 2),
                        "success_rate": round(rec.success_rate, 2),
                        "relevance": round(score, 3),
                        "contributors": rec.source_users,
                    })
            except Exception as e:
                print(f"[search_memory] 团队记忆检索跳过 (非致命): {e}")

            total_found = len(semantic_memories) + len(episodic_memories) + len(procedural_memories)
            print(
                f"[search_memory] 搜索结果: semantic={len(semantic_memories)}, "
                f"episodic={len(episodic_memories)}, procedural={len(procedural_memories)}"
            )

            if total_found == 0:
                return {
                    "success": True,
                    "count": 0,
                    "memories": [],
                    "message": (
                        "未找到相关记忆"
                        f"（semantic={sem_total}, episodic={epi_total}, procedural={proc_total}）"
                    ),
                }

            # 更新激活计数
            for rec, _ in sem_results:
                try:
                    store.increment_semantic_activation(rec.id)
                except Exception:
                    pass

            return {
                "success": True,
                "count": total_found,
                "query": query,
                "category_filter": category,
                # 兼容旧返回字段：memories 保留语义层结果
                "memories": semantic_memories,
                "semantic_memories": semantic_memories,
                "episodic_memories": episodic_memories,
                "procedural_memories": procedural_memories,
                "semantic_count": len(semantic_memories),
                "episodic_count": len(episodic_memories),
                "procedural_count": len(procedural_memories),
            }

        except Exception as e:
            return {"success": False, "error": f"记忆搜索失败: {str(e)}"}

    # ========================================
    # 视口截图
    # ========================================

    def _tool_capture_viewport(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """截取当前 Houdini 3D 视口的快照，返回 base64 编码的图片。
        
        使用 flipbook 机制截取当前帧的单帧图片，供 AI 视觉分析节点运行结果。
        ★ 必须在主线程执行（涉及 hou UI 操作）。
        """
        if hou is None:
            return {"success": False, "error": "Houdini 环境不可用"}
        
        width = args.get("width", 960)
        height = args.get("height", 540)
        output_path = args.get("output_path", "")
        # 限制分辨率范围
        width = max(160, min(width, 1920))
        height = max(120, min(height, 1080))
        
        try:
            import tempfile
            import base64
            
            # 获取 Scene Viewer
            viewer = None
            try:
                desktop = hou.ui.curDesktop()
                if desktop:
                    viewer = desktop.paneTabOfType(hou.paneTabType.SceneViewer)
            except Exception:
                pass
            
            if viewer is None:
                try:
                    viewer = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.SceneViewer)
                except Exception:
                    pass
            
            if viewer is None:
                return {"success": False, "error": "找不到 Scene Viewer 面板，请确保有打开的 3D 视口"}
            
            # 获取当前帧
            current_frame = int(hou.frame())
            
            # 生成临时文件路径
            tmp_dir = tempfile.gettempdir()
            tmp_file = os.path.join(tmp_dir, f"houdini_viewport_{int(time.time() * 1000)}.jpg")
            
            # 使用 flipbook 截取单帧
            try:
                flip_settings = viewer.flipbookSettings().stash()
                flip_settings.output(tmp_file)
                flip_settings.frameRange((current_frame, current_frame))
                flip_settings.resolution((width, height))
                flip_settings.outputToMPlay(False)
                
                # 执行单帧截图
                viewport = viewer.curViewport()
                viewer.flipbook(viewport, flip_settings)
            except Exception as e:
                # 某些 Houdini 版本可能不支持 flipbook API
                return {"success": False, "error": f"Flipbook 截图失败: {e}"}
            
            # 读取生成的图片
            if not os.path.exists(tmp_file):
                # flipbook 可能使用帧号作为文件名后缀
                import glob
                pattern = tmp_file.replace('.jpg', '*.jpg')
                candidates = sorted(glob.glob(pattern))
                if candidates:
                    tmp_file = candidates[0]
                else:
                    return {"success": False, "error": "截图文件未生成，请检查视口状态"}
            
            # 读取并编码
            with open(tmp_file, 'rb') as f:
                img_bytes = f.read()
            
            if len(img_bytes) == 0:
                return {"success": False, "error": "截图文件为空"}
            
            b64_data = base64.b64encode(img_bytes).decode('utf-8')
            
            # 清理临时文件
            try:
                os.remove(tmp_file)
            except Exception:
                pass
            
            # 获取视口信息
            viewport_name = ""
            try:
                viewport_name = viewer.curViewport().name()
            except Exception:
                pass
            
            cam_info = ""
            try:
                vp = viewer.curViewport()
                cam = vp.camera()
                if cam:
                    cam_info = f", camera={cam.path()}"
            except Exception:
                pass
            
            size_kb = len(img_bytes) / 1024
            
            result_msg = (
                f"已截取视口快照: {width}x{height}, frame={current_frame}, "
                f"viewport={viewport_name}{cam_info}, "
                f"size={size_kb:.1f}KB"
            )
            
            # 如果指定了 output_path，保存到文件
            if output_path:
                try:
                    # 支持 $HIP 等 Houdini 变量展开
                    expanded_path = hou.text.expandString(output_path) if hasattr(hou, 'text') else output_path
                    save_dir = os.path.dirname(expanded_path)
                    if save_dir and not os.path.exists(save_dir):
                        os.makedirs(save_dir, exist_ok=True)
                    with open(expanded_path, 'wb') as f:
                        f.write(img_bytes)
                    result_msg += f"\n截图已保存到: {expanded_path}"
                except Exception as e:
                    result_msg += f"\n保存到 {output_path} 失败: {e}"
            
            return {
                "success": True,
                "result": result_msg,
                # ★ 特殊字段：包含 base64 图片数据，
                # agent_loop_stream 中检测到此字段会将图片注入消息
                "_viewport_image": b64_data,
                "_image_media_type": "image/jpeg",
            }
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "error": f"视口截图失败: {str(e)}"}

    def _tool_unknown(self, tool_name: str) -> Dict[str, Any]:
        """处理未知工具名称，提供建议"""
        available = list(self._TOOL_DISPATCH.keys())
        error_msg = f"工具不存在: {tool_name}"
        similar = [t for t in available
                   if tool_name.lower() in t.lower() or t.lower() in tool_name.lower()]
        if similar:
            error_msg += f"\n建议的工具: {', '.join(similar[:3])}"
        else:
            error_msg += f"\n可用工具: {', '.join(available[:8])}..."
        error_msg += f"\n请使用正确的工具名称，不要重复调用不存在的工具。"
        return {"success": False, "error": error_msg}


    # ========================================
    # 内部辅助方法
    # ========================================

    def _place_new_node(self, new_node: Any, network: Any) -> None:
        """为新建节点选择合适的位置。

        moveToGoodPosition() 会依据输入/输出连接放置节点；若新节点没有连接，
        Houdini 会把它丢到网络里"看起来合适"的空白区（往往远离用户当前关注的
        区域）。为贴合用户在网络编辑器里的实际操作位置，改用以下锚点优先级：

        1. 有输入/输出连接 → 交给 moveToGoodPosition()（沿用连接节点排布）。
        2. 用户在同一父网络里选中的节点 → 放到其右下方。
        3. 网络编辑器当前视口的可见中心 → 放到视口中心。
        4. 都拿不到 → 回退 moveToGoodPosition()。
        """
        try:
            has_connection = any(inp is not None for inp in (new_node.inputs() or []))
            if not has_connection:
                has_connection = any(out is not None for out in (new_node.outputs() or []))
        except Exception:
            has_connection = False

        if has_connection:
            try:
                new_node.moveToGoodPosition()
            except Exception:
                pass
            return

        # 锚点 2：用户预先选中的同父网络节点（排除刚创建的这个）
        try:
            selected = [
                n for n in hou.selectedNodes()
                if n is not None and n != new_node and n.parent() == network
            ]
        except Exception:
            selected = []
        if selected:
            try:
                anchor = selected[-1]
                pos = anchor.position()
                new_node.setPosition(hou.Vector2(pos[0] + 1.5, pos[1] - 1.0))
                return
            except Exception:
                pass

        # 锚点 3：网络编辑器当前视口可见中心
        try:
            editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor and editor.pwd() == network:
                bounds = editor.visibleBounds()
                center = bounds.center()
                new_node.setPosition(hou.Vector2(center[0], center[1]))
                return
        except Exception:
            pass

        # 锚点 4：回退原生布局
        try:
            new_node.moveToGoodPosition()
        except Exception:
            pass

    def _current_network(self) -> Any:
        """获取当前网络编辑器中的网络
        
        优先级: 当前编辑器 > /obj/geo1 > /obj
        使用回退路径时会打印警告。
        """
        try:
            editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
            if editor:
                network = editor.pwd()
                if network:
                    return network
            # 回退到 /obj/geo1
            try:
                geo1 = hou.node('/obj/geo1')
                if geo1:
                    print("[MCP Client] ⚠️ 未找到活动网络编辑器，回退到 /obj/geo1")
                    return geo1
            except Exception:
                pass
            # 回退到 /obj
            try:
                obj = hou.node('/obj')
                if obj:
                    print("[MCP Client] ⚠️ 未找到活动网络编辑器，回退到 /obj")
                    return obj
            except Exception:
                pass
            return None
        except Exception as e:
            print(f"[MCP Client] _current_network 异常: {e}")
            try:
                geo1 = hou.node('/obj/geo1')
                if geo1:
                    return geo1
            except Exception:
                pass
            try:
                return hou.node('/obj')
            except Exception:
                return None

    def _category_from_hint(self, prefix: str) -> Any:
        """从前缀获取类别"""
        try:
            prefix_lower = (prefix or '').strip().lower()
            for name, category in hou.nodeTypeCategories().items():
                if name.lower() == prefix_lower:
                    return category
        except Exception:
            pass
        return None

    def _desired_category_from_hint(self, type_hint: str, network: Any) -> Any:
        """从类型提示获取期望的类别"""
        try:
            if "/" in (type_hint or ''):
                prefix = type_hint.split("/", 1)[0]
                return self._category_from_hint(prefix) or (network.childTypeCategory() if network else None)
            
            # 如果没有前缀，尝试根据节点名推断类别（常见SOP节点）
            hint_lower = (type_hint or '').lower().strip()
            common_sop_nodes = {
                'box', 'sphere', 'grid', 'tube', 'line', 'circle', 'font', 'curve',
                'noise', 'mountain', 'attribnoise', 'scatter', 'copytopoints', 
                'attribwrangle', 'pointwrangle', 'primitivewrangle', 'volumewrangle',
                'delete', 'blast', 'fuse', 'transform', 'subdivide', 'remesh',
                'polyextrude', 'smooth', 'relax', 'bend', 'twist', 'mountain',
                'add', 'merge', 'connect', 'group', 'partition'
            }
            if hint_lower in common_sop_nodes:
                # 这是一个SOP节点
                return hou.sopNodeTypeCategory()
            
            # 默认使用当前网络的类别
            return network.childTypeCategory() if network else None
        except Exception:
            return None

    def _ensure_target_network(self, network: Any, desired_category: Any) -> Any:
        """确保目标网络类型正确"""
        if network is None or desired_category is None:
            return network
            
        try:
            current_cat = network.childTypeCategory() if network else None
            if current_cat is None:
                return network
                
            # 如果类别匹配，直接返回
            if current_cat == desired_category:
                return network
            
            current_name = (current_cat.name().lower() if current_cat else "")
            desired_name = (desired_category.name().lower() if desired_category else "")
            
            if current_name == desired_name:
                return network
            
            # 如果在 obj 层级但需要创建 sop 节点，自动创建 geo 容器
            if current_name.startswith("object") and desired_name.startswith("sop"):
                try:
                    print(f"[MCP Client] 自动创建 geo 容器，从 {current_name} 到 {desired_name}")
                    # run_init_scripts=False：不运行 OnCreated 防止递归调用崩溃
                    # geo 容器只需要空壳，不需要默认 file1 节点
                    container = network.createNode(
                        "geo",
                        None,  # 让 Houdini 自动生成名称
                        run_init_scripts=False,
                        load_contents=False,
                        exact_type_name=True,
                    )
                    if container:
                        container.moveToGoodPosition()
                        print(f"[MCP Client] 成功创建 geo 容器: {container.path()}")
                        return container
                    else:
                        print(f"[MCP Client] 创建 geo 容器失败: 返回 None")
                        return network
                except Exception as e:
                    print(f"[MCP Client] 创建 geo 容器异常: {e}")
                    import traceback
                    traceback.print_exc()
                    return network
        except Exception as e:
            print(f"[MCP Client] _ensure_target_network 异常: {e}")
            import traceback
            traceback.print_exc()
        return network

    def _sanitize_node_name(self, name: Optional[str]) -> Optional[str]:
        """清理节点名称"""
        if not name:
            return None
        cleaned = str(name).strip()
        if not cleaned:
            return None
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", cleaned)
        cleaned = cleaned.strip("_") or None
        return cleaned

    # ========================================
    # Houdini 本地帮助文档查询
    # ========================================
    
    # Houdini nodeTypeCategories() 的 key 与 AI 传入的 category 映射
    _CATEGORY_MAP: Dict[str, str] = {
        "sop": "Sop", "obj": "Object", "dop": "Dop", "vop": "Vop",
        "cop": "Cop2", "cop2": "Cop2", "rop": "Driver", "driver": "Driver",
        "chop": "Chop", "shop": "Shop", "lop": "Lop", "top": "Top",
    }

    def _get_houdini_local_doc(self, node_type: str, category: str = "sop", page: int = 1) -> Tuple[bool, str]:
        """获取节点文档（多重降级策略，支持分页）

        优先级：
        1. 分页缓存（之前已获取的文档直接分页返回）
        2. Houdini 本地帮助服务器（http://127.0.0.1:{port}）
        3. SideFX 在线文档（https://www.sidefx.com/docs/houdini/）
        4. hou.NodeType.description() + 参数列表 作为最低限度的文档

        Args:
            node_type: 节点类型名
            category: 节点类别
            page: 页码（从 1 开始），大于 1 时优先从缓存读取

        Returns:
            (success, doc_text)
        """
        if hou is None:
            return False, "未检测到 Houdini API"

        type_name_lower = node_type.lower().strip()

        # ---------- 分页快速路径：缓存中已有完整文档 ----------
        cache_key = f"{category}/{node_type}".lower()
        if page > 1 and cache_key in self._doc_page_cache:
            return True, self._paginate_doc(self._doc_page_cache[cache_key], node_type, category, page)

        # ---------- 查找节点类型对象 ----------
        node_type_obj = None
        try:
            categories = hou.nodeTypeCategories()
            hou_cat_name = self._CATEGORY_MAP.get(category.lower(), category.capitalize())
            cat_obj = categories.get(hou_cat_name)
            # 如果精确匹配失败，遍历所有分类
            if cat_obj is None:
                for cname, cobj in categories.items():
                    if cname.lower() == category.lower():
                        cat_obj = cobj
                        break

            if cat_obj:
                for name, nt in cat_obj.nodeTypes().items():
                    name_low = name.lower()
                    if name_low == type_name_lower or name_low.endswith(f"::{type_name_lower}"):
                        node_type_obj = nt
                        break
            # 如果指定类别未找到，搜索全部类别
            if node_type_obj is None:
                for cname, cobj in categories.items():
                    for name, nt in cobj.nodeTypes().items():
                        name_low = name.lower()
                        if name_low == type_name_lower or name_low.endswith(f"::{type_name_lower}"):
                            node_type_obj = nt
                            # 更新 category 为实际找到的
                            for k, v in self._CATEGORY_MAP.items():
                                if v == cname:
                                    category = k
                                    break
                            break
                    if node_type_obj:
                        break
        except Exception as e:
            print(f"[MCP] 查找节点类型失败: {e}")

        # ---------- 策略 1: 本地帮助服务器 ----------
        local_result = self._fetch_local_help(node_type, category, node_type_obj, page)
        if local_result is not None:
            return True, local_result

        # ---------- 策略 2: SideFX 在线文档 ----------
        online_result = self._fetch_online_help(node_type, category, page)
        if online_result is not None:
            return True, online_result

        # ---------- 策略 3: 从 hou.NodeType 提取基本信息 ----------
        if node_type_obj is not None:
            return self._extract_type_info(node_type_obj, node_type)

        # ---------- 策略 4: search_houdini_help 全文兜底 ----------
        # 前三策略全部失败（本地帮助服务器/在线/类型信息都拿不到）时，
        # 用离线手册全文检索兜底——可命中结构化索引之外的概念页/长文。
        help_result = self._fetch_help_fulltext(node_type)
        if help_result is not None:
            return True, help_result

        return False, f"找不到节点类型 '{node_type}' 的文档。请用 search_node_types 确认正确的节点名。"

    def _fetch_help_fulltext(self, node_type: str) -> Optional[str]:
        """策略 4：用 search_houdini_help skill 全文检索离线手册兜底。

        返回格式化文本，或 None（未命中/skill 不可用时降级到上层的硬失败）。
        """
        try:
            from houdini_agent.skills import run_skill
        except Exception:
            return None
        try:
            res = run_skill("search_houdini_help", {"mode": "search",
                                                    "query": node_type, "top_k": 3})
        except Exception:
            return None
        if not isinstance(res, dict) or res.get("error") or not res.get("hits"):
            return None

        lines = [f"# {node_type} — 离线手册全文检索兜底 (search_houdini_help)", ""]
        for h in res["hits"]:
            title = h.get("title", "")
            path = h.get("path", "")
            snippet = h.get("snippet", "")
            lines.append(f"## {title}  ({path})")
            if snippet:
                lines.append(snippet)
            lines.append("")
        lines.append("提示：用 run_skill('search_houdini_help', {mode:'page', path:'<上面某条 path>'}) 取完整正文。")
        return "\n".join(lines)

    # ---- 帮助文档 子方法 ----

    def _html_to_text(self, html: str) -> str:
        """将 HTML 转为可读纯文本"""
        try:
            from bs4 import BeautifulSoup as BS
            soup = BS(html, 'html.parser')
            # 移除不需要的部分
            for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer']):
                tag.decompose()
            text = soup.get_text(separator='\n', strip=True)
        except Exception:
            # 无 bs4 时用正则
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<header[^>]*>.*?</header>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
            # 块级标签换行
            text = re.sub(r'<(?:br|p|div|h[1-6]|li|tr)[^>]*>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
        # 清理多余空行
        lines = [l.strip() for l in text.split('\n')]
        lines = [l for l in lines if l]
        text = '\n'.join(lines)
        return text

    # 文档分页缓存：key = "category/node_type" → 完整纯文本
    _doc_page_cache: Dict[str, str] = {}
    _DOC_PAGE_SIZE = 2500  # 每页字符数

    def _paginate_doc(self, text: str, node_type: str, category: str, page: int = 1) -> str:
        """将文档按页返回，支持分页查看完整内容
        
        Args:
            text: 完整的纯文本文档
            node_type: 节点类型名
            category: 节点类别
            page: 页码（从 1 开始）
        """
        cache_key = f"{category}/{node_type}".lower()
        self._doc_page_cache[cache_key] = text

        total_chars = len(text)
        page_size = self._DOC_PAGE_SIZE
        total_pages = max(1, (total_chars + page_size - 1) // page_size)

        # 限制页码范围
        page = max(1, min(page, total_pages))

        start = (page - 1) * page_size
        end = min(start + page_size, total_chars)
        page_text = text[start:end]

        header = f"[{node_type} 节点文档] (第 {page}/{total_pages} 页, 共 {total_chars} 字符)\n\n"

        if total_pages == 1:
            return header + page_text
        
        if page < total_pages:
            footer = f"\n\n[第 {page}/{total_pages} 页] 还有更多内容，调用 get_houdini_node_doc(node_type=\"{node_type}\", category=\"{category}\", page={page + 1}) 查看下一页"
        else:
            footer = f"\n\n[第 {page}/{total_pages} 页 - 最后一页]"
        
        return header + page_text + footer

    def _fetch_local_help(self, node_type: str, category: str, node_type_obj, page: int = 1) -> Optional[str]:
        """从 Houdini 本地帮助服务器获取文档"""
        # 先检查分页缓存（避免重复请求）
        cache_key = f"{category}/{node_type}".lower()
        if cache_key in self._doc_page_cache and page > 1:
            return self._paginate_doc(self._doc_page_cache[cache_key], node_type, category, page)

        if not requests:
            return None
        settings = read_settings()
        help_port = getattr(settings, "help_server_port", 48626)
        help_server = f"http://127.0.0.1:{help_port}"

        # 构建 URL（优先 helpUrl，否则用标准路径）
        url_path = f"/nodes/{category.lower()}/{node_type.lower()}"
        if node_type_obj:
            try:
                help_url = node_type_obj.helpUrl()
                if help_url and not help_url.startswith(('http://', 'https://')):
                    url_path = help_url
            except Exception:
                pass
        full_url = f"{help_server}{url_path}"

        try:
            response = requests.get(full_url, timeout=5)
            if response.status_code == 200:
                text = self._html_to_text(response.text)
                if text and len(text) > 50:
                    return self._paginate_doc(text, node_type, category, page)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            pass  # 本地服务器不可用，降级到在线
        except Exception as e:
            print(f"[MCP] 本地帮助获取失败: {e}")
        return None

    def _fetch_online_help(self, node_type: str, category: str, page: int = 1) -> Optional[str]:
        """从 SideFX 在线文档获取"""
        # 先检查分页缓存
        cache_key = f"{category}/{node_type}".lower()
        if cache_key in self._doc_page_cache and page > 1:
            return self._paginate_doc(self._doc_page_cache[cache_key], node_type, category, page)

        if not requests:
            return None
        base_url = "https://www.sidefx.com/docs/houdini/"
        full_url = f"{base_url}nodes/{category.lower()}/{node_type.lower()}.html"
        try:
            response = requests.get(full_url, timeout=8)
            if response.status_code == 200:
                text = self._html_to_text(response.text)
                if text and len(text) > 50:
                    return self._paginate_doc(text, node_type, category, page)
        except Exception:
            pass
        return None

    def _extract_type_info(self, node_type_obj, node_type: str) -> Tuple[bool, str]:
        """从 hou.NodeType 对象提取基本文档信息（最后降级）"""
        try:
            label = node_type_obj.description() or node_type
            # 输入信息
            inputs = []
            try:
                input_labels = node_type_obj.inputLabels()
                for i, lbl in enumerate(input_labels):
                    inputs.append(f"  输入 {i}: {lbl}")
            except Exception:
                pass
            # 参数摘要（前 40 个，与 get_node_card 的 max_parms=40 对齐）
            parms = []
            total_parms = 0
            try:
                parm_templates = node_type_obj.parmTemplates()
                total_parms = len(parm_templates)
                for pt in parm_templates[:40]:
                    parms.append(f"  {pt.name()}: {pt.label()} ({pt.type().name()})")
            except Exception:
                pass

            doc = [f"[{node_type} 节点基本信息]", f"名称: {label}"]
            if inputs:
                doc.append("输入端口:\n" + '\n'.join(inputs))
            if parms:
                shown = min(40, len(parms))
                doc.append(f"参数 (前{shown}个):\n" + '\n'.join(parms))
                if total_parms > shown:
                    doc.append(
                        f"\n⚠️ 本节点类型共有 {total_parms} 个参数，此处仅显示前 {shown} 个。"
                        f"\n完整参数列表请用：get_node_card(node_type=\"{node_type}\", max_parms={total_parms})"
                        f" 或对已建节点用 get_parameter_schema(node_path=\"...\") 查看（支持 offset 翻页）。"
                    )
            return True, '\n'.join(doc)
        except Exception as e:
            return False, f"提取节点信息失败: {e}"
    
    # 常见节点输入说明（从外部 JSON 加载，避免硬编码）
    # ========================================
    _COMMON_NODE_INPUTS: Dict[str, str] = {}

    @classmethod
    def _load_common_node_inputs(cls) -> Dict[str, str]:
        """从 node_inputs.json 懒加载常见节点输入信息"""
        if cls._COMMON_NODE_INPUTS:
            return cls._COMMON_NODE_INPUTS
        json_path = os.path.join(os.path.dirname(__file__), 'node_inputs.json')
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                cls._COMMON_NODE_INPUTS = json.load(f)
            print(f"[MCP Client] 已加载 {len(cls._COMMON_NODE_INPUTS)} 个节点输入信息")
        except FileNotFoundError:
            print(f"[MCP Client] ⚠️ 未找到 node_inputs.json: {json_path}")
        except Exception as e:
            print(f"[MCP Client] ⚠️ 加载 node_inputs.json 失败: {e}")
        return cls._COMMON_NODE_INPUTS

    def get_node_input_info(self, node_type: str, category: str = "sop") -> Tuple[bool, str]:
        """获取节点的输入端口信息（使用缓存，重要：帮助 AI 理解输入顺序）
        
        Args:
            node_type: 节点类型名称
            category: 节点类别
        
        Returns:
            (success, info) 输入端口信息
        """
        type_lower = node_type.lower()
        cache_key = f"{category}/{type_lower}"
        
        # 检查常见节点缓存（从 JSON 懒加载）
        common_inputs = self._load_common_node_inputs()
        if type_lower in common_inputs:
            return True, common_inputs[type_lower]
        
        # 检查动态缓存
        if cache_key in HoudiniMCP._common_node_inputs_cache:
            return True, HoudiniMCP._common_node_inputs_cache[cache_key]
        
        if hou is None:
            return False, "未检测到 Houdini API"
        
        try:
            # 获取节点类型
            categories = hou.nodeTypeCategories()
            cat_obj = categories.get(category.capitalize()) or categories.get(category.upper())
            if not cat_obj:
                return False, f"未找到类别: {category}"
            
            node_type_obj = None
            for name, nt in cat_obj.nodeTypes().items():
                if name.lower() == type_lower or name.lower().endswith(f"::{type_lower}"):
                    node_type_obj = nt
                    break
            
            if not node_type_obj:
                return False, f"未找到节点类型: {node_type}"
            
            # 获取输入信息
            max_inputs = node_type_obj.maxNumInputs()
            min_inputs = node_type_obj.minNumInputs()
            
            info_lines = [
                f"节点: {node_type} ({node_type_obj.description()})",
                f"输入端口数量: {min_inputs}-{max_inputs}",
                "",
                "输入端口详情:"
            ]
            
            for i in range(min(max_inputs, 6)):
                try:
                    label = node_type_obj.inputLabel(i)
                    required = i < min_inputs
                    req_str = "必需" if required else "可选"
                    info_lines.append(f"  [{i}] {label} ({req_str})")
                except Exception:
                    info_lines.append(f"  [{i}] Input {i}")
            
            result = "\n".join(info_lines)
            
            # 缓存结果
            HoudiniMCP._common_node_inputs_cache[cache_key] = result
            
            return True, result
            
        except Exception as e:
            return False, f"获取输入信息失败: {str(e)}"