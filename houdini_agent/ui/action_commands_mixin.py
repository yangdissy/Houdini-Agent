# -*- coding: utf-8 -*-
"""UI action commands for AITab."""

import json
from pathlib import Path

from houdini_agent.qt_compat import QtWidgets
from houdini_agent.ui.i18n import tr
from houdini_agent.ui.slash_commands import SLASH_COMMANDS_WITH_ARGS, parse_slash_command


class ActionCommandsMixin:
    def _on_stop(self):
        self.client.request_stop()

    def _request_user_switch(self):
        """触发用户切换（需要先停止当前请求）。"""
        try:
            from .login_dialog import LoginDialog
            dlg = LoginDialog(parent=self)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            new_user = dlg.get_username()
            if not new_user:
                return
            from shared.user_paths import is_user_allowed
            if not is_user_allowed(new_user):
                QtWidgets.QMessageBox.information(self, "切换用户", "当前用户未启用访问权限。")
                return
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "切换用户", f"无法打开登录窗口: {e}")
            return

        # 若正在运行，先停止
        if self._agent_session_id is not None:
            reply = QtWidgets.QMessageBox.question(
                self,
                "切换用户",
                "当前有任务正在运行。是否先停止并切换用户？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
            self._pending_user_switch = new_user
            self._on_stop()
            return

        self._perform_user_switch(new_user)

    def _perform_user_switch(self, new_user: str):
        """保存当前状态并让主窗口切换用户。"""
        try:
            self._save_all_sessions()
        except Exception:
            pass

        win = self.window()
        if hasattr(win, "switch_user"):
            win.switch_user(new_user)

    def _on_set_key(self):
        provider = self._current_provider()
        # Custom provider 使用专用配置对话框
        if provider == 'custom':
            self._open_custom_provider_dialog()
            return
        # OF3D 内置统一 key，不允许手动修改
        if provider == 'of3d':
            QtWidgets.QMessageBox.information(self, "OF3D", "OF3D 使用公司统一 API Key，已内置配置，无需手动输入。")
            return
        names = {'openai': 'OpenAI', 'deepseek': 'DeepSeek', 'glm': 'GLM（智谱AI）', 'ollama': 'Ollama', 'openrouter': 'OpenRouter', 'siliconflow': 'SiliconFlow', 'kimi_coding': 'Kimi Coding'}
        
        key, ok = QtWidgets.QInputDialog.getText(
            self, f"Set {names.get(provider, provider)} API Key",
            "Enter API Key:",
            QtWidgets.QLineEdit.Password
        )
        
        if ok and key.strip():
            self.client.set_api_key(key.strip(), persist=True, provider=provider)
            self._update_key_status()

    def _on_clear(self):
        # ── 如果当前 session 正在运行 agent，先停止 ──
        if self._agent_session_id == self._session_id and self._agent_session_id is not None:
            # 1) 请求后端线程停止
            self.client.request_stop()
            # 2) 断开 agent 对已删除 widget 的引用（防止回调访问已销毁控件）
            self._agent_response = None
            self._agent_todo_list = None
            self._agent_chat_layout = None
            self._agent_scroll_area = None
            # 3) 重置运行状态和按钮
            self._set_running(False)
        
        self._conversation_history.clear()
        self._context_summary = ""
        self._last_auto_read_context = None
        self._current_response = None
        self._token_stats = {
            'input_tokens': 0, 'output_tokens': 0,
            'reasoning_tokens': 0,
            'cache_read': 0, 'cache_write': 0,
            'total_tokens': 0, 'requests': 0,
            'estimated_cost': 0.0,
        }
        self._call_records = []
        
        # ── 清理待确认操作列表和批量操作栏 ──
        self._pending_ops.clear()
        self._batch_bar.setVisible(False)
        self._session_node_map.clear()
        
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 旧 todo_list 已被 deleteLater, 创建新的
        self.todo_list = self._create_todo_list(self.chat_container)
        if self._session_id in self._sessions:
            self._sessions[self._session_id]['todo_list'] = self.todo_list
        
        # 同步到 sessions 字典
        self._save_current_session_state()
        
        # ★ 清空后删除磁盘上的旧 session 文件（防止残留数据在重启后被恢复）
        try:
            old_session_file = self._cache_dir / f"session_{self._session_id}.json"
            if old_session_file.exists():
                old_session_file.unlink()
        except Exception:
            pass
        # ★ 立即更新 manifest（移除已清空的会话条目）
        try:
            self._update_manifest()
        except Exception:
            pass
        
        # 重置标签名
        for i in range(self.session_tabs.count()):
            if self.session_tabs.tabData(i) == self._session_id:
                self.session_tabs.setTabText(i, f"Chat {self._session_counter}")
                break
        
        # 更新统计显示
        self._update_token_stats_display()
        self._update_context_stats()

    # ============================================================
    # ★ 斜杠命令执行
    # ============================================================

    @staticmethod
    def _parse_slash_command(text: str):
        return parse_slash_command(text)

    def _execute_slash_command(self, command: str, args: str = ""):
        """执行斜杠命令 — 由 InputAreaMixin._on_slash_command_selected 调用"""
        handler = getattr(self, f'_slash_{command}', None)
        if handler:
            if command in SLASH_COMMANDS_WITH_ARGS:
                handler(args)
            else:
                handler()
            return True
        else:
            print(f"[SlashCommand] 未知命令: /{command}")
            return False

    def _slash_clear(self):
        """/ clear — 清空当前对话"""
        self._on_clear()

    def _slash_new(self):
        """/new — 新建会话"""
        self._new_session()

    def _slash_memory(self):
        """/memory — 显示记忆系统状态"""
        from ..utils.memory_store import get_memory_store, ABSTRACTION_LEVELS, MEMORY_CATEGORIES
        try:
            store = get_memory_store(self._username)
            stats = store.get_stats()
            core_mems = store.get_core_memories(max_count=10)

            lines = ["📊 **长期记忆系统状态**\n"]
            lines.append(f"- 情景记忆 (Episodic): {stats.get('episodic_count', 0)} 条")
            lines.append(f"- 语义记忆 (Semantic): {stats.get('semantic_count', 0)} 条")
            lines.append(f"- 策略记忆 (Procedural): {stats.get('procedural_count', 0)} 条")
            lines.append(f"- 嵌入后端: {stats.get('backend', 'unknown')}")
            lines.append(f"- 向量维度: {stats.get('embedding_dim', 0)}")

            if core_mems:
                lines.append(f"\n🧠 **核心记忆 (L0)** — {len(core_mems)} 条:")
                for i, mem in enumerate(core_mems, 1):
                    conf = f"(conf={mem.confidence:.2f})" if hasattr(mem, 'confidence') else ""
                    lines.append(f"  {i}. [{mem.category}] {mem.rule} {conf}")
            else:
                lines.append("\n🧠 核心记忆 (L0): 暂无")

            # 显示成长指标
            if self._memory_initialized and self._growth_tracker:
                try:
                    gm = self._growth_tracker.get_growth_metrics()
                    lines.append(f"\n📈 **成长指标:**")
                    lines.append(f"  - 成功率: {gm.get('success_rate', 0):.1%}")
                    lines.append(f"  - 错误率: {gm.get('error_rate', 0):.1%}")
                    lines.append(f"  - 成长分: {gm.get('growth_score', 0):.2f}")
                    lines.append(f"  - 任务数: {gm.get('total_tasks', 0)}")
                except Exception:
                    pass

            content = "\n".join(lines)
            self._add_user_message("[/memory]")
            resp = self._add_ai_response()
            resp.set_content(content)
            resp.finalize()
        except Exception as e:
            self._add_user_message("[/memory]")
            resp = self._add_ai_response()
            resp.set_content(f"❌ 记忆系统未就绪: {e}")
            resp.finalize()

    def _slash_command_reply(self, command_text: str, content: str):
        self._add_user_message(command_text)
        resp = self._add_ai_response()
        resp.set_content(content)
        resp.finalize()

    def _slash_remember(self, args=""):
        """/remember — 引导用户写入高优先级核心记忆（每轮对话都会注入）。"""
        from ..utils.explicit_memory import remember_explicit_memory

        text = (args or "").strip()
        # 无参数（从菜单选中）时弹引导对话框；手动输入 `/remember 文本` 直发时跳过。
        if not text:
            text, ok = QtWidgets.QInputDialog.getMultiLineText(
                self,
                "写入核心记忆",
                "输入要让 AI 长期遵守的核心内容（每轮对话都会生效）：\n"
                "例如：始终用中文注释 / 本项目 solver 命名用 sim_ 前缀 / 我偏好 VEX 而非节点",
                "",
            )
            if not ok:
                return
            text = (text or "").strip()
            if not text:
                self._slash_command_reply("[/remember]", "未输入内容，未保存核心记忆。")
                return

        result = remember_explicit_memory(self._username, text)
        if result.status == "created":
            self._slash_command_reply(
                f"[/remember] {text}",
                f"✅ 已写入核心记忆（优先级高于自动记忆，每轮对话都会生效）: {text}\n"
                f"ID: `{result.memory_id}`\n可在 `/memory` 查看、`/memories` 管理。",
            )
            return
        if result.status == "already_exists":
            self._slash_command_reply(
                f"[/remember] {text}",
                f"ℹ️ 该核心记忆已存在: {text}\nID: `{result.memory_id}`",
            )
            return
        prefix = "⚠️" if result.status == "rejected" else "❌"
        self._slash_command_reply(
            f"[/remember] {text}",
            f"{prefix} {result.message or '未保存核心记忆。'}",
        )

    def _slash_forget(self, args=""):
        """/forget — 搜索并删除记忆"""
        from ..utils.memory_store import get_memory_store

        keyword = (args or "").strip()
        if not keyword:
            self._slash_command_reply("[/forget]", "用法：`/forget <关键词>`")
            return

        try:
            store = get_memory_store(self._username)
            results = store.search_all_levels(
                query=keyword, top_k=5, min_confidence=0.0
            )
            if not results:
                self._slash_command_reply(f"[/forget] {keyword}", "未找到匹配的记忆。")
                return

            # 显示找到的记忆，让用户选择删除
            items = []
            for rec, score in results:
                display = f"[L{rec.abstraction_level}][{rec.category}] {rec.rule[:60]} (conf={rec.confidence:.2f})"
                items.append((rec.id, display))

            choices = [d for _, d in items]
            choice, ok2 = QtWidgets.QInputDialog.getItem(
                self, "选择要删除的记忆", "找到以下匹配记忆:", choices, 0, False
            )
            if not ok2:
                return

            idx = choices.index(choice)
            del_id = items[idx][0]
            store.delete_semantic(del_id)
            self._slash_command_reply(f"[/forget] {keyword}", f"🗑 已删除记忆: {choice}")
        except Exception as e:
            self._slash_command_reply("[/forget]", f"❌ 操作失败: {e}")

    def _slash_search_mem(self, args=""):
        """/search_mem — 搜索长期记忆"""
        from ..utils.memory_store import get_memory_store, ABSTRACTION_LEVELS

        keyword = (args or "").strip()
        if not keyword:
            self._slash_command_reply("[/search_mem]", "用法：`/search_mem <关键词>`")
            return

        try:
            store = get_memory_store(self._username)
            results = store.search_all_levels(
                query=keyword, top_k=10, min_confidence=0.0
            )

            if not results:
                self._slash_command_reply(f"[/search_mem] {keyword}", "未找到相关记忆。")
                return
            lines = [f"🔍 **搜索结果** — 关键词: `{keyword}`  ({len(results)} 条)\n"]
            for i, (rec, score) in enumerate(results, 1):
                level_name = ABSTRACTION_LEVELS.get(rec.abstraction_level, "unknown")
                lines.append(
                    f"{i}. **[L{rec.abstraction_level} {level_name}]** [{rec.category}] "
                    f"conf={rec.confidence:.2f}  rel={score:.3f}\n"
                    f"   {rec.rule}"
                )
            self._slash_command_reply(f"[/search_mem] {keyword}", "\n".join(lines))
        except Exception as e:
            self._slash_command_reply("[/search_mem]", f"❌ 搜索失败: {e}")

    def _slash_memories(self):
        """/memories — 打开记忆库管理窗口（情景 / 语义 / 策略 增删改查）"""
        try:
            from .memory_manager_dialog import MemoryManagerDialog
            # 直接 exec_，避免依赖 staticmethod exec_centered（旧版模块或热加载缺该方法时会报错）
            MemoryManagerDialog(self, username=self._username).exec_()
        except Exception as e:
            # 不在此处二次 import MemoryMgrSheet：模块未加载全或热加载残留时会再触发 ImportError
            QtWidgets.QMessageBox.critical(
                None,
                tr('memory_mgr.title'),
                f"{tr('memory_mgr.err_load')}\n{e}",
            )

    def _slash_network(self):
        """/network — 读取网络结构"""
        self._on_read_network()

    def _slash_selection(self):
        """/selection — 读取选中节点"""
        self._on_read_selection()

    def _slash_skills(self):
        """/skills — 列出所有技能"""
        result = self.mcp._tool_list_skills({})
        self._add_user_message("[/skills]")
        resp = self._add_ai_response()
        if result.get('success'):
            resp.set_content(result.get('result', '无可用 Skill'))
        else:
            resp.set_content(f"❌ {result.get('error', '未知错误')}")
        resp.finalize()

    def _slash_status(self):
        """/status — 显示系统综合状态"""
        lines = ["📊 **系统状态概览**\n"]

        # 上下文统计
        token_stats = self._token_stats
        lines.append("**Token 统计:**")
        lines.append(f"  - 输入: {token_stats.get('input_tokens', 0):,}")
        lines.append(f"  - 输出: {token_stats.get('output_tokens', 0):,}")
        lines.append(f"  - 总计: {token_stats.get('total_tokens', 0):,}")
        lines.append(f"  - 请求次数: {token_stats.get('requests', 0)}")
        cost = token_stats.get('estimated_cost', 0.0)
        if cost > 0:
            lines.append(f"  - 预估费用: ${cost:.4f}")
        lines.append(f"  - 对话轮数: {len(self._conversation_history)}")

        # 记忆统计
        if self._memory_initialized and self._memory_store:
            try:
                stats = self._memory_store.get_stats()
                lines.append(f"\n**记忆系统:**")
                lines.append(f"  - 情景: {stats.get('episodic_count', 0)}")
                lines.append(f"  - 语义: {stats.get('semantic_count', 0)}")
                lines.append(f"  - 策略: {stats.get('procedural_count', 0)}")
            except Exception:
                pass

        # 成长指标
        if self._memory_initialized and self._growth_tracker:
            try:
                gm = self._growth_tracker.get_growth_metrics()
                lines.append(f"\n**成长指标:**")
                lines.append(f"  - 成功率: {gm.get('success_rate', 0):.1%}")
                lines.append(f"  - 成长分: {gm.get('growth_score', 0):.2f}")
                lines.append(f"  - 累计任务: {gm.get('total_tasks', 0)}")
            except Exception:
                pass

        self._add_user_message("[/status]")
        resp = self._add_ai_response()
        resp.set_content("\n".join(lines))
        resp.finalize()

    def _slash_export(self):
        """/export — 导出训练数据"""
        self._on_export_training_data()

    def _slash_diagnostics(self):
        """/diagnostics — 导出策略与 Harness trace 诊断 JSON"""
        self._add_user_message("[/diagnostics]")
        self._export_diagnostics_json()

    def _slash_image(self):
        """/image — 附加图片"""
        self._on_attach_image()

    def _slash_help(self):
        """/help — 显示所有斜杠命令"""
        from .cursor_input_widgets import SLASH_COMMANDS
        from .i18n import get_language

        is_zh = (get_language() == 'zh')
        lines = ["❓ **可用斜杠命令**\n"]
        for cmd, icon, lbl_zh, lbl_en, desc_zh, desc_en, cat in SLASH_COMMANDS:
            label = lbl_zh if is_zh else lbl_en
            desc = desc_zh if is_zh else desc_en
            lines.append(f"  {icon} `/{cmd}` — {label}: {desc}")

        self._add_user_message("[/help]")
        resp = self._add_ai_response()
        resp.set_content("\n".join(lines))
        resp.finalize()

    def _on_read_network(self):
        ok, text = self.mcp.get_network_structure_text()
        if ok:
            # 添加到对话
            self._add_user_message("[Read network structure]")
            response = self._add_ai_response()
            response.add_status("Read network")
            response.add_collapsible("Network structure", text)
            response.finalize()
            self._conversation_history.append({'role': 'user', 'content': f"[Network structure]\n{text}"})
            self._update_context_stats()
            # 更新节点上下文栏
            self._refresh_node_context()
        else:
            self._add_ai_response().set_content(f"Error: {text}")

    # ============================================================
    # 图片输入支持
    # ============================================================
    # 已迁移到 ui/image_mixin.py (ImageMixin)

    def _on_read_selection(self):
        ok, text = self.mcp.describe_selection()
        if ok:
            self._add_user_message("[Read selected nodes]")
            response = self._add_ai_response()
            response.add_status("Read selection")
            response.add_collapsible("Node details", text)
            response.finalize()
            self._conversation_history.append({'role': 'user', 'content': f"[Selected nodes]\n{text}"})
            self._update_context_stats()
            # 更新节点上下文栏
            self._refresh_node_context()
        else:
            self._add_ai_response().set_content(f"Error: {text}")

    def _auto_inject_scene_read(self):
        """[主线程] 根据 auto_read_mode 自动将场景信息静默注入对话历史。

        每次 _on_send 时调用一次，不在聊天界面中显示额外卡片。
        调用方式与手动 + 菜单中的 Read Selection / Read Network 保持一致。
        """
        mode = getattr(self, '_auto_read_mode', 'sel')
        if mode == 'off':
            return
        try:
            if mode == 'sel':
                # 与 _on_read_selection 完全一致：读取所有选中节点，无数量限制
                ok, text = self.mcp.describe_selection()
                label = "Selected nodes"
            else:  # net
                # 与 _on_read_network 完全一致
                ok, text = self.mcp.get_network_structure_text()
                label = "Network structure"
            if ok and text:
                context_key = (mode, label, text)
                if getattr(self, '_last_auto_read_context', None) == context_key:
                    return
                self._last_auto_read_context = context_key
                self._conversation_history.append({
                    'role': 'user',
                    'content': f"[Auto-read: {label}]\n{text}"
                })
        except Exception:
            pass

    def _refresh_node_context(self):
        """刷新节点上下文栏（显示当前网络路径和选中节点）"""
        try:
            import hou
            # 获取当前网络编辑器的工作路径
            path = "/obj"
            editors = [p for p in hou.ui.paneTabs()
                       if p.type() == hou.paneTabType.NetworkEditor]
            if editors:
                pwd = editors[0].pwd()
                if pwd:
                    path = pwd.path()
            # 获取选中节点
            selected = [n.path() for n in hou.selectedNodes()]
            self.node_context_bar.update_context(path, selected)
        except Exception:
            self.node_context_bar.update_context("/obj")

    def _collect_scene_context(self) -> dict:
        """[主线程] 收集 Houdini 场景上下文用于自动 RAG 增强
        
        返回场景上下文 dict，传给后台线程的 _auto_rag_retrieve 使用。
        包含：当前网络路径、选中节点类型、选中节点名、更新模式。
        """
        ctx = {
            'network_path': '',
            'selected_types': [],
            'selected_names': [],
            'update_mode': '',
        }
        try:
            import hou  # type: ignore
            # 当前网络路径
            editors = [p for p in hou.ui.paneTabs()
                       if p.type() == hou.paneTabType.NetworkEditor]
            if editors:
                pwd = editors[0].pwd()
                if pwd:
                    ctx['network_path'] = pwd.path()
            # 选中节点的类型和名称
            for n in hou.selectedNodes()[:5]:  # 最多 5 个，避免过多
                ctx['selected_types'].append(n.type().name())
                ctx['selected_names'].append(n.name())
            # 当前 Houdini 更新模式
            try:
                ctx['update_mode'] = hou.updateModeSetting().name()
            except Exception:
                pass
        except Exception:
            pass
        return ctx

    def _on_create_wrangle(self, vex_code: str):
        """从代码块一键创建 Wrangle 节点"""
        result = self.mcp.execute_tool("create_wrangle_node", {"vex_code": vex_code})
        if result.get("success"):
            resp = self._add_ai_response()
            resp.set_content(f"{result.get('result', '已创建 Wrangle 节点')}")
            resp.finalize()
            self._refresh_node_context()
        else:
            resp = self._add_ai_response()
            resp.set_content(f"错误: {result.get('error', '创建 Wrangle 失败')}")
            resp.finalize()

    def _on_export_training_data(self):
        """导出当前对话为训练数据"""
        if not self._conversation_history:
            QtWidgets.QMessageBox.warning(self, "导出失败", "当前没有对话记录可导出")
            return
        
        # 统计对话信息
        user_count = sum(1 for m in self._conversation_history if m.get('role') == 'user')
        assistant_count = sum(1 for m in self._conversation_history if m.get('role') == 'assistant')
        
        if user_count == 0:
            QtWidgets.QMessageBox.warning(self, "导出失败", "对话中没有用户消息")
            return
        
        # 询问导出选项
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle("导出训练数据")
        msg_box.setText(f"当前对话包含 {user_count} 条用户消息，{assistant_count} 条 AI 回复。\n\n选择导出方式：")
        msg_box.setInformativeText(
            "• 分割模式：每轮对话生成一个训练样本（推荐，样本更多）\n"
            "• 完整模式：整个对话作为一个训练样本"
        )
        
        split_btn = msg_box.addButton("分割模式", QtWidgets.QMessageBox.ActionRole)
        full_btn = msg_box.addButton("完整模式", QtWidgets.QMessageBox.ActionRole)
        cancel_btn = msg_box.addButton("取消", QtWidgets.QMessageBox.RejectRole)
        
        msg_box.exec_()
        
        clicked = msg_box.clickedButton()
        if clicked == cancel_btn:
            return
        
        split_by_user = (clicked == split_btn)
        
        # 导出
        try:
            from ..utils.training_data_exporter import ChatTrainingExporter
            
            exporter = ChatTrainingExporter()
            filepath = exporter.export_conversation(
                self._conversation_history,
                system_prompt=self._system_prompt,
                split_by_user=split_by_user
            )
            
            # 显示成功消息
            response = self._add_ai_response()
            response.add_status("训练数据已导出")
            
            # 读取生成的样本数
            sample_count = 0
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    sample_count = sum(1 for _ in f)
            except:
                pass
            
            response.set_content(
                f"成功导出训练数据！\n\n"
                f"文件: {filepath}\n"
                f"训练样本数: {sample_count}\n"
                f"对话轮数: {user_count}\n"
                f"导出模式: {'分割模式' if split_by_user else '完整模式'}\n\n"
                f"提示: 文件为 JSONL 格式，可直接用于 OpenAI/DeepSeek 微调"
            )
            response.finalize()
            
            # 询问是否打开文件夹
            reply = QtWidgets.QMessageBox.question(
                self, 
                "导出成功",
                f"已生成 {sample_count} 个训练样本\n\n是否打开所在文件夹？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            
            if reply == QtWidgets.QMessageBox.Yes:
                import os
                import subprocess
                folder = os.path.dirname(filepath)
                if os.name == 'nt':  # Windows
                    os.startfile(folder)
                else:  # macOS/Linux
                    subprocess.run(['open' if 'darwin' in __import__('sys').platform else 'xdg-open', folder])
        
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "导出错误", f"导出训练数据时发生错误：{str(e)}")

    # ===== 缓存管理 =====
    
