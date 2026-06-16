"""
Shared Utilities for Houdini Agent
"""

import os
from datetime import datetime

from .user_paths import UserPaths, normalize_username

def get_repo_root(start_dir=None):
    """获取仓库根目录（包含 README.md 的目录作为仓库根）"""
    try:
        current = start_dir or os.path.dirname(os.path.abspath(__file__))
        # 向上查找直到找到 README.md 或到达磁盘根
        while True:
            if os.path.exists(os.path.join(current, "README.md")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    except Exception:
        pass
    # 退化：使用本文件的上级两级
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_config_dir():
    """获取统一配置目录: <repo_root>/config"""
    repo_root = get_repo_root()
    config_dir = os.path.join(repo_root, "config")
    os.makedirs(config_dir, exist_ok=True)
    return config_dir

def get_cache_dir():
    """获取统一缓存目录: <repo_root>/cache"""
    repo_root = get_repo_root()
    cache_dir = os.path.join(repo_root, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def load_config(config_name, dcc_type=None):
    """加载配置文件
    
    Args:
        config_name: 配置名称
        dcc_type: DCC 类型 ('houdini', 'maya')，如果为 None 则加载共享配置
    """
    config_dir = get_config_dir()
    
    if dcc_type:
        config_file = f"{dcc_type}_{config_name}.ini"
    else:
        config_file = f"{config_name}.ini"
    
    config_path = os.path.join(config_dir, config_file)
    config = {}
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines:
                    if ":" in line:
                        key, value = line.strip().split(":", 1)
                        config[key] = value
        except Exception as e:
            print(f"加载配置失败: {e}")
    
    return config, config_path

def save_config(config_name, config, dcc_type=None):
    """保存配置文件
    
    Args:
        config_name: 配置名称
        config: 配置字典
        dcc_type: DCC 类型 ('houdini', 'maya')
    """
    config_dir = get_config_dir()
    
    if dcc_type:
        config_file = f"{dcc_type}_{config_name}.ini"
    else:
        config_file = f"{config_name}.ini"
    
    config_path = os.path.join(config_dir, config_file)
    
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            for key, value in config.items():
                f.write(f"{key}:{value}\n")
        return True, config_path
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False, ""


# API key 字段永远不允许出现在全局共享配置文件中
# 只能存放在各用户自己的 cache/users/{username}/config.ini 或通过环境变量注入
_SENSITIVE_CONFIG_KEYS = frozenset({
    'openai_api_key', 'deepseek_api_key', 'glm_api_key',
    'duojie_api_key', 'openrouter_api_key', 'kimi_coding_api_key',
    'siliconflow_api_key', 'of3d_api_key', 'custom_api_key',
})


def _load_ini_file(path: str) -> dict:
    data = {}
    if not os.path.exists(path):
        return data
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                if ":" in line:
                    key, value = line.strip().split(":", 1)
                    data[key] = value
    except Exception as e:
        print(f"加载配置失败: {e}")
    return data


def load_user_config(username: str, config_name: str = "ai", dcc_type: str = "houdini"):
    """加载用户配置（全局配置 + 用户覆盖层）。

    全局配置只提供非敏感设置（URL、模型名等），API key 等敏感字段
    仅从用户私有配置 cache/users/{username}/config.ini 读取。
    """
    global_cfg, _ = load_config(config_name, dcc_type=dcc_type)
    # 从全局配置中过滤掉敏感字段，防止共享文件泄露 API key
    merged = {k: v for k, v in (global_cfg or {}).items()
              if k not in _SENSITIVE_CONFIG_KEYS}
    try:
        uname = normalize_username(username)
    except Exception:
        return merged, ""

    user_path = UserPaths(uname).user_config_path()
    user_cfg = _load_ini_file(str(user_path))
    if user_cfg:
        merged.update(user_cfg)
    return merged, str(user_path)


def save_user_config(username: str, config: dict, config_name: str = "ai", dcc_type: str = "houdini"):
    """保存用户配置覆盖层（不修改全局配置）。"""
    try:
        uname = normalize_username(username)
    except Exception:
        return False, ""

    user_path = UserPaths(uname).user_config_path()
    user_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(user_path, "w", encoding="utf-8") as f:
            for key, value in config.items():
                f.write(f"{key}:{value}\n")
        return True, str(user_path)
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False, ""

def get_history_path(history_name, dcc_type=None):
    """获取历史记录文件路径"""
    config_dir = get_config_dir()
    
    if dcc_type:
        history_file = f"{dcc_type}_{history_name}_history.txt"
    else:
        history_file = f"{history_name}_history.txt"
    
    return os.path.join(config_dir, history_file)

def add_to_history(history_name, entry, dcc_type=None):
    """添加记录到历史文件"""
    try:
        history_path = get_history_path(history_name, dcc_type)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(history_path, "a", encoding="utf-8") as f:
            f.write(f"{entry}|{timestamp}\n")
        return True
    except Exception as e:
        print(f"添加历史记录失败: {e}")
        return False

def load_history(history_name, dcc_type=None):
    """加载历史记录"""
    try:
        history_path = get_history_path(history_name, dcc_type)
        if not os.path.exists(history_path):
            return []
            
        with open(history_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        history = []
        for line in lines:
            if "|" in line:
                parts = line.strip().split("|")
                history.append(parts)
                
        return history
    except Exception as e:
        print(f"加载历史记录失败: {e}")
        return []
