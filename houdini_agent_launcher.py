"""
Houdini Agent - Launcher
"""

import sys
import os
import importlib

# ============================================================

def _is_dev_reload_enabled():
    """Return True when development hot-reload is explicitly enabled."""
    value = os.getenv("HOUDINI_AGENT_DEV_RELOAD", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _cleanup_legacy_modules():
    """Remove old package names left from previous product names."""
    old_mods = [k for k in sys.modules if k.startswith('HOUDINI_HIP_MANAGER')]
    for k in old_mods:
        del sys.modules[k]
# 强制使用本地 lib 目录中的依赖库
# ============================================================
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
_LIB_DIR = os.path.join(_ROOT_DIR, 'lib')

_PYTHON_LIB_NAME = f'python{sys.version_info.major}{sys.version_info.minor}'
_VERSIONED_LIB_CANDIDATES = (
    os.path.join(_LIB_DIR, f'{_PYTHON_LIB_NAME}_embed_complete'),
    os.path.join(_LIB_DIR, f'{_PYTHON_LIB_NAME}_embed'),
    os.path.join(_LIB_DIR, _PYTHON_LIB_NAME),
)
_VERSIONED_LIB_DIR = next(
    (path for path in _VERSIONED_LIB_CANDIDATES if os.path.isdir(path)),
    _VERSIONED_LIB_CANDIDATES[-1],
)

if os.path.exists(_LIB_DIR):
    if _LIB_DIR in sys.path:
        sys.path.remove(_LIB_DIR)
    sys.path.insert(0, _LIB_DIR)
if os.path.exists(_VERSIONED_LIB_DIR):
    if _VERSIONED_LIB_DIR in sys.path:
        sys.path.remove(_VERSIONED_LIB_DIR)
    sys.path.insert(0, _VERSIONED_LIB_DIR)

# ============================================================

def detect_dcc():
    """检测当前运行的 DCC 软件"""
    try:
        import hou
        return "houdini"
    except ImportError:
        pass
    
    return None

def launch_houdini_agent():
    """启动 Houdini Agent"""
    import importlib.util

    root_path = os.path.dirname(os.path.abspath(__file__))
    tool_path = os.path.join(root_path, "houdini_agent")

    # 把根目录加入 sys.path，使 shared、plugins 等顶级包可被找到
    if root_path not in sys.path:
        sys.path.insert(0, root_path)

    _cleanup_legacy_modules()

    if not _is_dev_reload_enabled():
        try:
            main = importlib.import_module("houdini_agent.main")
            return main.show_tool()
        except Exception as e:
            print(f"Failed to launch Houdini Agent: {e}")
            import traceback
            traceback.print_exc()
            return None

    # 开发模式：清理整个包，确保新拆分出的 mixin、Registry 和 schema 都从磁盘重载。
    for mod_name in list(sys.modules.keys()):
        if mod_name == 'main' or mod_name == 'houdini_agent' or mod_name.startswith('houdini_agent.'):
            del sys.modules[mod_name]

    try:
        # 注册顶级包的通用函数
        def _register_pkg(pkg_name, pkg_dir):
            init_file = os.path.join(pkg_dir, "__init__.py")
            spec = importlib.util.spec_from_file_location(
                pkg_name, init_file,
                submodule_search_locations=[pkg_dir]
            )
            mod = importlib.util.module_from_spec(spec)
            mod.__path__ = [pkg_dir]
            mod.__package__ = pkg_name
            sys.modules[pkg_name] = mod
            spec.loader.exec_module(mod)
            return mod

        # 注册 houdini_agent 包
        _register_pkg("houdini_agent", tool_path)

        # 注册 shared 包
        shared_path = os.path.join(root_path, "shared")
        _register_pkg("shared", shared_path)

        # 注册 plugins 包（如果存在）
        plugins_path = os.path.join(root_path, "plugins")
        if os.path.isdir(plugins_path):
            _register_pkg("plugins", plugins_path)

        # 加载 main，明确设置 __package__ 为 houdini_agent
        _main_file = os.path.join(tool_path, "main.py")
        _spec = importlib.util.spec_from_file_location(
            "houdini_agent.main", _main_file,
            submodule_search_locations=[]
        )
        main = importlib.util.module_from_spec(_spec)
        main.__package__ = "houdini_agent"
        sys.modules["houdini_agent.main"] = main
        sys.modules["main"] = main
        _spec.loader.exec_module(main)

        # launcher 已完整重建包；避免 main.show_tool() 再做一次局部 reload，
        # 否则 ai_tab 可能绑定到新旧 mixin 类的混合版本。
        previous_dev_reload = os.environ.get("HOUDINI_AGENT_DEV_RELOAD")
        os.environ["HOUDINI_AGENT_DEV_RELOAD"] = "0"
        try:
            return main.show_tool()
        finally:
            if previous_dev_reload is None:
                os.environ.pop("HOUDINI_AGENT_DEV_RELOAD", None)
            else:
                os.environ["HOUDINI_AGENT_DEV_RELOAD"] = previous_dev_reload
    except Exception as e:
        print(f"Failed to launch Houdini Agent: {e}")
        import traceback
        traceback.print_exc()
        return None

def launch():
    """自动检测并启动"""
    dcc = detect_dcc()
    
    if dcc == "houdini":
        print("Houdini detected, launching Houdini Agent...")
        return launch_houdini_agent()
    else:
        print("Error: Houdini not detected.")
        print("Please run this tool inside Houdini.")
        return None

# 全局变量存储窗口实例
_agent_window = None

def show_tool():
    """统一入口函数"""
    global _agent_window
    _agent_window = launch()
    return _agent_window

if __name__ == "__main__":
    show_tool()
