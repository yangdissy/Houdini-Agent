# -*- coding: utf-8 -*-
"""测试包：将仓库根目录加入 sys.path，使 houdini_agent / shared 可导入。"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
