# -*- coding: utf-8 -*-
"""测试公共配置：确保仓库根目录在 sys.path 上，使 houdini_agent / shared 可导入。

这些测试只覆盖不依赖 Houdini (`hou`) 的纯逻辑模块。
既可用 pytest 运行，也可用标准库 unittest 运行：

    python -m pytest tests/
    python -m unittest discover -s tests
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
