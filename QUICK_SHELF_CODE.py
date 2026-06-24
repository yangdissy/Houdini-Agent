import sys, os, importlib.util

# 开发测试预设：1=启用热重载，0=普通稳定启动
HOUDINI_AGENT_DEV_RELOAD = "0"
os.environ["HOUDINI_AGENT_DEV_RELOAD"] = HOUDINI_AGENT_DEV_RELOAD

if sys.platform.startswith('win'):
    launcher_file = r"U:\CG_VFX\sfxLib\sfx_third_party\houdini\extensions\Houdini-Agent\houdini_agent_launcher.py"
else:
    launcher_file = r"/mnt/CG_VFX/sfxLib/sfx_third_party/houdini/extensions/Houdini-Agent/houdini_agent_launcher.py"

mod_name = "houdini_agent_launcher"
# 每次都重新从文件加载，避免 spec 丢失导致 reload 报错
if mod_name in sys.modules:
    del sys.modules[mod_name]

spec = importlib.util.spec_from_file_location(mod_name, launcher_file)
mod = importlib.util.module_from_spec(spec)
sys.modules[mod_name] = mod
spec.loader.exec_module(mod)

mod.show_tool()