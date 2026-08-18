# -*- coding: utf-8 -*-
"""Houdini 离线帮助数据源：目录发现、wiki 解析、ZIP 页面遍历。

这是 ``HoudiniDocIndex``（dict 索引）与 ``search_houdini_help`` skill
（全文检索/取页）共享的底层 module。四个函数构成全部 interface：

- ``find_help_dir``  — 定位包含 nodes.zip/vex.zip/hom.zip 的 help 目录
- ``parse_wiki``     — 解析 Houdini wiki 标记格式为结构化 dict
- ``iter_pages``     — 遍历 help ZIP 中的 .txt 页面（统一过滤规则）
- ``get_page``       — 按 ZIP 内相对路径读取一个可公开检索的页面

不导入 ``hou``，可在 Houdini 进程外使用。
"""

import os
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

# Houdini 离线帮助归档。find_help_dir 只要求其中之一存在；
# iter_pages 由调用方指定具体 ZIP。
HELP_ZIPS = ("nodes.zip", "vex.zip", "hom.zip")


def find_help_dir(explicit: Optional[str] = None) -> Optional[Path]:
    """定位 Houdini help 目录（含 nodes.zip/vex.zip/hom.zip 至少其一）。

    查找顺序：
    1. 显式传入的路径
    2. 项目内置 Doc/ 目录（随项目分发，确保任何电脑可用）
    3. 环境变量 HFS
    4. hou 模块（若在 Houdini 进程内）
    5. 常见 Windows 安装路径
    """
    def _has_zips(d: Path) -> bool:
        return d.is_dir() and any((d / z).exists() for z in HELP_ZIPS)

    # 0. 显式路径
    if explicit:
        p = Path(explicit)
        if _has_zips(p):
            return p

    # 1. 项目内置 Doc/ 目录（优先——保证跨机器可用）
    project_root = Path(__file__).parent.parent.parent
    bundled = project_root / "Doc"
    if _has_zips(bundled):
        return bundled

    # 2. 环境变量 HFS（Houdini 标准）
    hfs = os.environ.get("HFS")
    if hfs:
        p = Path(hfs) / "houdini" / "help"
        if _has_zips(p):
            return p

    # 3. hou 模块获取
    try:
        import hou  # type: ignore
        hfs_val = hou.getenv("HFS", "")
        if hfs_val:
            p = Path(hfs_val) / "houdini" / "help"
            if _has_zips(p):
                return p
    except Exception:
        pass

    # 4. 常见 Windows 安装路径
    for drive in ("C", "D", "E"):
        base = Path(f"{drive}:/Program Files/Side Effects Software")
        if base.is_dir():
            for v in sorted(base.glob("Houdini*"), reverse=True):
                p = v / "houdini" / "help"
                if _has_zips(p):
                    return p

    return None


def parse_wiki(text: str) -> Dict[str, Any]:
    """解析 Houdini wiki 标记格式文档。

    格式概要::

        = Title =
        #type: homclass
        #context: sop
        #internal: nodename

        \"\"\"Brief description\"\"\"

        Body text ...

        @parameters
        Param Name:
            Description

        @methods
        ::`methodName(args)`:
            Description

    返回 dict，键：title / type / context / internal / description / body /
    sections（@section 名 → 文本）。
    """
    doc: Dict[str, Any] = {
        "title": "", "type": "", "context": "", "internal": "",
        "description": "", "body": "", "sections": {},
    }

    lines = text.split("\n")
    i, n = 0, len(lines)

    # 跳过空行
    while i < n and not lines[i].strip():
        i += 1

    # = Title =
    if i < n:
        m = re.match(r"^=\s+(.+?)\s+=\s*$", lines[i])
        if m:
            doc["title"] = m.group(1).strip()
            i += 1

    # #key: value 元数据
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        m = re.match(r"^#(\w+):\s*(.*)", line)
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            if key in doc:
                doc[key] = val
            i += 1
        else:
            break

    # """description"""
    while i < n and not lines[i].strip():
        i += 1
    if i < n and lines[i].strip().startswith('"""'):
        dl = lines[i].strip()
        if dl.endswith('"""') and len(dl) > 6:
            doc["description"] = dl[3:-3].strip()
            i += 1
        else:
            parts = [dl[3:]]
            i += 1
            while i < n:
                if '"""' in lines[i]:
                    parts.append(lines[i].split('"""')[0])
                    i += 1
                    break
                parts.append(lines[i])
                i += 1
            doc["description"] = "\n".join(parts).strip()

    # Body + @sections
    cur_sec = "_body"
    buf = []
    while i < n:
        line = lines[i]
        s = line.strip()
        if s.startswith("@") and len(s) > 1 and s[1:].split()[0].isalpha():
            # 保存上一段
            text_block = "\n".join(buf).strip()
            if text_block:
                if cur_sec == "_body":
                    doc["body"] = text_block
                else:
                    doc["sections"][cur_sec] = text_block
            cur_sec = s[1:].split()[0]
            buf = []
        else:
            buf.append(line)
        i += 1

    text_block = "\n".join(buf).strip()
    if text_block:
        if cur_sec == "_body":
            doc["body"] = text_block
        else:
            doc["sections"][cur_sec] = text_block

    return doc


def iter_pages(
    zip_path: Path,
    max_scan: Optional[int] = None,
    max_bytes: Optional[int] = None,
    skip_underscore: bool = True,
) -> Iterator[Tuple[str, str]]:
    """遍历 help ZIP 中的帮助页面，yield (entry_name, raw_text)。

    过滤规则：只取 .txt，跳过路径含 ``/_`` 的条目；``skip_underscore=True``
    时再跳过文件名以 ``_`` 开头的内部页面（如 ``_hhp.txt``）。
    单个页面读取/解码失败时跳过，不中断遍历。

    - ``max_scan``：最多扫描的页面数（防止巨型手册拖慢单次调用）。
    - ``max_bytes``：每页最多解码的字节数。
    - ``skip_underscore``：是否跳过 ``_`` 开头的内部页面。
    """
    scanned = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if not name.endswith(".txt"):
                continue
            if "/_" in name:
                continue
            if skip_underscore and name.startswith("_"):
                continue
            scanned += 1
            if max_scan is not None and scanned > max_scan:
                break
            try:
                data = zf.read(name)
                if max_bytes is not None:
                    data = data[:max_bytes]
                yield name, data.decode("utf-8", errors="ignore")
            except Exception:
                continue


def get_page(
    help_dir: Path,
    entry_name: str,
    max_bytes: Optional[int] = None,
) -> Optional[Tuple[str, str]]:
    """Return ``(archive_name, text)`` for one public help page, or ``None``.

    Entry paths use ZIP semantics and are never treated as Houdini node paths
    or operating-system paths. Filtering and decoding match ``iter_pages``.
    Corrupt archives are skipped so another shipped archive can still match.
    """
    normalized = str(entry_name or "").replace("\\", "/").strip("/")
    if not normalized.endswith(".txt") or "/_" in normalized or normalized.startswith("_"):
        return None
    for archive_name in HELP_ZIPS:
        zip_path = help_dir / archive_name
        if not zip_path.exists():
            continue
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if normalized not in zf.namelist():
                    continue
                data = zf.read(normalized)
                if max_bytes is not None:
                    data = data[:max_bytes]
                return archive_name, data.decode("utf-8", errors="ignore")
        except Exception:
            continue
    return None
