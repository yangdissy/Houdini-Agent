# -*- coding: utf-8 -*-
"""Cache persistence and history rendering helpers for AITab."""

import json
from datetime import datetime
from pathlib import Path

from houdini_agent.core.cache_records import (
    SessionCacheRecord,
    build_session_cache_record,
)
from houdini_agent.core.session_state import SessionState
from houdini_agent.core.workspace_persistence import (
    active_session_id,
    atomic_write_json,
    load_restore_plan,
    replace_file,
    save_workspace,
    write_manifest,
)
from houdini_agent.qt_compat import QtCore, QtGui, QtWidgets


class CacheMixin:
    def _on_cache_menu(self):
        """显示缓存菜单"""
        menu = QtWidgets.QMenu(self)
        
        # 保存存档（独立文件）
        archive_action = menu.addAction("存档当前对话")
        archive_action.triggered.connect(self._archive_cache)
        
        # 加载对话
        load_action = menu.addAction("加载对话...")
        load_action.triggered.connect(self._load_cache_dialog)
        
        menu.addSeparator()
        
        # 压缩为摘要（减少 token）
        compress_action = menu.addAction("压缩旧对话为摘要")
        compress_action.triggered.connect(self._compress_to_summary)
        
        # 列出所有缓存
        list_action = menu.addAction("查看所有缓存")
        list_action.triggered.connect(self._list_caches)
        
        menu.addSeparator()
        
        # 自动保存开关
        auto_save_action = menu.addAction("[on] 自动保存" if self._auto_save_cache else "自动保存")
        auto_save_action.setCheckable(True)
        auto_save_action.setChecked(self._auto_save_cache)
        auto_save_action.triggered.connect(lambda: setattr(self, '_auto_save_cache', not self._auto_save_cache))
        
        # 显示菜单（btn_cache 是隐藏控件，用鼠标位置避免弹到屏幕最左边）
        menu.exec_(QtGui.QCursor.pos())
    
    def _build_cache_data(self) -> dict:
        """构建缓存数据字典"""
        todo_data = []
        if hasattr(self, 'todo_list') and self.todo_list:
            todo_data = self.todo_list.get_todos_data()
        return build_session_cache_record(
            self._session_id,
            {
                'created_at': self._session_created_at,
                'conversation_history': self._conversation_history,
                'context_summary': self._context_summary,
                'token_stats': self._token_stats,
            },
            todo_data=todo_data,
            estimated_tokens=self._calculate_context_tokens(),
            todo_summary=self.todo_list.get_todos_summary() if hasattr(self, 'todo_list') else "",
        )

    def _periodic_save_all(self):
        """定期保存所有会话（QTimer 触发 + aboutToQuit 触发）"""
        try:
            if not self._sessions:
                return
            # 只有存在对话时才保存
            has_any = False
            for sid, sdata in self._sessions.items():
                if sdata.get('conversation_history'):
                    has_any = True
                    break
            if not has_any:
                return
            self._save_session_workspace()
        except Exception as e:
            print(f"[Cache] 定期保存失败: {e}")
    
    def _atexit_save(self):
        """Python 退出时的最后保存机会（atexit 回调）
        
        ★ 此时 Qt widget 可能已被销毁，因此：
        - 使用 _tabs_backup（纯 Python 列表）代替遍历 QTabBar
        - 使用 try/except 包裹 todo_list 访问
        """
        # ★ stale 保护：新窗口创建时旧实例被标记为 inactive，
        #   此时不再写文件，避免覆盖新窗口已保存的正确数据
        self._save_session_workspace(use_backup=True, quiet=True)

    def _save_cache(self) -> bool:
        """自动保存：覆写同 session 文件 + manifest"""
        if not self._conversation_history:
            return False
        try:
            # 同步当前会话状态到 _sessions
            self._save_current_session_state()
            # ★ 同步 tab 备份
            self._sync_tabs_backup()
            
            return self._save_session_workspace()
        except Exception as e:
            print(f"[Cache] 自动保存失败: {e}")
            return False
    
    def _update_manifest(self):
        """更新 sessions_manifest.json 以反映当前所有标签的状态"""
        try:
            manifest_tabs = []
            for i in range(self.session_tabs.count()):
                sid = self.session_tabs.tabData(i)
                if not sid:
                    continue
                tab_label = self.session_tabs.tabText(i)
                sdata = self._sessions.get(sid, {})
                history = sdata.get('conversation_history', [])
                if not history:
                    try:
                        session_file = self._cache_dir / f"session_{sid}.json"
                        if session_file.exists():
                            session_file.unlink()
                    except Exception:
                        pass
                    continue

                # 检查该 session 是否有对话文件存在
                session_file = self._cache_dir / f"session_{sid}.json"
                if not session_file.exists():
                    continue
                manifest_tabs.append({
                    'session_id': sid,
                    'tab_label': tab_label,
                    'file': f"session_{sid}.json",
                })
            self._write_manifest(manifest_tabs)
        except Exception as e:
            print(f"[Cache] 更新 manifest 失败: {e}")

    def _write_manifest(self, manifest_tabs: list, indent: int = 2):
        write_manifest(self._cache_dir, manifest_tabs, getattr(self, '_session_id', ''), indent)

    def _manifest_active_session_id(self, manifest_tabs: list) -> str:
        """Return an active session that is actually present in the saved manifest."""
        return active_session_id(manifest_tabs, getattr(self, '_session_id', ''))

    def _save_all_sessions(self) -> bool:
        """保存所有打开的会话到磁盘（关闭软件时调用）"""
        return self._save_session_workspace()

    @staticmethod
    def _atomic_write_json(path: Path, data: dict, indent: int = 2):
        atomic_write_json(path, data, indent)

    @staticmethod
    def _replace_file(source: Path, target: Path):
        replace_file(source, target)

    def _save_session_workspace(self, use_backup: bool = False, quiet: bool = False) -> bool:
        """Single stale-aware owner for all normal, periodic, quit and atexit saves."""
        if not getattr(self, '_ai_tab_active', True):
            return False
        try:
            # ★ agent 仍在运行时，先把最新 history 刷回对应 session（防止关窗口时丢最后一轮）
            agent_sid = getattr(self, '_agent_session_id', None)
            if agent_sid and agent_sid in self._sessions:
                if self._agent_history is not None:
                    self._sessions[agent_sid]['conversation_history'] = self._agent_history
                if self._agent_token_stats is not None:
                    self._sessions[agent_sid]['token_stats'] = self._agent_token_stats
            # 先保存当前活跃会话的状态到 _sessions 字典
            if agent_sid != self._session_id:
                self._save_current_session_state()
            # ★ 同步 tab 备份（确保 atexit 时也能用）
            try:
                self._sync_tabs_backup()
            except (RuntimeError, AttributeError):
                use_backup = True

            tabs_info = getattr(self, '_tabs_backup', []) if use_backup else [
                (self.session_tabs.tabData(i), self.session_tabs.tabText(i))
                for i in range(self.session_tabs.count())
            ]
            if not tabs_info and use_backup:
                tabs_info = [(sid, "Chat") for sid in self._sessions]
            states = {}
            for sid, sdata in self._sessions.items():
                state = SessionState.from_legacy_dict(sid, sdata)
                try:
                    todo = sdata.get('todo_list')
                    state.todo_data = todo.get_todos_data() if todo else []
                except (RuntimeError, AttributeError):
                    pass
                states[sid] = state
            return save_workspace(
                self._cache_dir, states, tabs_info, self._session_id,
                replace=self._replace_file,
            )
        except Exception as e:
            if not quiet:
                print(f"[Cache] 保存所有会话失败: {e}")
            return False

    def _restore_all_sessions(self) -> bool:
        """从 sessions_manifest.json 恢复所有会话标签（启动时调用，幂等）

        恢复策略（严格信任 manifest）：
                - manifest 存在 → 仅按 manifest 列出的 tab 恢复。即使 tabs 为空，
                    也表示用户上次关闭时是空工作区，不再扫描孤儿 session_*.json。
                - manifest 不存在 → 兜底扫盘，把目录下所有 session_*.json
                    作为孤儿恢复，避免误删 manifest 时丢失全部历史会话。

        可通过实例属性 `_orphan_scan_on_restore` 强制改变行为：
            True  → 即使 manifest 存在也扫盘补 tab（旧行为）
            False → 即使 manifest 不存在也不扫盘
            None / 未设置 → 按上面默认策略
        """
        # ★ 幂等保护：防止 __init__ 和 main_window 延迟回调重复恢复
        if getattr(self, '_sessions_restored', False):
            return True
        try:
            plan = load_restore_plan(
                self._cache_dir,
                orphan_scan=getattr(self, '_orphan_scan_on_restore', None),
            )
            if plan.cleared:
                self._write_manifest([])
                self._sessions_restored = True
                self._sync_tabs_backup()
                self._update_context_stats()
                return True

            # manifest 不存在且扫盘也没补到任何东西 → 没什么可恢复的
            if not plan.sessions:
                if plan.manifest_exists:
                    self._sessions_restored = True
                    self._sync_tabs_backup()
                    self._update_context_stats()
                    return True
                return False

            active_sid = plan.active_session_id
            active_tab_index = 0
            first_tab = True

            for sid, tab_label, state in plan.sessions:
                history = state.conversation_history
                context_summary = state.context_summary
                created_at = state.created_at
                todo_data = state.todo_data
                saved_token_stats = state.token_stats

                if first_tab:
                    # 第一个 tab：加载到已有的初始会话中
                    first_tab = False
                    old_id = self._session_id

                    self._session_id = sid
                    self._session_created_at = created_at
                    self._conversation_history = history
                    self._context_summary = context_summary
                    self._token_stats = saved_token_stats

                    # 更新 sessions 字典
                    if old_id in self._sessions:
                        sdata = self._sessions.pop(old_id)
                        sdata['conversation_history'] = history
                        sdata['created_at'] = created_at
                        sdata['context_summary'] = context_summary
                        sdata['token_stats'] = saved_token_stats
                        self._sessions[sid] = sdata
                    elif sid not in self._sessions:
                        self._sessions[sid] = {
                            'scroll_area': self.scroll_area,
                            'chat_container': self.chat_container,
                            'chat_layout': self.chat_layout,
                            'todo_list': self.todo_list,
                            'conversation_history': history,
                            'created_at': created_at,
                            'context_summary': context_summary,
                            'current_response': None,
                            'token_stats': saved_token_stats,
                        }

                    # 恢复 todo 数据
                    if todo_data and hasattr(self, 'todo_list') and self.todo_list:
                        self.todo_list.restore_todos(todo_data)
                        self._ensure_todo_in_chat(self.todo_list, self.chat_layout)

                    # 更新标签
                    for i in range(self.session_tabs.count()):
                        if self.session_tabs.tabData(i) == old_id:
                            self.session_tabs.setTabData(i, sid)
                            self.session_tabs.setTabText(i, tab_label)
                            if sid == active_sid:
                                active_tab_index = i
                            break

                    self._render_conversation_history()
                else:
                    # 后续 tab：创建新标签
                    self._save_current_session_state()
                    self._session_counter += 1

                    scroll_area, chat_container, chat_layout = self._create_session_widgets()
                    self.session_stack.addWidget(scroll_area)

                    tab_index = self.session_tabs.addTab(tab_label)
                    self.session_tabs.setTabData(tab_index, sid)

                    todo = self._create_todo_list(chat_container)
                    # 恢复 todo 数据
                    if todo_data:
                        todo.restore_todos(todo_data)
                        self._ensure_todo_in_chat(todo, chat_layout)

                    self._sessions[sid] = {
                        'scroll_area': scroll_area,
                        'chat_container': chat_container,
                        'chat_layout': chat_layout,
                        'todo_list': todo,
                        'conversation_history': history,
                        'created_at': created_at,
                        'context_summary': context_summary,
                        'current_response': None,
                        'token_stats': saved_token_stats,
                    }

                    # 临时切换到该标签以渲染历史
                    old_scroll = self.scroll_area
                    old_chat_container = self.chat_container
                    old_chat_layout = self.chat_layout
                    old_todo = self.todo_list
                    old_history = self._conversation_history
                    old_summary = self._context_summary
                    old_stats = self._token_stats
                    old_sid = self._session_id
                    old_created_at = self._session_created_at

                    self._session_id = sid
                    self._session_created_at = created_at
                    self._conversation_history = history
                    self._context_summary = context_summary
                    self._token_stats = saved_token_stats
                    self.scroll_area = scroll_area
                    self.chat_container = chat_container
                    self.chat_layout = chat_layout
                    self.todo_list = todo

                    self._render_conversation_history()

                    # 恢复
                    self._session_id = old_sid
                    self._session_created_at = old_created_at
                    self._conversation_history = old_history
                    self._context_summary = old_summary
                    self._token_stats = old_stats
                    self.scroll_area = old_scroll
                    self.chat_container = old_chat_container
                    self.chat_layout = old_chat_layout
                    self.todo_list = old_todo

                    if sid == active_sid:
                        active_tab_index = tab_index

            # 切换到之前活跃的标签
            if self.session_tabs.count() > 0:
                self.session_tabs.blockSignals(True)
                self.session_tabs.setCurrentIndex(active_tab_index)
                self.session_tabs.blockSignals(False)

                target_sid = self.session_tabs.tabData(active_tab_index)
                if target_sid and target_sid in self._sessions:
                    self._load_session_state(target_sid)
                    self.session_stack.setCurrentWidget(
                        self._sessions[target_sid]['scroll_area']
                    )

            # ★ 恢复完成后同步 tab 备份并更新 UI 显示
            self._sync_tabs_backup()
            self._update_manifest()
            self._update_token_stats_display()
            self._update_context_stats()
            self._sessions_restored = True  # 标记已恢复，防止重复
            print(f"[Cache] 已恢复 {self.session_tabs.count()} 个会话标签")
            return True

        except Exception as e:
            print(f"[Cache] 恢复多会话失败: {e}")
            import traceback; traceback.print_exc()
            return False

    def _archive_cache(self) -> bool:
        """手动存档：创建带时间戳的独立文件（不会被覆写）"""
        if not self._conversation_history:
            QtWidgets.QMessageBox.information(self, "提示", "没有对话历史可存档")
            return False
        try:
            cache_data = self._build_cache_data()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"archive_{self._session_id}_{timestamp}.json"
            archive_file = self._cache_dir / filename
            with open(archive_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            est = cache_data['estimated_tokens']
            self._addStatus.emit(f"已存档: {filename} (~{est} tokens)")
            return True
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "错误", f"存档失败: {str(e)}")
            return False
    
    def _load_cache(self, cache_file: Path, silent: bool = False) -> bool:
        """从缓存文件加载对话历史（在新标签页中打开）
        
        Args:
            cache_file: 缓存文件路径
            silent: 是否静默加载（不显示确认对话框，用于工作区自动恢复）
        """
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 验证数据格式
            if 'conversation_history' not in cache_data:
                if not silent:
                    QtWidgets.QMessageBox.warning(self, "错误", "缓存文件格式无效")
                return False
            
            # 确认加载（静默模式下跳过）
            if not silent:
                msg_count = len(cache_data.get('conversation_history', []))
                reply = QtWidgets.QMessageBox.question(
                    self, "确认加载",
                    f"将在新标签页加载 {msg_count} 条对话记录。\n是否继续？",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                )
                
                if reply != QtWidgets.QMessageBox.Yes:
                    return False
            
            record = SessionCacheRecord.from_cache_data(cache_data)
            history = record.conversation_history
            context_summary = record.context_summary
            created_at = record.created_at
            todo_data = record.todo_data
            cached_session_id = record.session_id
            # ★ 恢复 token 使用统计
            saved_token_stats = record.token_stats
            
            if silent and not self._conversation_history:
                # 静默恢复：当前会话为空时直接加载到当前标签
                self._conversation_history = history
                self._context_summary = context_summary
                self._last_auto_read_context = None
                self._session_id = cached_session_id
                self._session_created_at = created_at
                self._token_stats = saved_token_stats
                # 恢复 todo 数据
                if todo_data and hasattr(self, 'todo_list') and self.todo_list:
                    self.todo_list.restore_todos(todo_data)
                    self._ensure_todo_in_chat(self.todo_list, self.chat_layout)
                # 更新 sessions 字典
                if self._session_id in self._sessions:
                    self._sessions[self._session_id]['conversation_history'] = self._conversation_history
                    self._sessions[self._session_id]['created_at'] = created_at
                    self._sessions[self._session_id]['context_summary'] = self._context_summary
                    self._sessions[self._session_id]['token_stats'] = saved_token_stats
                elif self._sessions:
                    # 旧 session_id 已经变了，需要重新映射
                    old_id = list(self._sessions.keys())[0]
                    sdata = self._sessions.pop(old_id)
                    sdata['conversation_history'] = self._conversation_history
                    sdata['created_at'] = created_at
                    sdata['context_summary'] = self._context_summary
                    sdata['token_stats'] = saved_token_stats
                    self._sessions[self._session_id] = sdata
                    # 更新标签数据
                    for i in range(self.session_tabs.count()):
                        if self.session_tabs.tabData(i) == old_id:
                            self.session_tabs.setTabData(i, self._session_id)
                            break
                self._render_conversation_history()
                self._update_token_stats_display()
                self._update_context_stats()
                # 自动重命名标签
                if history:
                    for msg in history:
                        if msg.get('role') == 'user' and msg.get('content'):
                            self._auto_rename_tab(msg['content'])
                            break
                print(f"[Workspace] 自动恢复上下文: {len(self._conversation_history)} 条消息")
                return True
            
            # 非静默或当前会话非空：在新标签页中打开
            self._save_current_session_state()
            
            # 创建新标签
            self._session_counter += 1
            scroll_area, chat_container, chat_layout = self._create_session_widgets()
            self.session_stack.addWidget(scroll_area)
            
            # 用缓存文件名或首条用户消息作为标签名
            label = f"Chat {self._session_counter}"
            for msg in history:
                if msg.get('role') == 'user' and msg.get('content'):
                    short = msg['content'][:18].replace('\n', ' ').strip()
                    if len(msg['content']) > 18:
                        short += "..."
                    label = short
                    break
            
            tab_index = self.session_tabs.addTab(label)
            self.session_tabs.setTabData(tab_index, cached_session_id)
            
            todo = self._create_todo_list(chat_container)
            if todo_data:
                todo.restore_todos(todo_data)
                self._ensure_todo_in_chat(todo, chat_layout)
            
            self._sessions[cached_session_id] = {
                'scroll_area': scroll_area,
                'chat_container': chat_container,
                'chat_layout': chat_layout,
                'todo_list': todo,
                'conversation_history': history,
                'created_at': created_at,
                'context_summary': context_summary,
                'current_response': None,
                'token_stats': saved_token_stats,
            }
            
            # 切换到新标签
            self._session_id = cached_session_id
            self._session_created_at = created_at
            self._conversation_history = history
            self._context_summary = context_summary
            self._last_auto_read_context = None
            self._current_response = None
            self._token_stats = saved_token_stats
            self.scroll_area = scroll_area
            self.chat_container = chat_container
            self.chat_layout = chat_layout
            self.todo_list = todo
            
            self.session_tabs.blockSignals(True)
            self.session_tabs.setCurrentIndex(tab_index)
            self.session_tabs.blockSignals(False)
            self.session_stack.setCurrentWidget(scroll_area)
            
            self._render_conversation_history()
            self._update_token_stats_display()
            self._update_context_stats()
            
            if not silent:
                self._addStatus.emit(f"缓存已加载: {cache_file.name}")
            
            return True
            
        except Exception as e:
            if not silent:
                QtWidgets.QMessageBox.warning(self, "错误", f"加载缓存失败: {str(e)}")
            else:
                print(f"[Workspace] 加载缓存失败: {str(e)}")
            return False
    
    def _load_cache_silent(self, cache_file: Path) -> bool:
        """静默加载缓存（用于工作区自动恢复）"""
        return self._load_cache(cache_file, silent=True)
    
    def _load_cache_dialog(self):
        """显示加载缓存对话框"""
        cache_files = sorted(
            set(self._cache_dir.glob("session_*.json"))
            | set(self._cache_dir.glob("archive_*.json"))
            | set(self._cache_dir.glob("cache_*.json")),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        
        if not cache_files:
            QtWidgets.QMessageBox.information(self, "提示", "没有找到缓存文件")
            return
        
        # 创建选择对话框
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("选择缓存文件")
        dialog.setMinimumWidth(500)
        
        layout = QtWidgets.QVBoxLayout(dialog)
        
        # 文件列表
        list_widget = QtWidgets.QListWidget()
        for cache_file in cache_files:
            # 读取文件信息
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    msg_count = len(data.get('conversation_history', []))
                    estimated_tokens = data.get('estimated_tokens', 0)
                    created_at = data.get('created_at', '')
                    if created_at:
                        try:
                            dt = datetime.fromisoformat(created_at)
                            created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            pass
                    token_info = f" | ~{estimated_tokens:,} tokens" if estimated_tokens else ""
                    item_text = f"{cache_file.name}\n  {msg_count} 条消息{token_info} | {created_at}"
            except:
                item_text = cache_file.name
            
            item = QtWidgets.QListWidgetItem(item_text)
            item.setData(QtCore.Qt.UserRole, cache_file)
            list_widget.addItem(item)
        
        layout.addWidget(QtWidgets.QLabel("选择要加载的缓存文件:"))
        layout.addWidget(list_widget)
        
        # 按钮
        btn_layout = QtWidgets.QHBoxLayout()
        btn_load = QtWidgets.QPushButton("加载")
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_layout.addWidget(btn_load)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        def on_load():
            current = list_widget.currentItem()
            if current:
                cache_file = current.data(QtCore.Qt.UserRole)
                if self._load_cache(cache_file):
                    dialog.accept()
        
        btn_load.clicked.connect(on_load)
        btn_cancel.clicked.connect(dialog.reject)
        
        dialog.exec_()
    
    def _list_caches(self):
        """列出所有缓存文件"""
        cache_files = sorted(
            set(self._cache_dir.glob("session_*.json"))
            | set(self._cache_dir.glob("archive_*.json"))
            | set(self._cache_dir.glob("cache_*.json")),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        
        if not cache_files:
            QtWidgets.QMessageBox.information(self, "提示", "没有找到缓存文件")
            return
        
        # 创建信息对话框
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("缓存文件列表")
        dialog.setMinimumSize(600, 400)
        
        layout = QtWidgets.QVBoxLayout(dialog)
        
        # 文本显示
        text_edit = QtWidgets.QTextEdit()
        text_edit.setReadOnly(True)
        
        lines = ["缓存文件列表:\n"]
        for cache_file in cache_files:
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    msg_count = len(data.get('conversation_history', []))
                    created_at = data.get('created_at', '')
                    session_id = data.get('session_id', '')
                    estimated_tokens = data.get('estimated_tokens', 0)
                    
                    if created_at:
                        try:
                            dt = datetime.fromisoformat(created_at)
                            created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            pass
                    
                    size_kb = cache_file.stat().st_size / 1024
                    lines.append(f"  {cache_file.name}")
                    lines.append(f"   会话ID: {session_id}")
                    lines.append(f"   消息数: {msg_count}")
                    if estimated_tokens:
                        lines.append(f"   估算Token: ~{estimated_tokens:,}")
                    lines.append(f"   创建时间: {created_at}")
                    lines.append(f"   文件大小: {size_kb:.1f} KB")
                    lines.append("")
            except Exception as e:
                lines.append(f"[err] {cache_file.name} (读取失败: {str(e)})")
                lines.append("")
        
        text_edit.setPlainText("\n".join(lines))
        layout.addWidget(text_edit)
        
        btn_close = QtWidgets.QPushButton("关闭")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec_()
    
    def _compress_to_summary(self):
        """将旧对话压缩为摘要，减少 token 消耗"""
        if len(self._conversation_history) <= 4:
            QtWidgets.QMessageBox.information(self, "提示", "对话历史太短，无需压缩")
            return
        
        # 确认操作
        reply = QtWidgets.QMessageBox.question(
            self, "确认压缩",
            f"将把前 {len(self._conversation_history) - 4} 条对话压缩为摘要，"
            f"保留最近 4 条完整对话。\n\n"
            f"这样可以大幅减少 token 消耗。是否继续？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        old_tokens = self.token_optimizer.calculate_message_tokens(self._conversation_history)
        result = self.token_optimizer.compress_context(
            self._conversation_history,
            protect_recent_rounds=2,
            existing_summary=self._context_summary,
        )
        stats = result.stats
        self._conversation_history = result.messages
        self._context_summary = result.summary
        
        # 重新渲染
        self._render_conversation_history()
        
        # 更新统计
        self._update_context_stats()
        
        # 计算节省的 token
        new_tokens = stats.get('compressed_tokens', old_tokens)
        saved_tokens = old_tokens - new_tokens
        
        QtWidgets.QMessageBox.information(
            self, "压缩完成",
            f"对话已压缩！\n\n"
            f"原始: ~{old_tokens} tokens\n"
            f"压缩后: ~{new_tokens} tokens\n"
            f"节省: ~{saved_tokens} tokens ({saved_tokens/old_tokens*100:.1f}%)"
        )
