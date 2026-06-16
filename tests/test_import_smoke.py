# -*- coding: utf-8 -*-
"""导入冒烟测试 —— 重构安全网。

逐个导入 houdini_agent 下的所有子模块，确保：
- 没有语法错误
- 没有循环导入
- 拆分模块后所有 re-export 仍然可用

由于测试环境没有 Houdini，`hou` 用 MagicMock 桩替代；
仅验证「可导入」，不实例化任何 QWidget（无需 QApplication）。
"""

import importlib
import pkgutil
import sys
import unittest
from unittest import mock

import houdini_agent


def _install_hou_stub():
    """安装 hou 桩模块，使依赖 hou 的模块可在无 Houdini 环境下导入。"""
    if "hou" not in sys.modules:
        sys.modules["hou"] = mock.MagicMock(name="hou")


def _install_thirdparty_stubs():
    """桩替第三方网络依赖。

    捆绑的 lib/ 依赖（requests / urllib3 等）面向 Houdini 内置 Python（3.9+），
    在更低版本的测试解释器上可能无法导入。本冒烟测试只关心 houdini_agent
    自身的模块结构，因此用桩模块替代这些纯运行时依赖。
    """
    for name in ("requests", "trafilatura"):
        if name not in sys.modules:
            sys.modules[name] = mock.MagicMock(name=name)


def _install_qt_stubs():
    """安装 PySide 桩模块，使 UI 模块可在无 Qt 环境下静态导入。"""
    class _QtBase:
        def __init__(self, *args, **kwargs):
            pass

    class _QtObject:
        def __init__(self, *args, **kwargs):
            pass

    class _QSettingsStub:
        def __init__(self, *args, **kwargs):
            self._values = {}

        def value(self, key, default=None):
            return self._values.get(key, default)

        def setValue(self, key, value):
            self._values[key] = value

    class _Signal:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self, *args, **kwargs):
            pass

        def emit(self, *args, **kwargs):
            pass

    class _QtValue:
        value = 0

        def __or__(self, other):
            return self

        def __and__(self, other):
            return self

        def __int__(self):
            return 0

    class _QtEnum:
        Window = _QtValue()
        WindowStaysOnTopHint = _QtValue()
        QueuedConnection = _QtValue()
        BlockingQueuedConnection = _QtValue()

        def __getattr__(self, name):
            return _QtValue()

    def _slot(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    for package_name in ("PySide6", "PySide2"):
        if package_name in sys.modules:
            continue
        package = mock.MagicMock(name=package_name)
        qt_core = mock.MagicMock(name=f"{package_name}.QtCore")
        qt_widgets = mock.MagicMock(name=f"{package_name}.QtWidgets")
        qt_gui = mock.MagicMock(name=f"{package_name}.QtGui")
        qt_core.QObject = _QtObject
        qt_core.QTimer = _QtBase
        qt_core.QSettings = _QSettingsStub
        qt_core.Signal = _Signal
        qt_core.Slot = _slot
        qt_core.Qt = _QtEnum
        qt_widgets.QWidget = _QtBase
        qt_widgets.QMainWindow = _QtBase
        qt_widgets.QDialog = _QtBase
        qt_widgets.QFrame = _QtBase
        qt_widgets.QLabel = _QtBase
        qt_widgets.QPushButton = _QtBase
        qt_widgets.QTextEdit = _QtBase
        qt_widgets.QPlainTextEdit = _QtBase
        qt_widgets.QLineEdit = _QtBase
        qt_widgets.QComboBox = _QtBase
        qt_widgets.QScrollArea = _QtBase
        qt_widgets.QTabWidget = _QtBase
        qt_widgets.QApplication = _QtBase
        qt_widgets.QVBoxLayout = _QtBase
        qt_widgets.QHBoxLayout = _QtBase
        qt_widgets.QGridLayout = _QtBase
        qt_gui.QColor = _QtBase
        qt_gui.QBrush = _QtBase
        qt_gui.QPen = _QtBase
        qt_gui.QFont = _QtBase
        qt_gui.QPixmap = _QtBase
        qt_gui.QPainter = _QtBase
        package.QtCore = qt_core
        package.QtWidgets = qt_widgets
        package.QtGui = qt_gui
        sys.modules[package_name] = package
        sys.modules[f"{package_name}.QtCore"] = qt_core
        sys.modules[f"{package_name}.QtWidgets"] = qt_widgets
        sys.modules[f"{package_name}.QtGui"] = qt_gui



def _iter_submodules(package):
    """递归产出包内所有子模块的全限定名。"""
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        yield info.name


# 已知需要真实 Houdini / 运行环境、无法在 CI 静态导入的模块（按需补充）
# QUICK_SHELF_CODE / shelf_tool 是粘贴到 Houdini 货架的启动片段（`import main`），
# 依赖运行期 sys.path，本就不是可导入模块。
_SKIP = {
    "houdini_agent.QUICK_SHELF_CODE",
    "houdini_agent.shelf_tool",
}


class ImportSmokeTest(unittest.TestCase):
    def test_all_submodules_importable(self):
        _install_hou_stub()
        _install_thirdparty_stubs()
        _install_qt_stubs()
        failures = []
        for name in _iter_submodules(houdini_agent):
            if name in _SKIP:
                continue
            try:
                importlib.import_module(name)
            except Exception as e:  # noqa: BLE001 - 汇总所有导入错误一次性报告
                failures.append(f"{name}: {type(e).__name__}: {e}")
        self.assertEqual(
            failures, [],
            "以下模块导入失败:\n" + "\n".join(failures),
        )


if __name__ == "__main__":
    unittest.main()
