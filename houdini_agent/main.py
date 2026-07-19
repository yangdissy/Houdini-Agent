import os
import sys
import hou
from houdini_agent.qt_compat import QtWidgets


def _is_dev_reload_enabled():
    """Return True when development hot-reload is explicitly enabled."""
    value = os.getenv("HOUDINI_AGENT_DEV_RELOAD", "").strip().lower()
    return value in {"1", "true", "yes", "on"}

# 开发模式下重新加载模块，避免缓存问题
def _reload_modules():
    # ---- 清理旧包名残留（HOUDINI_HIP_MANAGER → houdini_agent 迁移） ----
    old_mods = [k for k in sys.modules if k.startswith('HOUDINI_HIP_MANAGER')]
    for k in old_mods:
        del sys.modules[k]
    
    modules_to_reload = [
        'houdini_agent.qt_compat',  # ★ Qt 兼容层最先重载
        'houdini_agent.utils.token_optimizer',
        'houdini_agent.utils.ultra_optimizer',
        'houdini_agent.utils.training_data_exporter',
        'houdini_agent.utils.updater',
        'houdini_agent.utils.hooks',
        'houdini_agent.utils.tool_registry',
        'houdini_agent.utils.rules_manager',
        'houdini_agent.utils.ai_client',
        'houdini_agent.utils.mcp.client',
        'houdini_agent.utils.mcp',
        'houdini_agent.ui.i18n',
        'houdini_agent.ui.cursor_widgets',
        # ★ 新增：拆分出的 mixin 模块也需要重载，否则引用旧类导致异常
        'houdini_agent.ui.font_settings_dialog',
        'houdini_agent.ui.header',
        'houdini_agent.ui.input_area',
        'houdini_agent.ui.chat_view',
        'houdini_agent.core.agent_runner',
        'houdini_agent.core.session_manager',
        'houdini_agent.ui.ai_tab',
        'houdini_agent.core.main_window',
    ]
    for mod_name in modules_to_reload:
        if mod_name in sys.modules:
            try:
                import importlib
                importlib.reload(sys.modules[mod_name])
            except Exception:
                pass

from houdini_agent.core.main_window import MainWindow
from houdini_agent.ui.login_dialog import LoginDialog
from shared.user_paths import is_user_allowed

_main_window = None

def show_tool(username: str = None, force_login: bool = False):
    global _main_window, MainWindow
    
    if _is_dev_reload_enabled():
        _reload_modules()
        try:
            from houdini_agent.core.main_window import MainWindow as _MW
            MainWindow = _MW
        except Exception:
            pass
    
    if not QtWidgets.QApplication.instance():
        app = QtWidgets.QApplication([])
    else:
        app = QtWidgets.QApplication.instance()

    # ★ 禁用 Qt 无障碍桥接：规避 Windows UIAutomation 与中文输入法(WeType)
    #   争用导致的 setText → QAccessible::updateAccessibility 段错误崩溃。
    try:
        from houdini_agent.qt_compat import disable_accessibility_bridge
        disable_accessibility_bridge()
    except Exception:
        pass

    try:
        if _main_window is not None:
            if _main_window.isVisible():
                _main_window.raise_()
                _main_window.activateWindow()
                return _main_window
            else:
                # ★ 旧窗口标记为 stale，防止其 atexit 回调在 Houdini 退出时
                #   以旧数据覆盖新窗口写入的 manifest/session 文件
                try:
                    if hasattr(_main_window, 'ai_tab') and _main_window.ai_tab:
                        _main_window.ai_tab._ai_tab_active = False
                        try:
                            _main_window.ai_tab._auto_save_timer.stop()
                        except Exception:
                            pass
                        try:
                            _main_window.ai_tab.cleanup()
                        except Exception:
                            pass
                    _main_window._already_saved = True  # 禁止旧 MainWindow atexit 再保存
                except Exception:
                    pass
                _main_window.force_quit = True
                _main_window.close()
                # ★ 显式隐藏，确保已进入删除流程的旧窗口及其子按钮不再参与
                #   任何残留的布局/绘制事件（配合 safe_single_shot 存活守卫）。
                try:
                    _main_window.hide()
                except Exception:
                    pass
                _main_window.deleteLater()
                _main_window = None
                # ★ 不要 processEvents()，它会触发队列中残留的事件导致窗口闪烁
    except Exception:
        _main_window = None

    try:
        if force_login or not username:
            dlg = LoginDialog(parent=None)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return None
            username = dlg.get_username()
        if not username:
            return None
        if not is_user_allowed(username):
            QtWidgets.QMessageBox.information(None, "Houdini Agent", "当前用户未启用访问权限。", QtWidgets.QMessageBox.Ok)
            return None

        _main_window = MainWindow(username=username)
        _main_window.show()
        _main_window.raise_()
        _main_window.activateWindow()
        return _main_window
    except Exception as e:
        QtWidgets.QMessageBox.critical(None, "Error", f"Failed to create Houdini Agent window:\n{e}", QtWidgets.QMessageBox.Ok)
        return None

if __name__ == "__main__":
    show_tool()
