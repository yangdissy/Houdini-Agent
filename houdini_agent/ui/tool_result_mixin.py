# -*- coding: utf-8 -*-
"""Tool result rendering, VEX previews, node operation cards, and shell widgets."""

import json
import re

from houdini_agent.qt_compat import QtCore, invoke_on_main
from houdini_agent.ui.cursor_chat_widgets import (
    NodeOperationLabel,
    StreamingCodePreview,
)
from houdini_agent.ui.cursor_rich_content import (
    PythonShellWidget,
    SystemShellWidget,
)
from houdini_agent.ui.i18n import tr


class ToolResultMixin:
    def _add_tool_result(self, name: str, result: dict, arguments: dict = None):
        """添加工具结果到执行流程（自动压缩长结果）"""
        result_text = str(result.get('result', result.get('error', '')))
        success = result.get('success', True)
        
        # ★ 从工具结果和参数中提取节点路径，用于后处理裸节点名
        self._collect_node_paths_from_tool(result, arguments)
        
        # 压缩工具结果以节省 token（如果结果很长）
        if self._auto_optimize and len(result_text) > 300:
            compressed_summary = self.token_optimizer.compress_tool_result(result, max_length=200)
            # 在历史中使用压缩版本，但 UI 中显示完整版本
            # 注意：这里只影响显示，实际保存到历史时会使用压缩版本
        
        # === execute_python 专用展示 ===
        if name == 'execute_python' and arguments:
            code = arguments.get('code', '')
            if code:
                shell_data = {
                    'code': code,
                    'output': result.get('result', ''),
                    'error': result.get('error', ''),
                    'success': success,
                }
                self._addPythonShell.emit(code, json.dumps(shell_data))
                # 同时设置 ToolCallItem 结果
                short = f"[ok] Python ({len(code.splitlines())} lines)" if success else f"[err] {result_text[:50]}"
                invoke_on_main(self, "_add_tool_result_ui", name, short)
                # ★ 如果 execute_python 导致了节点变更，额外生成 checkpoint
                if result.get('_node_changes'):
                    self._addNodeOperation.emit(name, result)
                return
        
        # === execute_shell 专用展示 ===
        if name == 'execute_shell' and arguments:
            command = arguments.get('command', '')
            if command:
                shell_data = {
                    'command': command,
                    'output': result.get('result', ''),
                    'error': result.get('error', ''),
                    'success': success,
                    'cwd': arguments.get('cwd', ''),
                }
                self._addSystemShell.emit(command, json.dumps(shell_data))
                short = f"[ok] $ {command[:40]}" if success else f"[err] {result_text[:50]}"
                invoke_on_main(self, "_add_tool_result_ui", name, short)
                return
        
        # ★ 通用节点变更检测：任何工具如果通过 before/after 快照检测到节点变更，生成 checkpoint
        if result.get('_node_changes') and result.get('success'):
            self._addNodeOperation.emit(name, result)
        
        # 检查是否是节点操作，需要高亮显示
        # 但如果是失败的操作，也要显示错误信息
        if name in ('create_node', 'create_nodes_batch', 'create_wrangle_node', 'delete_node', 'set_node_parameter'):
            if result.get('success'):
                # 成功时使用节点操作标签（直接传 dict，避免 JSON 序列化开销）
                self._addNodeOperation.emit(name, result)
                # 同时设置 ToolCallItem 结果（折叠式，可展开查看完整内容）
                invoke_on_main(self, "_add_tool_result_ui", name, f"[ok] {result_text}")
                return
            else:
                # 失败时也结束流式预览
                if name in self._VEX_TOOLS:
                    self._finalize_streaming_preview()
                # 失败时显示错误信息（继续下面的逻辑）
                pass
        
        # 添加到执行流程（CollapsibleSection 风格，点击展开查看完整结果）
        if self._agent_response or self._current_response:
            prefix = "[err]" if not success else "[ok]"
            if not success:
                self._addStatus.emit(
                    f"恢复建议: {name} 执行失败，可点 Policy 按钮查看时间线并切换 Plan/Ask。"
                )
            invoke_on_main(self, "_add_tool_result_ui", name, f"{prefix} {result_text}")
    
    @QtCore.Slot(str, str)
    def _add_tool_result_ui(self, name: str, result: str):
        """在 UI 线程中添加工具结果"""
        try:
            resp = self._agent_response or self._current_response
            if resp:
                resp.add_tool_result(name, result)
        except RuntimeError:
            pass  # widget 已被 clear 销毁

    @QtCore.Slot(str, str)
    def _add_collapsible_result(self, name: str, result: str):
        resp = self._agent_response or self._current_response
        if resp:
            resp.add_collapsible(f"Result: {name}", result)

    @staticmethod
    def _extract_node_paths(text: str, tool_name: str = '') -> list:
        """从工具返回的结果文本中提取 **实际操作** 的节点路径
        
        只提取真正被创建/删除的节点路径，忽略上下文信息
        （父网络、输入/输出连接等附属路径）。
        
        各工具的返回格式:
        - create_node:      "✓/obj/geo1/scatter1 (父网络: /obj/geo1, ...)"
        - create_nodes_batch:"已创建 3 个节点: /obj/geo1/a, /obj/geo1/b, /obj/geo1/c"
        - create_wrangle_node:"已创建 Wrangle 节点: /obj/geo1/attribwrangle1"
        - delete_node:      "已删除节点: /obj/geo1/scatter1 (父网络: ...)"
        """
        import re
        _PATH_RE = r'(/(?:obj|out|ch|shop|stage|mat|tasks)[/\w]*)'
        
        if tool_name == 'create_node':
            # 格式: "✓/obj/geo1/scatter1 (父网络: /obj/geo1, ...)"
            # 只取 ✓ 后面的第一个路径
            m = re.match(r'[✓\s]*' + _PATH_RE, text)
            return [m.group(1)] if m else []
        
        if tool_name == 'delete_node':
            # 格式: "已删除节点: /obj/geo1/scatter1 (父网络: ...)"
            # 只取 "已删除节点:" 后面的第一个路径
            m = re.search(r'已删除节点:\s*' + _PATH_RE, text)
            if m:
                return [m.group(1)]
            # fallback: 取文本中第一个路径
            m = re.search(_PATH_RE, text)
            return [m.group(1)] if m else []
        
        if tool_name == 'create_nodes_batch':
            # 格式: "已创建 3 个节点: /obj/geo1/a, /obj/geo1/b, /obj/geo1/c\n注意: ..."
            # 只解析 "个节点:" 后同一行内的逗号分隔路径
            m = re.search(r'个节点:\s*(.*)', text)
            if m:
                first_line = m.group(1).split('\n')[0]
                return re.findall(_PATH_RE, first_line)
            # fallback: 提取所有路径（批量创建格式未匹配时）
            return re.findall(_PATH_RE, text)
        
        if tool_name == 'create_wrangle_node':
            # 格式: "已创建 Wrangle 节点: /obj/geo1/attribwrangle1"
            m = re.search(r'节点:\s*' + _PATH_RE, text)
            return [m.group(1)] if m else []
        
        # 未知工具 → 保守策略：只取第一个路径
        m = re.search(_PATH_RE, text)
        return [m.group(1)] if m else []
    
    # ── 流式 VEX 预览 ─────────────────────────────────────
    # VEX 相关的工具名（只有这些才需要流式预览）
    _VEX_TOOLS = frozenset({'create_wrangle_node', 'set_node_parameter'})

    # 常见的 VEX/代码参数名（set_node_parameter 只有在设置这些参数时才做流式预览）
    _VEX_PARAM_NAMES = frozenset({
        'snippet', 'vex_code', 'code', 'script', 'python',
        'sopoutput', 'command', 'expr', 'expression',
    })

    @QtCore.Slot(str, str, str)
    def _on_tool_args_delta(self, tool_name: str, delta: str, accumulated: str):
        """主线程 slot：处理 tool_call 参数增量，流式预览 VEX 代码 / Plan 生成进度"""
        try:
            # ★ Plan 模式：create_plan 参数流式 → 创建/更新流式卡片
            if tool_name == 'create_plan':
                # 首次收到 create_plan 参数 → 立即创建流式卡片
                if self._streaming_plan_card is None:
                    self._on_create_streaming_plan()
                self._show_plan_generation_progress(accumulated)
                self._updateStreamingPlan.emit(accumulated)
                return

            if tool_name not in self._VEX_TOOLS:
                return

            # set_node_parameter 只对 VEX/代码参数做流式预览
            if tool_name == 'set_node_parameter':
                # 尝试从已累积的 JSON 中提取 param_name
                import re as _re
                m = _re.search(r'"param_name"\s*:\s*"([^"]*)"', accumulated)
                if m:
                    param_name = m.group(1).lower()
                    if param_name not in self._VEX_PARAM_NAMES:
                        return
                # 如果 param_name 还没出现，暂不创建预览（等到能确认是 VEX 参数再说）

            # 从不完整的 JSON 中增量提取 VEX 代码
            code = self._extract_vex_from_partial_json(tool_name, accumulated)
            if not code:
                return
            
            # 对于 set_node_parameter，只有代码超过一定长度才显示预览（避免为 "1.5" 这种值创建预览）
            if tool_name == 'set_node_parameter' and len(code) < 10 and '\n' not in code:
                return

            # 如果还没有 StreamingCodePreview，则创建
            if self._streaming_preview is None or self._streaming_preview_tool != tool_name:
                resp = self._agent_response or self._current_response
                if not resp:
                    return
                self._streaming_preview = StreamingCodePreview(tool_name, parent=resp)
                self._streaming_preview_tool = tool_name
                self._streaming_last_code = ""
                resp.details_layout.addWidget(self._streaming_preview)
                self._scroll_agent_to_bottom()

            # 更新预览（StreamingCodePreview 内部做增量追加）
            self._streaming_preview.update_code(code)
            self._streaming_last_code = code
        except RuntimeError:
            pass  # widget 已被销毁

    def _extract_vex_from_partial_json(self, tool_name: str, accumulated: str) -> str:
        """从不完整的 JSON 字符串中增量提取 VEX 代码字段
        
        create_wrangle_node → 提取 "vex_code" 字段
        set_node_parameter  → 提取 "value" 字段
        """
        import re as _re
        # 确定要提取的字段名
        if tool_name == 'create_wrangle_node':
            field_pattern = r'"vex_code"\s*:\s*"'
        else:
            field_pattern = r'"value"\s*:\s*"'

        m = _re.search(field_pattern, accumulated)
        if not m:
            return ""
        start = m.end()

        # 从 start 开始，解析 JSON 字符串内容（处理转义字符）
        result_chars = []
        i = start
        while i < len(accumulated):
            ch = accumulated[i]
            if ch == '\\' and i + 1 < len(accumulated):
                next_ch = accumulated[i + 1]
                if next_ch == 'n':
                    result_chars.append('\n')
                elif next_ch == 't':
                    result_chars.append('\t')
                elif next_ch == '"':
                    result_chars.append('"')
                elif next_ch == '\\':
                    result_chars.append('\\')
                elif next_ch == '/':
                    result_chars.append('/')
                elif next_ch == 'r':
                    result_chars.append('\r')
                else:
                    result_chars.append(next_ch)
                i += 2
            elif ch == '"':
                break  # 字符串字面量结束
            else:
                result_chars.append(ch)
                i += 1
        return ''.join(result_chars)

    def _finalize_streaming_preview(self):
        """流式预览结束：移除预览 widget（ParamDiffWidget 会接替展示正式 diff）"""
        if self._streaming_preview is not None:
            try:
                self._streaming_preview.setVisible(False)
                self._streaming_preview.deleteLater()
            except RuntimeError:
                pass
            self._streaming_preview = None
            self._streaming_preview_tool = ""
            self._streaming_last_code = ""

    @QtCore.Slot(str, str)
    def _on_add_node_operation(self, name: str, result: dict):
        """处理节点操作高亮显示"""
        try:
            # ★ 工具执行完毕 → 结束流式预览
            if name in self._VEX_TOOLS:
                self._finalize_streaming_preview()
            
            resp = self._agent_response or self._current_response
            if not resp:
                return
            
            if not isinstance(result, dict):
                result = {}
            
            label = None
            result_text = str(result.get('result', ''))
            undo_snapshot = result.get('_undo_snapshot')  # 仅 delete_node 时会有
            
            # ---- 收集路径 & 操作类型 ----
            op_type = 'create'
            paths: list = []
            
            if name == 'create_node':
                paths = self._extract_node_paths(result_text, 'create_node') or ([result_text] if result_text else [])
                label = NodeOperationLabel('create', 1, paths) if paths else None
            
            elif name in ('create_nodes_batch', 'create_wrangle_node'):
                paths = self._extract_node_paths(result_text, name) or ([result_text] if result_text else [])
                label = NodeOperationLabel('create', len(paths) or 1, paths) if paths else None
            
            elif name == 'delete_node':
                op_type = 'delete'
                paths = self._extract_node_paths(result_text, 'delete_node') or ([result_text] if result_text else [])
                label = NodeOperationLabel('delete', 1, paths) if paths else None
            
            elif name == 'set_node_parameter':
                op_type = 'modify'
                # undo_snapshot 包含 node_path, param_name, old_value, new_value
                # ★ 无 snapshot = 参数值未变化 → 不显示 checkpoint（避免用户困惑）
                if undo_snapshot:
                    node_path = undo_snapshot.get("node_path", "")
                    param_name = undo_snapshot.get("param_name", "")
                    old_val = undo_snapshot.get("old_value", "")
                    new_val = undo_snapshot.get("new_value", "")
                    paths = [node_path] if node_path else []
                    # 传 param_diff 给 NodeOperationLabel，展示红绿 diff
                    param_diff = {
                        "param_name": param_name,
                        "old_value": old_val,
                        "new_value": new_val,
                    }
                    label = NodeOperationLabel('modify', 1, paths, param_diff=param_diff) if paths else None
            
            # ★ 通用变更检测（execute_python, run_skill, copy_node 等通过 before/after 快照检测到的变更）
            node_changes = result.get('_node_changes')
            if node_changes and label is None:
                created = node_changes.get('created', [])
                deleted = node_changes.get('deleted', [])
                labels_to_add = []
                
                if created:
                    c_paths = [n['path'] for n in created]
                    op_type = 'create'
                    paths = c_paths
                    labels_to_add.append(
                        ('create', len(created), c_paths, None)
                    )
                if deleted:
                    d_paths = [n['path'] for n in deleted]
                    if not created:
                        op_type = 'delete'
                        paths = d_paths
                    labels_to_add.append(
                        ('delete', len(deleted), d_paths, None)
                    )
                
                # 为每种操作类型生成独立的 checkpoint label
                for l_op, l_count, l_paths, _ in labels_to_add:
                    l_label = NodeOperationLabel(l_op, l_count, l_paths)
                    l_label.nodeClicked.connect(self._navigate_to_node)
                    l_label.undoRequested.connect(
                        lambda _op=l_op, _paths=list(l_paths), _snap=None:
                            self._undo_node_operation(_op, _paths, _snap)
                    )
                    resp.details_layout.addWidget(l_label)
                    entry = (l_label, l_op, list(l_paths), None)
                    self._pending_ops.append(entry)
                    l_label.decided.connect(self._update_batch_bar)
                
                if labels_to_add:
                    self._update_batch_bar()
                    self._scroll_agent_to_bottom()
                    return  # 已处理，跳过下面的通用逻辑
            
            if label:
                label.nodeClicked.connect(self._navigate_to_node)
                # 用 lambda 捕获当前操作的上下文，使撤销精确到这一条操作
                label.undoRequested.connect(
                    lambda _op=op_type, _paths=list(paths), _snap=undo_snapshot:
                        self._undo_node_operation(_op, _paths, _snap)
                )
                resp.details_layout.addWidget(label)
                
                # ★ 追踪未决操作 → Undo All / Keep All 按钮可见
                entry = (label, op_type, list(paths), undo_snapshot)
                self._pending_ops.append(entry)
                label.decided.connect(self._update_batch_bar)
                self._update_batch_bar()
            
            self._scroll_agent_to_bottom()
        except RuntimeError:
            pass  # widget 已被 clear 销毁
    
    def _navigate_to_node(self, node_path: str):
        """点击节点标签时，跳转到该节点并选中"""
        try:
            import hou
            node = hou.node(node_path)
            if node is None:
                self._show_toast(tr('toast.node_not_exist', node_path))
                return
            
            # 选中节点
            node.setSelected(True, clear_all_selected=True)
            
            # 在网络编辑器中跳转到该节点
            try:
                editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
                if editor:
                    # 先切换到节点的父网络
                    parent = node.parent()
                    if parent:
                        editor.cd(parent.path())
                    editor.homeToSelection()
            except Exception:
                pass
            
            # 更新节点上下文栏
            self._refresh_node_context()
            
        except ImportError:
            self._show_toast(tr('toast.houdini_unavailable'))
        except Exception as e:
            self._show_toast(tr('toast.jump_failed', e))
    
    # ----------------------------------------------------------------
    # ★ 递归恢复节点树（用于 undo delete 操作）
    # ----------------------------------------------------------------
    def _restore_node_from_snapshot(self, hou, snapshot: dict, _parent_override=None):
        """从快照递归重建节点及其整棵子节点树
        
        Args:
            hou: Houdini 模块引用
            snapshot: _snapshot_node 生成的快照字典
            _parent_override: 若不为 None，则在此节点下创建（用于递归重建子节点）
        
        Returns:
            新建的 hou.Node，或 None（失败时）
        """
        if not snapshot:
            return None
        
        parent_path = snapshot.get("parent_path", "")
        node_type = snapshot.get("node_type", "")
        node_name = snapshot.get("node_name", "")
        has_children_snapshot = bool(snapshot.get("children"))
        
        parent = _parent_override or hou.node(parent_path)
        if parent is None:
            return None
        
        # 1) 创建节点
        # ★ 如果快照中有子节点数据，必须禁止自动创建默认子节点
        #   否则 geo 等容器节点会自动生成 file1 等默认子节点，
        #   与我们递归恢复的原始子节点冲突（名称冲突/多余节点）
        try:
            if has_children_snapshot:
                new_node = parent.createNode(
                    node_type, node_name,
                    run_init_scripts=False,
                    load_contents=False,
                )
            else:
                new_node = parent.createNode(node_type, node_name)
        except Exception:
            return None
        
        # 2) 恢复位置
        pos = snapshot.get("position")
        if pos and len(pos) == 2:
            try:
                new_node.setPosition(hou.Vector2(pos[0], pos[1]))
            except Exception:
                pass
        
        # 3) 恢复参数
        for parm_name, val in snapshot.get("params", {}).items():
            try:
                parm = new_node.parm(parm_name)
                if parm is None:
                    continue
                if isinstance(val, dict) and "expr" in val:
                    lang_str = val.get("lang", "Hscript")
                    lang = (hou.exprLanguage.Python
                            if "python" in lang_str.lower()
                            else hou.exprLanguage.Hscript)
                    parm.setExpression(val["expr"], lang)
                else:
                    parm.set(val)
            except Exception:
                continue
        
        # 4) ★ 清空可能残留的默认子节点（以防万一，确保干净恢复）
        if has_children_snapshot:
            try:
                for default_child in list(new_node.children()):
                    try:
                        default_child.destroy()
                    except Exception:
                        pass
            except Exception:
                pass
        
        # 5) ★ 递归重建子节点
        children_map: dict = {}  # name → hou.Node  用于稍后恢复内部连接
        for child_snap in snapshot.get("children", []):
            child_node = self._restore_node_from_snapshot(hou, child_snap, _parent_override=new_node)
            if child_node:
                children_map[child_node.name()] = child_node
        
        # 6) ★ 恢复子节点间的内部连接
        for iconn in snapshot.get("internal_connections", []):
            try:
                src_node = children_map.get(iconn["src_name"])
                dest_node = children_map.get(iconn["dest_name"])
                if src_node and dest_node:
                    dest_node.setInput(iconn["dest_input"], src_node)
            except Exception:
                continue
        
        # 7) 恢复外部输入连接（仅顶层节点 — 子节点的外部连接由父级调用处理）
        if _parent_override is None:
            for conn in snapshot.get("input_connections", []):
                try:
                    src = hou.node(conn["source_path"])
                    if src:
                        new_node.setInput(conn["input_index"], src)
                except Exception:
                    continue
        
        # 8) 恢复外部输出连接（仅顶层节点）
        if _parent_override is None:
            for conn in snapshot.get("output_connections", []):
                try:
                    dest = hou.node(conn["dest_path"])
                    if dest:
                        dest.setInput(conn["dest_input_index"], new_node, conn.get("output_index", 0))
                except Exception:
                    continue
        
        # 9) 恢复标志位
        try:
            if snapshot.get("display_flag") and hasattr(new_node, 'setDisplayFlag'):
                new_node.setDisplayFlag(True)
            if snapshot.get("render_flag") and hasattr(new_node, 'setRenderFlag'):
                new_node.setRenderFlag(True)
        except Exception:
            pass
        
        return new_node

    def _undo_node_operation(self, op_type: str = 'create',
                              node_paths: list = None,
                              undo_snapshot: dict = None):
        """精确撤销单次节点操作
        
        - create 操作 → 删除该节点（by path）
        - delete 操作 → 从快照递归重建该节点及所有子节点
        - modify 操作 → 恢复参数旧值
        """
        try:
            import hou
        except ImportError:
            self._show_toast(tr('toast.houdini_unavailable'))
            return
        
        try:
            if op_type == 'modify' and undo_snapshot:
                # ---- 撤销参数修改 = 恢复旧值 ----
                node_path = undo_snapshot.get("node_path", "")
                param_name = undo_snapshot.get("param_name", "")
                old_value = undo_snapshot.get("old_value")
                is_tuple = undo_snapshot.get("is_tuple", False)
                
                node = hou.node(node_path)
                if node is None:
                    self._show_toast(tr('toast.node_not_found', node_path))
                    return
                
                if is_tuple:
                    parm_tuple = node.parmTuple(param_name)
                    if parm_tuple is None:
                        self._show_toast(tr('toast.param_not_found', param_name))
                        return
                    parm_tuple.set(old_value)
                else:
                    parm = node.parm(param_name)
                    if parm is None:
                        self._show_toast(tr('toast.param_not_found', param_name))
                        return
                    if isinstance(old_value, dict) and "expr" in old_value:
                        lang_str = old_value.get("lang", "Hscript")
                        lang = (hou.exprLanguage.Python
                                if "python" in lang_str.lower()
                                else hou.exprLanguage.Hscript)
                        parm.setExpression(old_value["expr"], lang)
                    else:
                        parm.set(old_value)
                
                self._show_toast(tr('toast.param_restored', param_name))
            
            elif op_type == 'create':
                # ---- 撤销创建 = 删除节点 ----
                if not node_paths:
                    self._show_toast(tr('toast.missing_path'))
                    return
                deleted = 0
                for p in node_paths:
                    node = hou.node(p)
                    if node is not None:
                        node.destroy()
                        deleted += 1
                if deleted:
                    self._show_toast(tr('toast.undo_create', deleted))
                else:
                    self._show_toast(tr('toast.node_gone'))
            
            elif op_type == 'delete' and undo_snapshot:
                # ---- 撤销删除 = 从快照递归重建整棵节点树 ----
                new_node = self._restore_node_from_snapshot(hou, undo_snapshot)
                if new_node:
                    self._show_toast(tr('toast.node_restored', new_node.path()))
                else:
                    self._show_toast(tr('toast.undo_failed', 'snapshot restore returned None'))
            
            else:
                # 回退：使用 Houdini 原生 undo
                hou.undos.performUndo()
                self._show_toast(tr('toast.undone'))
            
            self._refresh_node_context()
        
        except Exception as e:
            self._show_toast(tr('toast.undo_failed', e))

    # ---------- Undo All / Keep All 批量操作 ----------

    def _update_batch_bar(self):
        """根据未决操作数量显示/隐藏批量操作栏"""
        # 清理已决的条目（label._decided == True）
        self._pending_ops = [
            entry for entry in self._pending_ops
            if entry[0] and not entry[0]._decided
        ]
        count = len(self._pending_ops)
        if count > 0:
            self._batch_count_label.setText(f"{count} 个操作待确认")
            self._batch_bar.setVisible(True)
        else:
            self._batch_bar.setVisible(False)

    def _undo_all_ops(self):
        """撤销所有未决操作（倒序执行，后创建的先撤销）"""
        # 清理已决条目
        self._pending_ops = [
            entry for entry in self._pending_ops
            if entry[0] and not entry[0]._decided
        ]
        if not self._pending_ops:
            self._batch_bar.setVisible(False)
            return
        
        count = 0
        # 倒序：后创建的先撤销（避免依赖冲突）
        for label, op_type, paths, snapshot in reversed(self._pending_ops):
            if label._decided:
                continue
            # ★ 直接执行撤销逻辑，不通过 label._on_undo() 的信号
            #   因为 label._on_undo() 会 emit undoRequested 信号，
            #   而该信号已连接了 _undo_node_operation，会导致双重执行。
            #   这里只更新 label 的 UI 状态，然后手动执行一次撤销。
            label._decided = True
            label._undo_btn.setVisible(False)
            label._keep_btn.setVisible(False)
            label._status_label.setText(tr('status.undone'))
            label._status_label.setProperty("state", "undone")
            label._status_label.style().unpolish(label._status_label)
            label._status_label.style().polish(label._status_label)
            label._status_label.setVisible(True)
            self._undo_node_operation(op_type, paths, snapshot)
            count += 1
        
        self._pending_ops.clear()
        self._batch_bar.setVisible(False)
        if count:
            self._show_toast(f"已撤销全部 {count} 个操作")

    def _keep_all_ops(self):
        """保留所有未决操作"""
        self._pending_ops = [
            entry for entry in self._pending_ops
            if entry[0] and not entry[0]._decided
        ]
        if not self._pending_ops:
            self._batch_bar.setVisible(False)
            return
        
        count = 0
        for label, op_type, paths, snapshot in self._pending_ops:
            if label._decided:
                continue
            label._on_keep()
            label.collapse_diff()  # ★ 自动折叠 diff 展示区
            count += 1
        
        self._pending_ops.clear()
        self._batch_bar.setVisible(False)
        if count:
            self._show_toast(f"已保留全部 {count} 个操作")

    @QtCore.Slot(str, str)
    def _on_add_python_shell(self, code: str, result_json: str):
        """处理 execute_python 的专用 UI 展示"""
        try:
            resp = self._agent_response or self._current_response
            if not resp:
                return
            
            try:
                data = json.loads(result_json)
            except Exception:
                data = {}
            
            raw_output = data.get('output', '')
            error = data.get('error', '')
            success = data.get('success', True)
            
            # 从格式化的输出中提取执行时间和清理内容
            # 格式: "输出:\n...\n返回值: ...\n执行时间: 0.123s"
            exec_time = 0.0
            clean_parts = []
            
            for line in raw_output.split('\n'):
                time_match = re.match(r'^执行时间:\s*([\d.]+)s$', line.strip())
                if time_match:
                    exec_time = float(time_match.group(1))
                    continue
                # 去掉 "输出:" 前缀
                if line.strip() == '输出:':
                    continue
                clean_parts.append(line)
            
            clean_output = '\n'.join(clean_parts).strip()
            
            widget = PythonShellWidget(
                code=code,
                output=clean_output,
                error=error,
                exec_time=exec_time,
                success=success,
                parent=resp
            )
            # 放入 Python Shell 折叠区块（而非 details_layout）
            resp.add_shell_widget(widget)
            self._scroll_agent_to_bottom()
        except RuntimeError:
            pass  # widget 已被 clear 销毁

    @QtCore.Slot(str, str)
    def _on_add_system_shell(self, command: str, result_json: str):
        """处理 execute_shell 的专用 UI 展示"""
        try:
            resp = self._agent_response or self._current_response
            if not resp:
                return

            try:
                data = json.loads(result_json)
            except Exception:
                data = {}

            raw_output = data.get('output', '')
            error = data.get('error', '')
            success = data.get('success', True)
            cwd = data.get('cwd', '')

            # 从输出中提取执行时间和退出码
            exec_time = 0.0
            exit_code = 0
            stdout_parts = []

            for line in raw_output.split('\n'):
                # 匹配 "退出码: 0, 耗时: 0.123s" 或 "⛔ 命令执行失败: 退出码: 1, 耗时: ..."
                time_match = re.search(r'耗时:\s*([\d.]+)s', line)
                code_match = re.search(r'退出码:\s*(\d+)', line)
                if time_match:
                    exec_time = float(time_match.group(1))
                if code_match:
                    exit_code = int(code_match.group(1))
                if time_match or code_match:
                    continue
                # 分离 stdout / stderr
                if line.strip() == '--- stdout ---':
                    continue
                if line.strip() == '--- stderr ---':
                    continue
                stdout_parts.append(line)

            clean_output = '\n'.join(stdout_parts).strip()

            widget = SystemShellWidget(
                command=command,
                output=clean_output,
                error=error,
                exit_code=exit_code,
                exec_time=exec_time,
                success=success,
                cwd=cwd,
                parent=resp
            )
            resp.add_sys_shell_widget(widget)
            self._scroll_agent_to_bottom()
        except RuntimeError:
            pass  # widget 已被 clear 销毁

