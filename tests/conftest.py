# -*- coding: utf-8 -*-
"""测试公共配置：确保仓库根目录在 sys.path 上，使 houdini_agent / shared 可导入。

这些测试只覆盖不依赖 Houdini (`hou`) 的纯逻辑模块。
既可用 pytest 运行，也可用标准库 unittest 运行：

    python -m pytest tests/
    python -m unittest discover -s tests
"""

import os
from pathlib import Path
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def pytest_addoption(parser):
    group = parser.getgroup("houdini integration")
    group.addoption(
        "--run-houdini-integration",
        action="store_true",
        default=False,
        help="run tests that launch an isolated hython process",
    )
    group.addoption(
        "--hython",
        action="store",
        default=None,
        help="path to the hython executable used by integration tests",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-houdini-integration"):
        return
    skip = pytest.mark.skip(reason="use --run-houdini-integration to launch hython")
    for item in items:
        if "houdini_integration" in item.keywords:
            item.add_marker(skip)


def _resolve_hython(config):
    candidates = [
        config.getoption("--hython"),
        os.environ.get("HOUDINI_TEST_HYTHON"),
    ]
    hfs = os.environ.get("HFS")
    if hfs:
        candidates.append(str(Path(hfs) / "bin" / "hython.exe"))
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser().resolve()
        if path.is_file() and path.name.lower() in {"hython", "hython.exe"}:
            return path
    return None


@pytest.fixture(scope="session")
def hython_executable(request):
    path = _resolve_hython(request.config)
    if path is None:
        pytest.skip(
            "hython not found; set --hython, HOUDINI_TEST_HYTHON, or HFS"
        )
    return path
