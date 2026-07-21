# -*- coding: utf-8 -*-
"""Cache persistence and history rendering helpers for AITab."""

import json
import re
import time
from datetime import datetime
from pathlib import Path

from houdini_agent.qt_compat import QtCore, QtWidgets


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
    
    @staticmethod
    def _strip_images_for_cache(history: list) -> list:
        """剥离 conversation_history 中的 base64 图片数据，
        用占位文本替代，大幅减小缓存文件体积。
        返回一份深拷贝，不修改原始 history。
        """
        stripped = []
        for msg in history:
            content = msg.get('content')
            if isinstance(content, list):
                # 多模态消息：content 是 [{type:text,...}, {type:image_url,...}, ...]
                new_parts = []
                for part in content:
                    if part.get('type') == 'image_url':
                        url = part.get('image_url', {}).get('url', '')
                        if url.startswith('data:'):
                            # 替换 base64 为占位符，保留 media type 信息
                            media_type = url.split(';')[0].replace('data:', '')
                            new_parts.append({
                                'type': 'text',
                                'text': f'[Image: {media_type}]',
                            })
                        else:
                            new_parts.append(copy.copy(part))
                    else:
                        new_parts.append(copy.copy(part))
                new_msg = msg.copy()
                new_msg['content'] = new_parts
                stripped.append(new_msg)
            else:
                stripped.append(msg)  # 非多模态消息直接引用（str/None 不可变）
        return stripped
    
    def _build_cache_data(self) -> dict:
        """构建缓存数据字典"""
        todo_data = []
        if hasattr(self, 'todo_list') and self.todo_list:
            todo_data = self.todo_list.get_todos_data()
        return {
            'version': '1.0',
            'session_id': self._session_id,
            'created_at': self._session_created_at,
            'message_count': len(self._conversation_history),
            'estimated_tokens': self._calculate_context_tokens(),
            'conversation_history': self._conversation_history,
            'context_summary': self._context_summary,
            'todo_summary': self.todo_list.get_todos_summary() if hasattr(self, 'todo_list') else "",
            'todo_data': todo_data,
            'token_stats': self._token_stats.copy(),
        }

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
            self._save_all_sessions()
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
        if not getattr(self, '_ai_tab_active', True):
            return
        try:
            if not hasattr(self, '_sessions') or not self._sessions:
                return
            # ★ agent 仍在运行时，先把最新 history 刷回对应 session
            try:
                agent_sid = getattr(self, '_agent_session_id', None)
                if agent_sid and agent_sid in self._sessions:
                    if getattr(self, '_agent_history', None) is not None:
                        self._sessions[agent_sid]['conversation_history'] = self._agent_history
                    if getattr(self, '_agent_token_stats', None) is not None:
                        self._sessions[agent_sid]['token_stats'] = self._agent_token_stats
            except Exception:
                pass
            # 尝试同步当前状态（Qt widget 可能已销毁）
            try:
                if getattr(self, '_agent_session_id', None) != getattr(self, '_session_id', None):
                    self._save_current_session_state()
            except (RuntimeError, AttributeError):
                pass
            
            # ★ 优先使用 _tabs_backup（纯 Python 数据，不依赖 Qt）
            tabs_info = getattr(self, '_tabs_backup', [])
            if not tabs_info:
                # 如果备份也为空，尝试从 _sessions 字典的 key 中获取
                tabs_info = [(sid, f"Chat") for sid in self._sessions]
            
            # 直接写文件，不依赖 Qt 事件循环
            manifest_tabs = []
            for sid, tab_label in tabs_info:
                if not sid or sid not in self._sessions:
                    continue
                sdata = self._sessions[sid]
                history = sdata.get('conversation_history', [])
                if not history:
                    continue
                # 收集 todo 数据（widget 可能已销毁）
                todo_data = []
                try:
                    todo_list_obj = sdata.get('todo_list')
                    todo_data = todo_list_obj.get_todos_data() if todo_list_obj else []
                except (RuntimeError, AttributeError, Exception):
                    pass
                cache_data = {
                    'version': '1.0',
                    'session_id': sid,
                    'created_at': sdata.get('created_at') or datetime.now().isoformat(),
                    'message_count': len(history),
                    'conversation_history': self._strip_images_for_cache(history),
                    'context_summary': sdata.get('context_summary', ''),
                    'todo_data': todo_data,
                    'token_stats': sdata.get('token_stats', {}),
                }
                session_file = self._cache_dir / f"session_{sid}.json"
                with open(session_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False)
                manifest_tabs.append({
                    'session_id': sid,
                    'tab_label': tab_label,
                    'file': f"session_{sid}.json",
                })
            self._write_manifest(manifest_tabs, indent=None)
        except Exception:
            pass  # atexit 中不能抛出异常

    def _save_cache(self) -> bool:
        """自动保存：覆写同 session 文件 + manifest"""
        if not self._conversation_history:
            return False
        try:
            # 同步当前会话状态到 _sessions
            self._save_current_session_state()
            # ★ 同步 tab 备份
            self._sync_tabs_backup()
            
            cache_data = self._build_cache_data()
            # ★ 剥离 base64 图片以减小缓存文件大小
            cache_data['conversation_history'] = self._strip_images_for_cache(
                cache_data.get('conversation_history', [])
            )

            # 1. 覆写固定的 session 文件（一个 session 只有一个文件）
            session_file = self._cache_dir / f"session_{self._session_id}.json"
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            # 2. 同步更新 sessions_manifest.json（确保所有 tab 信息都是最新的）
            # ★ 不再写 cache_latest.json — 恢复由 sessions_manifest + session_*.json 管理
            self._update_manifest()

            if self._workspace_dir:
                self._update_workspace_cache_info()
            return True
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
        manifest = {
            'version': '1.0',
            'active_session_id': self._manifest_active_session_id(manifest_tabs),
            'tabs': manifest_tabs,
        }
        manifest_file = self._cache_dir / "sessions_manifest.json"
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=indent)
        clear_marker = self._cache_dir / "sessions_cleared.json"
        if manifest_tabs:
            try:
                if clear_marker.exists():
                    clear_marker.unlink()
            except Exception:
                pass
        else:
            try:
                with open(clear_marker, 'w', encoding='utf-8') as f:
                    json.dump({
                        'version': '1.0',
                        'cleared_at': datetime.now().isoformat(),
                    }, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def _manifest_active_session_id(self, manifest_tabs: list) -> str:
        """Return an active session that is actually present in the saved manifest."""
        saved_sids = [tab.get('session_id') for tab in manifest_tabs if tab.get('session_id')]
        session_id = getattr(self, '_session_id', '')
        if session_id in saved_sids:
            return session_id
        return saved_sids[0] if saved_sids else ""

    def _save_all_sessions(self) -> bool:
        """保存所有打开的会话到磁盘（关闭软件时调用）"""
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
            self._sync_tabs_backup()

            manifest_tabs = []
            for i in range(self.session_tabs.count()):
                sid = self.session_tabs.tabData(i)
                tab_label = self.session_tabs.tabText(i)
                if not sid or sid not in self._sessions:
                    continue

                sdata = self._sessions[sid]
                history = sdata.get('conversation_history', [])
                if not history:
                    # ★ 空会话：清理其磁盘上的旧 session 文件（防止残留）
                    try:
                        old_file = self._cache_dir / f"session_{sid}.json"
                        if old_file.exists():
                            old_file.unlink()
                    except Exception:
                        pass
                    continue  # 空会话不保存

                # 收集 todo 数据（防御 widget 已销毁的情况）
                todo_data = []
                try:
                    todo_list_obj = sdata.get('todo_list')
                    todo_data = todo_list_obj.get_todos_data() if todo_list_obj else []
                except (RuntimeError, AttributeError):
                    pass

                # 写 session 文件（★ 剥离 base64 图片以减小文件大小）
                cache_data = {
                    'version': '1.0',
                    'session_id': sid,
                    'created_at': sdata.get('created_at') or datetime.now().isoformat(),
                    'message_count': len(history),
                    'conversation_history': self._strip_images_for_cache(history),
                    'context_summary': sdata.get('context_summary', ''),
                    'todo_data': todo_data,
                    'token_stats': sdata.get('token_stats', {}),
                }
                session_file = self._cache_dir / f"session_{sid}.json"
                with open(session_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)

                manifest_tabs.append({
                    'session_id': sid,
                    'tab_label': tab_label,
                    'file': f"session_{sid}.json",
                })

            # 写 manifest 文件
            self._write_manifest(manifest_tabs)

            # ★ 不再写 cache_latest.json — 恢复由 sessions_manifest + session_*.json 管理
            # print(f"[Cache] 已保存 {len(manifest_tabs)} 个会话到磁盘")
            return bool(manifest_tabs)
        except Exception as e:
            print(f"[Cache] 保存所有会话失败: {e}")
            import traceback; traceback.print_exc()
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
            manifest_file = self._cache_dir / "sessions_manifest.json"
            clear_marker = self._cache_dir / "sessions_cleared.json"
            if clear_marker.exists():
                self._write_manifest([])
                self._sessions_restored = True
                self._sync_tabs_backup()
                self._update_context_stats()
                return True

            manifest_exists = manifest_file.exists()

            manifest = {}
            tabs_info = []
            if manifest_exists:
                with open(manifest_file, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                tabs_info = manifest.get('tabs', []) or []

            # 决定是否扫盘补孤儿 session 文件
            scan_override = getattr(self, '_orphan_scan_on_restore', None)
            if scan_override is None:
                should_scan_orphans = not manifest_exists
            else:
                should_scan_orphans = bool(scan_override)

            if should_scan_orphans:
                known_sids = {tab.get('session_id') for tab in tabs_info if tab.get('session_id')}
                for session_file in sorted(self._cache_dir.glob("session_*.json")):
                    sid = session_file.stem.replace("session_", "", 1)
                    if sid in known_sids:
                        continue
                    try:
                        with open(session_file, 'r', encoding='utf-8') as f:
                            cache_data = json.load(f)
                    except Exception:
                        continue
                    history = cache_data.get('conversation_history', [])
                    if not history:
                        continue
                    label = "Chat"
                    for msg in history:
                        if msg.get('role') == 'user' and msg.get('content'):
                            label = str(msg['content'])[:18].replace('\n', ' ').strip() or label
                            if len(str(msg['content'])) > 18:
                                label += "..."
                            break
                    tabs_info.append({
                        'session_id': sid,
                        'tab_label': label,
                        'file': session_file.name,
                    })
                    known_sids.add(sid)

            # manifest 不存在且扫盘也没补到任何东西 → 没什么可恢复的
            if not tabs_info:
                if manifest_exists:
                    self._sessions_restored = True
                    self._sync_tabs_backup()
                    self._update_context_stats()
                    return True
                return False

            active_sid = manifest.get('active_session_id', '')
            active_tab_index = 0
            first_tab = True

            for tab_info in tabs_info:
                sid = tab_info.get('session_id', '')
                tab_label = tab_info.get('tab_label', 'Chat')
                session_file = self._cache_dir / tab_info.get('file', '')

                if not session_file.exists():
                    continue

                with open(session_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)

                history = cache_data.get('conversation_history', [])
                if not history:
                    continue

                context_summary = cache_data.get('context_summary', '')
                created_at = cache_data.get('created_at') or datetime.now().isoformat()
                todo_data = cache_data.get('todo_data', [])
                # ★ 从缓存中恢复 token 使用统计
                saved_token_stats = cache_data.get('token_stats', {
                    'input_tokens': 0, 'output_tokens': 0,
                    'reasoning_tokens': 0,
                    'cache_read': 0, 'cache_write': 0,
                    'total_tokens': 0, 'requests': 0,
                    'estimated_cost': 0.0,
                })

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
    
    def _update_workspace_cache_info(self):
        """更新工作区中的缓存信息（供主窗口保存工作区时使用）"""
        # 这个方法会被主窗口调用，用于更新工作区配置
        # 实际保存由主窗口的 _save_workspace 完成
        pass
    
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
            
            history = cache_data.get('conversation_history', [])
            context_summary = cache_data.get('context_summary', '')
            created_at = cache_data.get('created_at') or datetime.now().isoformat()
            todo_data = cache_data.get('todo_data', [])
            cached_session_id = cache_data.get('session_id', str(uuid.uuid4())[:8])
            # ★ 恢复 token 使用统计
            saved_token_stats = cache_data.get('token_stats', {
                'input_tokens': 0, 'output_tokens': 0,
                'reasoning_tokens': 0,
                'cache_read': 0, 'cache_write': 0,
                'total_tokens': 0, 'requests': 0,
                'estimated_cost': 0.0,
            })
            
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
        
        # 执行压缩
        old_messages = self._conversation_history[:-4]
        recent_messages = self._conversation_history[-4:]
        
        # 生成详细摘要
        summary_parts = ["[历史对话摘要 - 已压缩以节省 token]"]
        
        user_requests = []
        ai_results = []
        
        for msg in old_messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            
            if role == 'user':
                # 提取用户请求的核心（前200字符）
                user_request = content[:200].replace('\n', ' ')
                if len(content) > 200:
                    user_request += "..."
                user_requests.append(user_request)
            
            elif role == 'assistant' and content:
                # 提取 AI 回复的关键信息
                lines = [l.strip() for l in content.split('\n') if l.strip()]
                if lines:
                    # 取最后一行或前150字符
                    result_summary = lines[-1][:150].replace('\n', ' ')
                    if len(lines[-1]) > 150:
                        result_summary += "..."
                    ai_results.append(result_summary)
        
        # 合并摘要
        if user_requests:
            summary_parts.append(f"\n用户请求 ({len(user_requests)} 条):")
            for i, req in enumerate(user_requests[:10], 1):  # 最多显示10条
                summary_parts.append(f"  {i}. {req}")
            if len(user_requests) > 10:
                summary_parts.append(f"  ... 还有 {len(user_requests) - 10} 条请求")
        
        if ai_results:
            summary_parts.append(f"\nAI 完成的任务 ({len(ai_results)} 条):")
            for i, res in enumerate(ai_results[:10], 1):  # 最多显示10条
                summary_parts.append(f"  {i}. {res}")
            if len(ai_results) > 10:
                summary_parts.append(f"  ... 还有 {len(ai_results) - 10} 条结果")
        
        summary_text = "\n".join(summary_parts)
        
        # 更新历史：用摘要替换旧对话
        self._conversation_history = [
            {'role': 'system', 'content': summary_text}
        ] + recent_messages
        
        # 更新上下文摘要
        self._context_summary = summary_text
        
        # 重新渲染
        self._render_conversation_history()
        
        # 更新统计
        self._update_context_stats()
        
        # 计算节省的 token
        old_tokens = sum(self._estimate_tokens(json.dumps(msg)) for msg in old_messages)
        new_tokens = self._estimate_tokens(summary_text)
        saved_tokens = old_tokens - new_tokens
        
        QtWidgets.QMessageBox.information(
            self, "压缩完成",
            f"对话已压缩！\n\n"
            f"原始: ~{old_tokens} tokens\n"
            f"压缩后: ~{new_tokens} tokens\n"
            f"节省: ~{saved_tokens} tokens ({saved_tokens/old_tokens*100:.1f}%)"
        )
    
    # ---------- 历史渲染辅助 ----------
    _CONTEXT_HEADERS = ('[Network structure]', '[Selected nodes]',
                        '[Auto-read: Network structure]', '[Auto-read: Selected nodes]',
                        '[网络结构]', '[选中节点]')

    # ★ 分批渲染常量（借鉴 markstream-vue 的批次策略）
    _BATCH_INITIAL = 30      # 首批渲染最后 N 条消息（用户最近看到的）
    _BATCH_SIZE = 15          # 后续每批渲染 N 条
    _BATCH_BUDGET_MS = 8      # 每批时间预算（毫秒）

    def _render_conversation_history(self):
        """重新渲染对话历史到 UI

        ★ 分批渲染策略（借鉴 markstream-vue）：
        1. 首批渲染最后 _BATCH_INITIAL 条消息（用户最近看到的）
        2. 用 QTimer.singleShot(0) 模拟 idle callback，逐批渲染剩余
        3. 每批设时间预算，超出则暂停让出主线程

        处理三种数据格式：
        1. role="user" 中嵌入 [Network structure] / [Selected nodes] 等上下文
           → 用户文字正常显示，上下文数据放入可折叠区域
        2. role="assistant" 以 [工具执行结果] 开头
           → 解析每一条 [ok]/[err]/✅/❌ 行，创建折叠式 ToolCallItem
        3. role="tool"（旧缓存格式）
           → 先 add_tool_call 再 set_tool_result（折叠式）
        """
        # 清空当前显示（保留末尾 stretch）
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 取消之前的分批渲染定时器
        if hasattr(self, '_batch_render_timer') and self._batch_render_timer is not None:
            self._batch_render_timer.stop()
            self._batch_render_timer = None

        messages = self._conversation_history
        if not messages:
            return

        # ★ 预扫描：将消息分组为逻辑"轮次"（每轮 = 一组相关消息）
        groups = self._group_messages_into_turns(messages)
        total_groups = len(groups)

        if total_groups <= self._BATCH_INITIAL:
            # 消息量小，一次性渲染
            self._render_message_groups(groups, 0, total_groups)
        else:
            # ★ 分批渲染：先渲染最后 _BATCH_INITIAL 组（用户最近看到的）
            # 早期消息用占位符
            early_count = total_groups - self._BATCH_INITIAL

            # 插入占位符
            self._batch_placeholder = QtWidgets.QLabel(
                f"⏳ 加载历史消息 ({early_count} 轮)..."
            )
            self._batch_placeholder.setObjectName("batchPlaceholder")
            self._batch_placeholder.setStyleSheet(
                "color: #64748b; padding: 8px 12px; font-size: 12px; "
                "font-style: italic; background: transparent;"
            )
            self._batch_placeholder.setAlignment(QtCore.Qt.AlignCenter)
            # 插入到 stretch 之前
            self.chat_layout.insertWidget(self.chat_layout.count() - 1,
                                         self._batch_placeholder)

            # 渲染最后 _BATCH_INITIAL 组
            self._render_message_groups(groups, early_count, total_groups)

            # 用 QTimer 分批渲染早期消息
            self._batch_groups = groups
            self._batch_cursor = early_count  # 从 early_count 向 0 回退
            self._batch_insert_pos = 0  # 早期消息插入到布局头部
            self._batch_render_timer = QtCore.QTimer(self)
            self._batch_render_timer.setSingleShot(True)
            self._batch_render_timer.timeout.connect(self._render_next_batch)
            self._batch_render_timer.start(0)  # 下一帧开始

    def _group_messages_into_turns(self, messages: list) -> list:
        """将消息列表分组为逻辑轮次
        
        返回: list of (start_idx, end_idx) 元组
        """
        groups: list = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get('role', '')

            if role == 'user':
                groups.append((i, i + 1))
                i += 1
            elif role == 'assistant':
                if msg.get('tool_calls'):
                    # 收集工具交互轮次
                    j = i + 1
                    while j < len(messages):
                        m = messages[j]
                        r = m.get('role', '')
                        if r == 'tool':
                            j += 1
                        elif r == 'assistant':
                            j += 1
                            if not m.get('tool_calls'):
                                break
                        else:
                            break
                    groups.append((i, j))
                    i = j
                else:
                    # 普通 assistant + 后续 tool 消息
                    j = i + 1
                    while j < len(messages) and messages[j].get('role') == 'tool':
                        j += 1
                    groups.append((i, j))
                    i = j
            elif role == 'system':
                groups.append((i, i + 1))
                i += 1
            else:
                groups.append((i, i + 1))
                i += 1
        return groups

    def _render_message_groups(self, groups: list, start: int, end: int):
        """渲染 [start, end) 范围内的消息组"""
        messages = self._conversation_history
        for gi in range(start, end):
            si, ei = groups[gi]
            try:
                self._render_single_group(messages, si, ei)
            except Exception:
                import traceback
                traceback.print_exc()

    def _render_single_group(self, messages: list, si: int, ei: int):
        """渲染一个消息组"""
        msg = messages[si]
        role = msg.get('role', '')
        raw_content = msg.get('content', '') or ''
        if isinstance(raw_content, list):
            content = '\n'.join(
                part.get('text', '') for part in raw_content
                if isinstance(part, dict) and part.get('type') == 'text'
            )
        else:
            content = raw_content

        if role == 'user':
            self._render_user_history(content)

        elif role == 'assistant':
            if msg.get('tool_calls'):
                turn_msgs = messages[si:ei]
                self._render_native_tool_turn(turn_msgs)
            else:
                tool_msgs = [messages[j] for j in range(si + 1, ei)
                             if messages[j].get('role') == 'tool']

                if content.lstrip().startswith('[工具执行结果]'):
                    self._render_tool_summary_history(content, msg)
                else:
                    response = self._add_ai_response()
                    thinking = msg.get('thinking', '')
                    if thinking:
                        response.add_thinking(thinking)
                        response.thinking_section.finalize()
                    self._render_old_tool_msgs(response, tool_msgs)
                    self._restore_shell_widgets(response, msg)
                    response.set_content(content)
                    response.status_label.setText("历史")
                    response.finalize()
                    parts = []
                    if thinking:
                        parts.append("思考")
                    if tool_msgs:
                        parts.append(f"{len(tool_msgs)}次调用")
                    label = f"历史 | {', '.join(parts)}" if parts else "历史"
                    response.status_label.setText(label)

        elif role == 'system' and '[历史对话摘要' in content:
            response = self._add_ai_response()
            response.add_collapsible("历史对话摘要", content)
            response.status_label.setText("历史摘要")
            response.finalize()
            response.status_label.setText("历史摘要")

    def _render_next_batch(self):
        """分批渲染回调 — 渲染下一批早期消息（从后向前，插入到布局头部）"""
        if not hasattr(self, '_batch_groups') or not self._batch_groups:
            return
        if self._batch_cursor <= 0:
            # 全部渲染完毕，移除占位符
            self._finish_batch_render()
            return

        batch_start = max(0, self._batch_cursor - self._BATCH_SIZE)
        batch_end = self._batch_cursor
        start_time = time.time()

        # ★ 早期消息需要插入到占位符之前（即布局的第 0 个位置开始）
        # 我们从 batch_start 到 batch_end 按顺序渲染，每个 widget 插入到
        # 占位符位置之前（insert_pos 递增）
        messages = self._conversation_history
        insert_pos = self._batch_insert_pos  # 在此位置之前插入
        rendered_count = 0

        for gi in range(batch_start, batch_end):
            si, ei = self._batch_groups[gi]
            try:
                widgets_before = self.chat_layout.count()
                self._render_single_group(messages, si, ei)
                widgets_after = self.chat_layout.count()
                added = widgets_after - widgets_before

                # 将新添加的 widget 移动到正确位置（占位符之前）
                if added > 0:
                    for _ in range(added):
                        # 取出最后添加的 widget（在 stretch 之前）
                        from_idx = self.chat_layout.count() - 2  # -1 是 stretch, -2 是新 widget
                        item = self.chat_layout.takeAt(from_idx)
                        if item and item.widget():
                            self.chat_layout.insertWidget(insert_pos, item.widget())
                            insert_pos += 1
                    rendered_count += added
            except Exception:
                import traceback
                traceback.print_exc()

            # 时间预算检查
            elapsed_ms = (time.time() - start_time) * 1000
            if elapsed_ms > self._BATCH_BUDGET_MS and gi < batch_end - 1:
                self._batch_cursor = gi + 1
                self._batch_insert_pos = insert_pos
                remaining = gi + 1
                if hasattr(self, '_batch_placeholder') and self._batch_placeholder:
                    try:
                        self._batch_placeholder.setText(
                            f"⏳ 加载历史消息 ({remaining} 轮)..."
                        )
                    except RuntimeError:
                        pass
                self._batch_render_timer.start(0)
                return

        self._batch_cursor = batch_start
        self._batch_insert_pos = insert_pos

        if self._batch_cursor > 0:
            if hasattr(self, '_batch_placeholder') and self._batch_placeholder:
                try:
                    self._batch_placeholder.setText(
                        f"⏳ 加载历史消息 ({self._batch_cursor} 轮)..."
                    )
                except RuntimeError:
                    pass
            self._batch_render_timer.start(0)
        else:
            self._finish_batch_render()

    def _finish_batch_render(self):
        """完成分批渲染，清理占位符"""
        if hasattr(self, '_batch_placeholder') and self._batch_placeholder:
            try:
                self._batch_placeholder.setVisible(False)
                self._batch_placeholder.deleteLater()
            except RuntimeError:
                pass
            self._batch_placeholder = None
        self._batch_groups = None
        self._batch_render_timer = None

    # ------------------------------------------------------------------
    def _replay_todo_from_tool_call(self, tool_name: str, arguments_str: str):
        """从历史工具调用中恢复 todo 项（不显示在 UI 执行列表中）
        
        注意：todo 数据现在通过 todo_data 字段在缓存中保存/恢复，
        此方法仅作为兼容旧缓存的后备方案。
        """
        try:
            if isinstance(arguments_str, str) and arguments_str:
                args = json.loads(arguments_str)
            elif isinstance(arguments_str, dict):
                args = arguments_str
            else:
                return
            if tool_name == 'add_todo':
                tid = args.get('todo_id', '')
                text = args.get('text', '')
                status = args.get('status', 'pending')
                if tid and text and hasattr(self, 'todo_list') and self.todo_list:
                    self.todo_list.add_todo(tid, text, status)
                    self._ensure_todo_in_chat(self.todo_list, self.chat_layout)
            elif tool_name == 'update_todo':
                tid = args.get('todo_id', '')
                status = args.get('status', 'done')
                if tid and hasattr(self, 'todo_list') and self.todo_list:
                    self.todo_list.update_todo(tid, status)
        except Exception:
            pass  # 解析失败忽略

    # ------------------------------------------------------------------
    def _render_native_tool_turn(self, turn_msgs: list):
        """渲染 Cursor 风格原生工具调用轮次
        
        turn_msgs 格式：
          assistant(tool_calls) → tool → [assistant(tool_calls) → tool →] ... → assistant(reply)
        静默工具（add_todo/update_todo）不显示在执行列表中，但会恢复 todo 数据。
        """
        response = self._add_ai_response()
        tool_count = 0
        final_content = ''
        thinking = ''
        final_msg = {}
        
        for m in turn_msgs:
            r = m.get('role', '')
            if r == 'assistant':
                tc_list = m.get('tool_calls', [])
                if tc_list:
                    # 工具调用 assistant 消息：注册每个工具调用
                    for tc in tc_list:
                        fn = tc.get('function', {})
                        name = fn.get('name', 'unknown')
                        # 静默工具：恢复 todo 但不显示在执行列表
                        if name in self._SILENT_TOOLS:
                            self._replay_todo_from_tool_call(name, fn.get('arguments', ''))
                            continue
                        response.add_status(f"[tool]{name}")
                        tool_count += 1
                else:
                    # 最终回复 assistant 消息
                    final_content = m.get('content', '') or ''
                    thinking = m.get('thinking', '')
                    final_msg = m
            elif r == 'tool':
                tc_id = m.get('tool_call_id', '')
                t_content = m.get('content', '') or ''
                # 从 tool_call_id 查找对应的工具名
                t_name = self._find_tool_name_by_id(turn_msgs, tc_id) or 'tool'
                # 静默工具的结果也不显示
                if t_name in self._SILENT_TOOLS:
                    continue
                success = not t_content.lstrip().startswith('[err]') and 'error' not in t_content[:50].lower()
                prefix = "[ok] " if success else "[err] "
                response.add_tool_result(t_name, f"{prefix}{t_content}")
        
        # 恢复 thinking
        if thinking:
            response.add_thinking(thinking)
            response.thinking_section.finalize()
        
        # 恢复 Shell 折叠面板
        self._restore_shell_widgets(response, final_msg)
        
        # AI 回复内容
        if final_content:
            response.set_content(final_content)
        
        # 状态标签
        parts = []
        if thinking:
            parts.append("思考")
        if tool_count > 0:
            parts.append(f"{tool_count}次调用")
        label = f"历史 | {', '.join(parts)}" if parts else "历史"
        response.status_label.setText(label)
        response.finalize()
        response.status_label.setText(label)

    @staticmethod
    def _find_tool_name_by_id(messages: list, tool_call_id: str) -> str:
        """从消息列表中根据 tool_call_id 查找对应的工具名"""
        if not tool_call_id:
            return ''
        for m in messages:
            if m.get('role') == 'assistant':
                for tc in m.get('tool_calls', []):
                    if tc.get('id') == tool_call_id:
                        return tc.get('function', {}).get('name', '')
        return ''

    # ------------------------------------------------------------------
    def _render_user_history(self, content: str):
        """渲染用户历史消息，长上下文自动折叠"""
        # 检查是否包含 [Network structure] 等上下文注入
        split_pos = -1
        header_tag = ''
        for tag in self._CONTEXT_HEADERS:
            pos = content.find(tag)
            if pos != -1:
                split_pos = pos
                header_tag = tag
                break

        if split_pos > 0 and len(content) > 300:
            # 用户实际输入 + 上下文注入
            user_text = content[:split_pos].strip()
            context_data = content[split_pos:]
            # 显示用户实际文字
            if user_text:
                self._add_user_message(user_text)
            # 上下文放进折叠区域
            resp = self._add_ai_response()
            resp.add_collapsible(header_tag.strip('[]'), context_data)
            resp.status_label.setText("上下文")
            resp.finalize()
            resp.status_label.setText("上下文")
        elif split_pos == 0 and len(content) > 300:
            # 纯上下文（无用户文字），整块折叠
            resp = self._add_ai_response()
            resp.add_collapsible(header_tag.strip('[]'), content)
            resp.status_label.setText("上下文")
            resp.finalize()
            resp.status_label.setText("上下文")
        else:
            self._add_user_message(content)

    # ------------------------------------------------------------------
    _TOOL_LINE_PREFIXES = ('[ok] ', '[err] ', '\u2705 ', '\u274c ')

    def _render_tool_summary_history(self, content: str, msg: dict = None):
        """渲染 [工具执行结果] 格式的 assistant 消息

        格式示例：
          [工具执行结果]
          [ok] get_network_structure: ## 网络结构: /obj
          网络类型: obj          ← 上一条的续行
          节点数量: 0            ← 上一条的续行
          [ok] create_node: /obj/geo1
        """
        if msg is None:
            msg = {}
        response = self._add_ai_response()

        # 先按行分组：以 [ok]/[err]/✅/❌ 开头的行开始新条目，
        # 其他行归到前一条目的续行
        entries = []  # [(first_line, [continuation_lines])]
        for line in content.split('\n'):
            stripped = line.strip()
            if not stripped or stripped == '[工具执行结果]':
                # 空行或标题→如果有上一条目，添加空行到续行（保留格式）
                if entries:
                    entries[-1][1].append('')
                continue
            is_new_entry = any(stripped.startswith(p) for p in self._TOOL_LINE_PREFIXES)
            if is_new_entry:
                entries.append((stripped, []))
            elif entries:
                entries[-1][1].append(stripped)
            # else: 没有前导条目的散行，忽略

        tool_count = 0
        for first_line, cont_lines in entries:
            t_name = 'unknown'
            success = True
            # 解析前缀
            rest = first_line
            for prefix in self._TOOL_LINE_PREFIXES:
                if first_line.startswith(prefix):
                    if 'err' in prefix or '\u274c' in prefix:
                        success = False
                    rest = first_line[len(prefix):]
                    break
            # 解析 tool_name: result
            if ':' in rest:
                parts = rest.split(':', 1)
                t_name = parts[0].strip()
                first_result = parts[1].strip() if len(parts) > 1 else ''
            else:
                first_result = rest

            # 合并续行
            all_parts = [first_result] + cont_lines
            t_result = '\n'.join(all_parts).strip()

            # 静默工具不显示在执行列表
            if t_name in self._SILENT_TOOLS:
                continue
            # 注册工具 + 设置结果
            response.add_status(f"[tool]{t_name}")
            tool_count += 1
            result_prefix = "[ok] " if success else "[err] "
            response.add_tool_result(t_name, f"{result_prefix}{t_result}")

        # 恢复 Shell 折叠面板
        self._restore_shell_widgets(response, msg)

        # 恢复 thinking
        thinking = msg.get('thinking', '')
        if thinking:
            response.add_thinking(thinking)
            response.thinking_section.finalize()

        # 恢复正文（[工具执行结果]之后可能还有 AI 正式回复）
        # 找到工具摘要之后的正文部分
        text_after_tools = ''
        parts = content.split('\n\n')
        for idx_p, part in enumerate(parts):
            if not part.strip().startswith('[工具执行结果]') and not any(
                part.strip().startswith(p) for p in self._TOOL_LINE_PREFIXES
            ):
                # 检查是否整段都是工具结果行
                is_tool_block = all(
                    any(line.strip().startswith(p) for p in self._TOOL_LINE_PREFIXES)
                    or not line.strip()
                    or line.strip() == '[工具执行结果]'
                    for line in part.split('\n')
                )
                if not is_tool_block and part.strip():
                    text_after_tools = '\n\n'.join(parts[idx_p:])
                    break
        if text_after_tools:
            response.set_content(text_after_tools)

        label_parts = []
        if thinking:
            label_parts.append("思考")
        label_parts.append(f"{tool_count}次调用")
        response.status_label.setText(f"历史 | {', '.join(label_parts)}")
        response.finalize()
        response.status_label.setText(f"历史 | {', '.join(label_parts)}")

    # ------------------------------------------------------------------
    def _restore_shell_widgets(self, response, msg: dict):
        """从历史消息中恢复 Python Shell / System Shell 折叠面板"""
        # 恢复 Python Shell
        for ps in msg.get('python_shells', []):
            code = ps.get('code', '')
            raw_output = ps.get('output', '')
            error = ps.get('error', '')
            success = ps.get('success', True)
            # 提取执行时间（和 _on_add_python_shell 相同逻辑）
            exec_time = 0.0
            clean_parts = []
            for line in raw_output.split('\n'):
                time_match = re.match(r'^执行时间:\s*([\d.]+)s$', line.strip())
                if time_match:
                    exec_time = float(time_match.group(1))
                    continue
                if line.strip() == '输出:':
                    continue
                clean_parts.append(line)
            clean_output = '\n'.join(clean_parts).strip()
            widget = PythonShellWidget(
                code=code, output=clean_output, error=error,
                exec_time=exec_time, success=success, parent=response
            )
            response.add_shell_widget(widget)

        # 恢复 System Shell
        for ss in msg.get('system_shells', []):
            command = ss.get('command', '')
            raw_output = ss.get('output', '')
            error = ss.get('error', '')
            success = ss.get('success', True)
            cwd = ss.get('cwd', '')
            exec_time = 0.0
            exit_code = 0
            stdout_parts = []
            for line in raw_output.split('\n'):
                tm = re.search(r'耗时:\s*([\d.]+)s', line)
                cm = re.search(r'退出码:\s*(\d+)', line)
                if tm:
                    exec_time = float(tm.group(1))
                if cm:
                    exit_code = int(cm.group(1))
                if tm or cm:
                    continue
                if line.strip() in ('--- stdout ---', '--- stderr ---'):
                    continue
                stdout_parts.append(line)
            clean_output = '\n'.join(stdout_parts).strip()
            widget = SystemShellWidget(
                command=command, output=clean_output, error=error,
                exit_code=exit_code, exec_time=exec_time,
                success=success, cwd=cwd, parent=response
            )
            response.add_sys_shell_widget(widget)

    # ------------------------------------------------------------------
    def _render_old_tool_msgs(self, response, tool_msgs: list):
        """渲染旧格式 role=tool 消息到 AIResponse"""
        for tm in tool_msgs:
            t_name = tm.get('name', 'unknown')
            t_content = tm.get('content', '')
            # 解析 tool_name:result_text
            if ':' in t_content:
                parts = t_content.split(':', 1)
                t_name = parts[0].strip() or t_name
                t_result = parts[1].strip() if len(parts) > 1 else t_content
            else:
                t_result = t_content
            # 静默工具不显示在执行列表
            if t_name in self._SILENT_TOOLS:
                continue
            success = not t_result.startswith('[err]') and not t_result.startswith('\u274c')
            # 先注册工具调用
            response.add_status(f"[tool]{t_name}")
            result_prefix = "[ok] " if success else "[err] "

            response.add_tool_result(t_name, f"{result_prefix}{t_result}")
