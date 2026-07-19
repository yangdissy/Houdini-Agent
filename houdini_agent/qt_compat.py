# -*- coding: utf-8 -*-
"""
Qt 兼容层 — 统一 PySide6 / PySide2 导入

Houdini 20.5 及之前版本自带 PySide2，Houdini 21+ 自带 PySide6。
所有模块统一从此处导入 QtWidgets / QtCore / QtGui / QSettings，
无需在每个文件中写 try/except。

用法:
    from houdini_agent.qt_compat import QtWidgets, QtCore, QtGui, QSettings
"""

try:
    from PySide6 import QtWidgets, QtCore, QtGui          # noqa: F401
    from PySide6.QtCore import QSettings                   # noqa: F401
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui          # noqa: F401
    from PySide2.QtCore import QSettings                   # noqa: F401
    PYSIDE_VERSION = 2

# ---- C++ 对象存活检查（shiboken）----
# 用于判断一个 QObject 底层 C++ 实例是否已被删除（deleteLater 后）。
# 若延迟回调（QTimer.singleShot）在 widget 销毁后才执行，直接触碰它会
# 导致对半销毁对象计算布局/sizeHint，触发 Houdini Qt messageHandler 崩溃。
try:
    if PYSIDE_VERSION == 6:
        from shiboken6 import isValid as _shiboken_is_valid  # noqa: F401
    else:
        from shiboken2 import isValid as _shiboken_is_valid  # noqa: F401
except ImportError:
    _shiboken_is_valid = None


def is_qobject_alive(obj) -> bool:
    """返回 True 当且仅当 obj 的底层 C++ QObject 仍存活。

    obj 为 None 时返回 False。若 shiboken 不可用则退回到 True
    （无法判断时按存活处理，保持旧行为）。
    """
    if obj is None:
        return False
    if _shiboken_is_valid is None:
        return True
    try:
        return bool(_shiboken_is_valid(obj))
    except Exception:
        return False


_accessibility_disabled = False


def disable_accessibility_bridge() -> bool:
    """禁用 Qt 无障碍（Accessibility）桥接，规避 Windows UIAutomation 崩溃。

    根因：在 Houdini + PySide2 + 中文输入法（如腾讯 WeType）环境下，
    频繁的 QWidget.setText() 会触发 QAccessible::updateAccessibility →
    UiaRaiseAutomationEvent，与输入法的 UIAutomation 线程争用，
    导致 signal 11（段错误）。禁用无障碍桥接可从源头消除该事件流，
    对本工具功能无影响。

    幂等：多次调用只生效一次。返回 True 表示已成功禁用（或先前已禁用）。
    """
    global _accessibility_disabled
    if _accessibility_disabled:
        return True
    try:
        QAccessible = getattr(QtGui, 'QAccessible', None)
        if QAccessible is not None and hasattr(QAccessible, 'setActive'):
            QAccessible.setActive(False)
            _accessibility_disabled = True
            return True
    except Exception:
        pass
    return False


def safe_single_shot(msec: int, receiver, method_name: str):
    """QTimer.singleShot 的安全封装：回调执行前先校验 receiver 存活。

    专用于延迟布局刷新（_update_height / _scroll_to_bottom / _maybe_collapse 等）。
    若 receiver 在回调触发前已被 deleteLater，则跳过，避免对半销毁 widget
    计算布局导致崩溃。

    Args:
        msec: 延迟毫秒数（通常 0）
        receiver: 拥有该方法的 QObject
        method_name: 要调用的方法名（字符串，避免过早绑定已销毁对象）
    """
    def _guarded():
        if not is_qobject_alive(receiver):
            return
        method = getattr(receiver, method_name, None)
        if method is None:
            return
        method()

    QtCore.QTimer.singleShot(msec, _guarded)


def invoke_on_main(receiver, slot_name: str, *args):
    """线程安全地在主线程调用 slot（兼容 PySide2 / PySide6）

    PySide6 支持 QMetaObject.invokeMethod + Q_ARG，
    PySide2 不支持 Q_ARG，改用 QTimer.singleShot(0, lambda)。

    Args:
        receiver: 目标 QObject（仅 PySide6 使用）
        slot_name: slot 方法名
        *args: 传递给 slot 的参数
    """
    if PYSIDE_VERSION == 6:
        q_args = [QtCore.Q_ARG(type(a), a) for a in args]
        QtCore.QMetaObject.invokeMethod(
            receiver, slot_name,
            QtCore.Qt.QueuedConnection,
            *q_args
        )
    else:
        # PySide2: 通过 QTimer.singleShot 排队到主线程
        method = getattr(receiver, slot_name)
        QtCore.QTimer.singleShot(0, lambda: method(*args))
