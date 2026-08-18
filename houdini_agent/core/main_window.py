# -*- coding: utf-8 -*-
"""
Houdini Agent - 主窗口
支持工作区保存/恢复（窗口状态 + 上下文缓存）
"""

import os
import json
import atexit
import hou
import shutil
from datetime import datetime
from pathlib import Path
from houdini_agent.qt_compat import QtWidgets, QtGui, QtCore
from houdini_agent.ui.ai_tab import AITab
from shared.user_paths import UserPaths, is_user_allowed


class MainWindow(QtWidgets.QMainWindow):
    """Houdini Agent 主窗口"""
    
    def __init__(self, username: str, parent=None):
        # 尝试获取 Houdini 主窗口作为父窗口
        if parent is None:
            try:
                parent = hou.qt.mainWindow()
            except Exception:
                pass
        
        super().__init__(parent)
        self._username = username
        self.setWindowTitle(f"Houdini Agent [{self._username}]")
        self.setMinimumSize(420, 600)
        
        # 工作区配置目录
        user_paths = UserPaths(self._username)
        user_paths.ensure_dirs()
        self._workspace_dir = user_paths.workspace_dir()
        self._workspace_file = user_paths.workspace_file()
        
        # 不使用 WindowStaysOnTopHint，让窗口与 Houdini 同层级
        self.setWindowFlags(QtCore.Qt.Window)
        
        # 深邃蓝黑背景（与 aiTab glassmorphism 主题匹配）
        self.setStyleSheet("QMainWindow { background-color: #0a0a12; }")
        
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        
        self.force_quit = False
        self._already_saved = False  # 防止重复保存
        
        self.init_ui(central_widget)

        # 迁移提示（仅首次）
        self._maybe_offer_migration(user_paths)
        
        # 加载工作区（窗口状态 + 上下文）
        self._load_workspace()
        
        # 注册多重退出保存钩子（确保 Houdini 退出时能保存）
        # 1. QApplication.aboutToQuit（Qt 正常退出时触发）
        app = QtWidgets.QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._on_app_about_to_quit)
        # 2. atexit（Python 解释器关闭时触发）
        atexit.register(self._atexit_save)
        # 3. Houdini 专用：监听 hipFile 事件（切换场景时也保存）
        try:
            hou.hipFile.addEventCallback(self._on_hip_event)
        except Exception:
            pass

    def init_ui(self, central_widget):
        """初始化UI"""
        layout = QtWidgets.QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._central_layout = layout
        self.ai_tab = AITab(workspace_dir=self._workspace_dir, username=self._username)
        layout.addWidget(self.ai_tab)

    def switch_user(self, username: str):
        """切换用户：保存当前状态并重建 AITab。"""
        if not is_user_allowed(username):
            QtWidgets.QMessageBox.information(self, "切换用户", "当前用户未启用访问权限。")
            return

        try:
            # 先保存当前用户的会话与窗口状态
            self._save_workspace()
        except Exception:
            pass

        self._username = username
        self.setWindowTitle(f"Houdini Agent [{self._username}]")
        user_paths = UserPaths(self._username)
        user_paths.ensure_dirs()
        self._workspace_dir = user_paths.workspace_dir()
        self._workspace_file = user_paths.workspace_file()

        # 替换 AITab
        if hasattr(self, 'ai_tab') and self.ai_tab:
            old_tab = self.ai_tab
            try:
                old_tab._auto_save_timer.stop()
            except Exception:
                pass
            old_tab._ai_tab_active = False
            try:
                old_tab.cleanup()
            except Exception:
                pass
            # ★ 先隐藏再从父布局摘除，避免已 deleteLater 的旧 AITab 继续参与
            #   布局/绘制事件，导致对半销毁 widget 计算 sizeHint 崩溃。
            try:
                old_tab.hide()
            except Exception:
                pass
            old_tab.setParent(None)
            old_tab.deleteLater()
        self.ai_tab = AITab(workspace_dir=self._workspace_dir, username=self._username)
        self._central_layout.addWidget(self.ai_tab)

        # 迁移提示与加载新用户工作区
        self._maybe_offer_migration(user_paths)
        self._load_workspace()
        self._already_saved = False

    def _maybe_offer_migration(self, user_paths: UserPaths):
        """检测旧 cache 并提示迁移（复制，不删除）。"""
        try:
            flag_path = user_paths.migration_flag_path()
            if flag_path.exists():
                return

            legacy_cache = user_paths.legacy_cache_dir()
            legacy_conversations = legacy_cache / "conversations"
            legacy_memory = legacy_cache / "memory"
            legacy_workspace = legacy_cache / "workspace" / "workspace.json"

            has_legacy = any([
                legacy_conversations.exists(),
                legacy_memory.exists(),
                legacy_workspace.exists(),
            ])
            if not has_legacy:
                return

            reply = QtWidgets.QMessageBox.question(
                self,
                "迁移旧数据",
                (
                    "检测到旧版本缓存数据。\n"
                    "是否将旧数据复制到当前用户目录？\n\n"
                    "注意：仅复制，不会删除旧数据。"
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            migrated = False
            if reply == QtWidgets.QMessageBox.Yes:
                self._copy_legacy_data(legacy_conversations, user_paths.conversations_dir())
                self._copy_legacy_data(legacy_memory, user_paths.memory_dir())
                if legacy_workspace.exists():
                    user_paths.workspace_dir().mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(legacy_workspace), str(user_paths.workspace_file()))
                migrated = True

            flag_path.parent.mkdir(parents=True, exist_ok=True)
            with open(flag_path, "w", encoding="utf-8") as f:
                json.dump({
                    "migrated": migrated,
                    "timestamp": datetime.now().isoformat(),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Migration] Failed: {e}")

    def _copy_legacy_data(self, src: Path, dst: Path):
        if not src.exists():
            return
        dst.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            for item in src.iterdir():
                s = src / item.name
                d = dst / item.name
                if s.is_dir():
                    if not d.exists():
                        d.mkdir(parents=True, exist_ok=True)
                    self._copy_legacy_data(s, d)
                else:
                    if d.exists():
                        continue
                    try:
                        shutil.copy2(str(s), str(d))
                    except Exception:
                        pass
        else:
            try:
                if not dst.exists():
                    shutil.copy2(str(src), str(dst))
            except Exception:
                pass

    def force_quit_application(self):
        """强制退出应用程序"""
        self.force_quit = True
        self.close()

    def _save_workspace(self):
        """保存工作区（窗口状态 + 所有会话缓存）"""
        try:
            geometry = self.geometry()
            window_state = {
                'x': geometry.x(),
                'y': geometry.y(),
                'width': geometry.width(),
                'height': geometry.height(),
                'is_maximized': self.isMaximized()
            }
            
            has_sessions = False
            tab_count = 0
            if hasattr(self, 'ai_tab') and self.ai_tab:
                has_sessions = self.ai_tab._save_all_sessions()
                tab_count = self.ai_tab.session_tabs.count()
            
            workspace_data = {
                'version': '1.1',
                'window_state': window_state,
                'cache_info': {
                    'has_conversation': has_sessions,
                    'tab_count': tab_count,
                    'use_manifest': True,
                }
            }
            
            with open(self._workspace_file, 'w', encoding='utf-8') as f:
                json.dump(workspace_data, f, ensure_ascii=False, indent=2)
            
            print(f"[Workspace] Saved: window({window_state['width']}x{window_state['height']}), {tab_count} session tabs")
            
        except Exception as e:
            print(f"[Workspace] Save failed: {str(e)}")
    
    def _load_workspace(self):
        """加载工作区（窗口状态 + 上下文缓存）"""
        try:
            if not self._workspace_file.exists():
                self.resize(450, 700)
                return
            
            with open(self._workspace_file, 'r', encoding='utf-8') as f:
                workspace_data = json.load(f)
            
            window_state = workspace_data.get('window_state', {})
            if window_state:
                x = window_state.get('x', 100)
                y = window_state.get('y', 100)
                width = window_state.get('width', 450)
                height = window_state.get('height', 700)
                is_maximized = window_state.get('is_maximized', False)
                
                self.setGeometry(x, y, width, height)
                if is_maximized:
                    self.setWindowState(QtCore.Qt.WindowMaximized)
            
            cache_info = workspace_data.get('cache_info', {})
            # ★ 始终尝试恢复（不再依赖 has_conversation 标志，
            #   即使上次退出时所有会话为空，manifest 或 cache_latest 中可能仍有内容）
            if hasattr(self, 'ai_tab'):
                # 延迟 200ms 确保 UI 完全初始化完毕
                QtCore.QTimer.singleShot(200, self._load_workspace_cache)
            
            print(f"[Workspace] Loaded: {self._workspace_file}")
            
        except Exception as e:
            print(f"[Workspace] Load failed: {str(e)}")
            self.resize(450, 700)
    
    def _load_workspace_cache(self):
        """延迟加载工作区缓存"""
        try:
            if not hasattr(self, 'ai_tab'):
                return
            
            if self.ai_tab._restore_all_sessions():
                return
            
            cache_dir = self.ai_tab._cache_dir
            latest_cache = cache_dir / "cache_latest.json"
            if latest_cache.exists():
                self.ai_tab._load_cache_silent(latest_cache)
        except Exception as e:
            print(f"[Workspace] Cache load failed: {str(e)}")
    
    def _on_app_about_to_quit(self):
        self._save_workspace_once()
    
    def _atexit_save(self):
        self._save_workspace_once()
    
    def _on_hip_event(self, event_type):
        try:
            if event_type in (hou.hipFileEventType.BeforeClear,
                              hou.hipFileEventType.BeforeLoad):
                self._save_workspace_once()
        except Exception:
            pass
    
    def _save_workspace_once(self):
        """确保退出时只保存一次（aboutToQuit / atexit / closeEvent 都可能触发）"""
        if self._already_saved:
            return
        self._already_saved = True  # ★ 不在 finally 中重置，确保只执行一次
        try:
            self._save_workspace()
        except Exception as e:
            print(f"[Workspace] Exit save failed: {e}")
    
    def closeEvent(self, event):
        # ★ 使用 _save_workspace_once() 而不是 _save_workspace()：
        #   当 show_tool() 替换旧窗口时会预先设 _already_saved=True，
        #   防止旧窗口 closeEvent 用旧数据覆盖新窗口刚写好的 manifest。
        #   普通关闭（用户点 X）时 _already_saved=False，行为与之前完全一致。
        self._save_workspace_once()
        event.accept()
        super().closeEvent(event)
