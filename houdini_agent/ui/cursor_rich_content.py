# -*- coding: utf-8 -*-
"""Rich Markdown, code, and shell output widgets."""

import html
import re
import sys

from houdini_agent.qt_compat import QtWidgets, QtCore, QtGui

from .cursor_theme import CursorTheme
from .node_links import _linkify_node_paths


# ============================================================
# Markdown 解析器（专业版）
# ============================================================

class SimpleMarkdown:
    """将 Markdown 转换为 Qt Rich Text HTML（增强版）

    支持特性：
    - 标题 (# ~ ####)
    - 粗体 / 斜体 / 删除线 / 行内代码
    - 无序列表 / 有序列表 / 任务列表 / 嵌套列表
    - 引用块（多行合并，支持渐变背景）
    - 表格（居中 / 左对齐 / 右对齐）
    - 水平分割线
    - 链接 [text](url) / 自动 URL 检测
    - 图片 ![alt](url)
    - 脚注 [^id] / [^id]: ...
    - 转义字符 \\* \\` 等
    - 围栏代码块（交给 CodeBlockWidget）
    """

    _CODE_BLOCK_RE = re.compile(
        r'^[ \t]*```[ \t]*([^\n`]*)\n(.*?)^[ \t]*```[ \t]*$',
        re.DOTALL | re.MULTILINE,
    )
    _TABLE_SEP_RE = re.compile(r'^\|?\s*[-:]+[-| :]*$')  # 表头分割行
    # 自动检测裸 URL
    _AUTO_URL_RE = re.compile(
        r'(?<!["\w/=])(?<!\]\()(?<!\[)'       # 不在引号、字母、=、](、[ 之后
        r'(https?://[^\s<>\)\]\"\'`]+)'        # URL 本体
    )
    # 脚注引用
    _FOOTNOTE_REF_RE = re.compile(r'\[\^(\w+)\](?!:)')
    # 脚注定义
    _FOOTNOTE_DEF_RE = re.compile(r'^\[\^(\w+)\]:\s*(.*)')
    # 图片语法
    _IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
    # 列表缩进检测
    _LIST_ITEM_RE = re.compile(r'^(\s*)([-*]|\d+\.)\s+(.*)')
    # 任务列表
    _TASK_ITEM_RE = re.compile(r'^(\s*)[-*]\s+\[([ xX])\]\s+(.*)')

    # -------- 公共接口 --------

    @classmethod
    def parse_segments(cls, text: str) -> list:
        """将文本拆分为 ('text', html), ('code', lang, raw_code), ('image', url, alt) 段落"""
        segments: list = []
        last = 0
        for m in cls._CODE_BLOCK_RE.finditer(text):
            before = text[last:m.start()]
            if before.strip():
                cls._parse_text_with_images(before, segments)
            lang = (m.group(1) or '').strip()
            code = m.group(2).rstrip()
            if not lang:
                code_lines = code.split('\n')
                if code_lines and re.fullmatch(r'[A-Za-z][\w.+#-]{0,31}', code_lines[0].strip()):
                    lang = code_lines[0].strip()
                    code = '\n'.join(code_lines[1:]).rstrip()
            segments.append(('code', lang, code))
            last = m.end()
        after = text[last:]
        if after.strip():
            cls._parse_text_with_images(after, segments)
        if not segments and text.strip():
            cls._parse_text_with_images(text, segments)
        return segments

    @classmethod
    def _parse_text_with_images(cls, text: str, segments: list):
        """将文本段落进一步拆分出独立的 image segment
        
        只有独占一行的 ![alt](url) 才作为独立 image segment，
        行内的图片语法仍按行内格式处理。
        """
        lines = text.split('\n')
        buf_lines: list = []

        def _flush_buf():
            if buf_lines:
                joined = '\n'.join(buf_lines)
                if joined.strip():
                    segments.append(('text', cls._text_to_html(joined)))
                buf_lines.clear()

        for line in lines:
            stripped = line.strip()
            img_match = cls._IMAGE_RE.fullmatch(stripped)
            if img_match:
                _flush_buf()
                segments.append(('image', img_match.group(2), img_match.group(1)))
            else:
                buf_lines.append(line)
        _flush_buf()

    @classmethod
    def has_rich_content(cls, text: str) -> bool:
        """判断文本是否包含 Markdown 格式"""
        if '```' in text:
            return True
        if re.search(r'^#{1,4}\s', text, re.MULTILINE):
            return True
        if '**' in text or '`' in text:
            return True
        if re.search(r'^[-*]\s', text, re.MULTILINE):
            return True
        if re.search(r'^\d+\.\s', text, re.MULTILINE):
            return True
        if '|' in text and re.search(r'^\|.+\|', text, re.MULTILINE):
            return True
        if cls._IMAGE_RE.search(text):
            return True
        if cls._FOOTNOTE_REF_RE.search(text):
            return True
        return False

    # -------- 块级解析 --------

    @classmethod
    def _get_indent(cls, line: str) -> int:
        """返回行的缩进空格数"""
        return len(line) - len(line.lstrip())

    @classmethod
    def _text_to_html(cls, text: str) -> str:
        lines = text.split('\n')
        out: list = []
        i = 0
        n = len(lines)

        # 嵌套列表状态栈: [(tag, indent_level), ...]
        list_stack: list = []
        # 引用块缓冲
        quote_buf: list = []
        # 脚注定义收集
        footnotes: dict = {}

        # 第一遍：收集脚注定义
        remaining_lines: list = []
        for line in lines:
            fn_match = cls._FOOTNOTE_DEF_RE.match(line.strip())
            if fn_match:
                footnotes[fn_match.group(1)] = fn_match.group(2)
            else:
                remaining_lines.append(line)
        lines = remaining_lines
        n = len(lines)

        def _flush_all_lists():
            while list_stack:
                _, ltag = list_stack.pop()
                out.append(f'</{ltag}>')

        def _flush_lists_to_indent(target_indent: int):
            """关闭所有缩进大于 target_indent 的列表层级"""
            while list_stack and list_stack[-1][0] > target_indent:
                _, ltag = list_stack.pop()
                out.append(f'</{ltag}>')

        def _flush_quote():
            nonlocal quote_buf
            if quote_buf:
                q_html = '<br>'.join(cls._inline(q, footnotes) for q in quote_buf)
                out.append(
                    f'<div style="border-left:2px solid rgba(148,163,184,50);padding:8px 14px;'
                    f'margin:8px 0;'
                    f'background:transparent;'
                    f'color:#cbd5e1;border-radius:0 6px 6px 0;'
                    f'line-height:1.6;">{q_html}</div>'
                )
                quote_buf = []

        while i < n:
            raw_line = lines[i]
            s = raw_line.strip()

            # ---- empty line ----
            if not s:
                _flush_quote()
                _flush_all_lists()
                out.append('<div style="height:4px;"></div>')
                i += 1
                continue

            # ---- horizontal rule ----
            if re.match(r'^[-*_]{3,}\s*$', s):
                _flush_quote()
                _flush_all_lists()
                out.append(
                    '<hr style="border:none;border-top:1px solid rgba(255,255,255,8);margin:16px 0;width:100%;">'
                )
                i += 1
                continue

            # ---- table ----
            if '|' in s and i + 1 < n and cls._TABLE_SEP_RE.match(lines[i + 1].strip()):
                _flush_quote()
                _flush_all_lists()
                table_html = cls._parse_table(lines, i)
                if table_html:
                    out.append(table_html[0])
                    i = table_html[1]
                    continue

            # ---- headers ----
            header_match = re.match(r'^(#{1,4})\s+(.+)', s)
            if header_match:
                _flush_quote()
                _flush_all_lists()
                lvl = len(header_match.group(1))
                content = header_match.group(2)
                styles = {
                    1: ('1.5em', '#f1f5f9', '700', '18px 0 8px 0', 'border-bottom:1px solid rgba(255,255,255,12);padding-bottom:8px;letter-spacing:0.3px;'),
                    2: ('1.3em', '#e2e8f0', '600', '16px 0 6px 0', 'letter-spacing:0.2px;'),
                    3: ('1.1em', '#cbd5e1', '600', '12px 0 4px 0', ''),
                    4: ('1.0em', '#94a3b8', '600', '10px 0 3px 0', ''),
                }
                sz, clr, wt, mg, extra = styles[lvl]
                out.append(
                    f'<p style="font-size:{sz};font-weight:{wt};'
                    f'color:{clr};margin:{mg};{extra}">'
                    f'{cls._inline(content, footnotes)}</p>'
                )
                i += 1
                continue

            # ---- blockquote (合并连续行) ----
            if s.startswith('> '):
                _flush_all_lists()
                quote_buf.append(s[2:])
                i += 1
                continue
            elif s.startswith('>'):
                _flush_all_lists()
                quote_buf.append(s[1:].lstrip())
                i += 1
                continue
            else:
                _flush_quote()

            # ---- task list (with nesting support) ----
            task_match = cls._TASK_ITEM_RE.match(raw_line)
            if task_match:
                indent = len(task_match.group(1))
                _flush_lists_to_indent(indent)
                if not list_stack or list_stack[-1][0] < indent:
                    out.append(
                        '<ul style="margin:2px 0;padding-left:4px;list-style:none;">'
                    )
                    list_stack.append((indent, 'ul'))
                checked = task_match.group(2) in ('x', 'X')
                box = (
                    '<span style="color:#10b981;font-weight:bold;margin-right:6px;">✓</span>'
                    if checked else
                    '<span style="color:#64748b;margin-right:6px;">○</span>'
                )
                text_style = 'color:#64748b;text-decoration:line-through;' if checked else ''
                out.append(
                    f'<li style="margin:4px 0;line-height:1.6;{text_style}">'
                    f'{box}{cls._inline(task_match.group(3), footnotes)}</li>'
                )
                i += 1
                continue

            # ---- unordered / ordered list (with nesting) ----
            list_match = cls._LIST_ITEM_RE.match(raw_line)
            if list_match:
                indent = len(list_match.group(1))
                marker = list_match.group(2)
                item_text = list_match.group(3)
                is_ordered = marker[-1] == '.'
                new_tag = 'ol' if is_ordered else 'ul'

                _flush_lists_to_indent(indent)

                if not list_stack or list_stack[-1][0] < indent:
                    # 开启新的嵌套层级
                    if is_ordered:
                        out.append(
                            '<ol style="margin:4px 0;padding-left:22px;color:#94a3b8;">'
                        )
                    else:
                        out.append(
                            '<ul style="margin:4px 0;padding-left:22px;'
                            'list-style-type:disc;color:#94a3b8;">'
                        )
                    list_stack.append((indent, new_tag))
                elif list_stack[-1][1] != new_tag:
                    # 同层级但类型切换
                    old_indent, old_tag = list_stack.pop()
                    out.append(f'</{old_tag}>')
                    if is_ordered:
                        out.append(
                            '<ol style="margin:4px 0;padding-left:22px;color:#94a3b8;">'
                        )
                    else:
                        out.append(
                            '<ul style="margin:4px 0;padding-left:22px;'
                            'list-style-type:disc;color:#94a3b8;">'
                        )
                    list_stack.append((indent, new_tag))

                out.append(
                    f'<li style="margin:4px 0;line-height:1.6;color:{CursorTheme.TEXT_PRIMARY};">'
                    f'{cls._inline(item_text, footnotes)}</li>'
                )
                i += 1
                continue

            # ---- normal paragraph ----
            _flush_all_lists()
            out.append(
                f'<p style="margin:4px 0;line-height:1.6;color:#e2e8f0;">'
                f'{cls._inline(s, footnotes)}</p>'
            )
            i += 1

        _flush_quote()
        _flush_all_lists()

        # 渲染脚注定义区域（如果有）
        if footnotes:
            out.append(
                '<hr style="border:none;border-top:1px solid rgba(255,255,255,8);'
                'margin:12px 0 6px 0;width:40%;">'
            )
            for fn_id, fn_text in footnotes.items():
                out.append(
                    f'<p style="margin:2px 0;font-size:0.85em;color:{CursorTheme.TEXT_SECONDARY};'
                    f'line-height:1.4;">'
                    f'<sup style="color:#60a5fa;">[{html.escape(fn_id)}]</sup> '
                    f'{cls._inline(fn_text, footnotes)}</p>'
                )

        return '\n'.join(out)

    # -------- 表格解析 --------

    @classmethod
    def _parse_table(cls, lines: list, start: int) -> tuple:
        """解析 Markdown 表格，返回 (html, next_line_index)"""
        header_line = lines[start].strip()
        if start + 1 >= len(lines):
            return None
        sep_line = lines[start + 1].strip()

        # 解析对齐方式
        sep_cells = [c.strip() for c in sep_line.strip('|').split('|')]
        aligns = []
        for c in sep_cells:
            c = c.strip()
            if c.startswith(':') and c.endswith(':'):
                aligns.append('center')
            elif c.endswith(':'):
                aligns.append('right')
            else:
                aligns.append('left')

        def _parse_row(line: str) -> list:
            line = line.strip()
            if line.startswith('|'):
                line = line[1:]
            if line.endswith('|'):
                line = line[:-1]
            return [c.strip() for c in line.split('|')]

        # 表头
        headers = _parse_row(header_line)

        # 表体
        rows = []
        j = start + 2
        while j < len(lines):
            row_s = lines[j].strip()
            if not row_s or '|' not in row_s:
                break
            rows.append(_parse_row(row_s))
            j += 1

        # 生成 HTML（现代极简：无外边框、无斑马纹、仅底线分隔）
        tbl = [
            '<table style="border-collapse:collapse;'
            'margin:10px 0;width:100%;font-size:0.92em;">'
        ]

        # thead
        tbl.append('<tr>')
        for ci, h in enumerate(headers):
            align = aligns[ci] if ci < len(aligns) else 'left'
            tbl.append(
                f'<th style="border-bottom:2px solid rgba(255,255,255,12);'
                f'padding:7px 14px;'
                f'background:transparent;color:#e2e8f0;font-weight:600;'
                f'text-align:{align};font-size:0.95em;">{cls._inline(h)}</th>'
            )
        tbl.append('</tr>')

        # tbody — 统一背景，仅底线分隔
        for ri, row in enumerate(rows):
            tbl.append('<tr>')
            for ci, cell in enumerate(row):
                align = aligns[ci] if ci < len(aligns) else 'left'
                border_bottom = (
                    'border-bottom:1px solid rgba(255,255,255,5);'
                    if ri < len(rows) - 1 else ''
                )
                tbl.append(
                    f'<td style="{border_bottom}padding:7px 14px;'
                    f'background:transparent;color:{CursorTheme.TEXT_PRIMARY};'
                    f'text-align:{align};line-height:1.5;">{cls._inline(cell)}</td>'
                )
            tbl.append('</tr>')

        tbl.append('</table>')
        return ('\n'.join(tbl), j)

    # -------- 行内解析 --------

    @classmethod
    def _inline(cls, text: str, footnotes: dict = None) -> str:
        """行内格式: **粗体**, *斜体*, ~~删除线~~, `代码`, [链接](url),
        ![图片](url), [^脚注], 自动URL, 转义字符, 节点路径"""
        # 1. 处理转义字符：先将 \X 替换为占位符，最后再还原
        _ESC_MAP = {}
        _esc_counter = [0]

        def _replace_escape(m):
            key = f'\x00ESC{_esc_counter[0]}\x00'
            _ESC_MAP[key] = m.group(1)  # 被转义的字符
            _esc_counter[0] += 1
            return key

        text = re.sub(r'\\([\\`*_~\[\]()#>!|])', _replace_escape, text)

        # 2. HTML 转义
        text = html.escape(text)

        # 3. 行内图片 ![alt](url)（行内级别，不独占行）
        text = re.sub(
            r'!\[([^\]]*)\]\(([^)]+)\)',
            r'<img src="\2" alt="\1" style="max-width:100%;max-height:200px;'
            r'border-radius:4px;margin:2px 0;vertical-align:middle;">',
            text,
        )

        # 4. 链接 [text](url)
        text = re.sub(
            r'\[([^\]]+?)\]\(([^)]+?)\)',
            r'<a href="\2" style="color:#818cf8;text-decoration:none;'
            r'border-bottom:1px solid rgba(129,140,248,0.3);">\1</a>',
            text,
        )

        # 5. 脚注引用 [^id]
        if footnotes:
            def _fn_ref(m):
                fid = m.group(1)
                if fid in footnotes:
                    return (
                        f'<sup style="color:#818cf8;cursor:pointer;">'
                        f'<a href="#fn-{html.escape(fid)}" style="color:#818cf8;'
                        f'text-decoration:none;">[{html.escape(fid)}]</a></sup>'
                    )
                return m.group(0)
            text = cls._FOOTNOTE_REF_RE.sub(_fn_ref, text)

        # 6. 粗体
        text = re.sub(r'\*\*(.+?)\*\*', r'<b style="color:#f1f5f9;font-weight:600;">\1</b>', text)
        # 7. 删除线
        text = re.sub(r'~~(.+?)~~', r'<s style="color:#64748b;">\1</s>', text)
        # 8. 斜体
        text = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<i style="color:#cbd5e1;">\1</i>', text)
        # 9. 行内代码
        text = re.sub(
            r'`([^`]+?)`',
            r'<code style="background:rgba(255,255,255,8);padding:2px 7px;border-radius:5px;'
            r'font-family:Consolas,Monaco,monospace;color:#c9d1d9;'
            r'font-size:0.88em;border:1px solid rgba(255,255,255,5);">\1</code>',
            text,
        )
        # 10. 自动 URL 检测（裸链接）
        text = cls._AUTO_URL_RE.sub(
            r'<a href="\1" style="color:#818cf8;text-decoration:none;">\1</a>',
            text,
        )
        # 11. Houdini 节点路径 → 可点击链接
        text = _linkify_node_paths(text)

        # 12. 还原转义字符
        for key, char in _ESC_MAP.items():
            text = text.replace(key, html.escape(char))

        return text


# ============================================================
# 语法高亮器
# ============================================================

class SyntaxHighlighter:
    """代码语法高亮 — 基于 token 的着色
    
    支持语言: VEX, Python, JSON, YAML, Bash/Shell, JavaScript/TypeScript,
    HScript, GLSL, Markdown
    """

    COL = {
        'keyword':  '#569CD6',
        'type':     '#4EC9B0',
        'builtin':  '#DCDCAA',
        'string':   '#CE9178',
        'comment':  '#6A9955',
        'number':   '#B5CEA8',
        'attr':     '#9CDCFE',
        'key':      '#9CDCFE',    # JSON / YAML key
        'constant': '#569CD6',    # true / false / null
        'operator': '#D4D4D4',    # operators
        'directive': '#C586C0',   # preprocessor / shebang
    }

    # ---- VEX ----
    VEX_KW = frozenset(
        'if else for while return break continue foreach do switch case default'.split()
    )
    VEX_TY = frozenset(
        'float vector vector2 vector4 int string void matrix matrix3 dict'.split()
    )
    VEX_BI = frozenset(
        'set getattrib setattrib point prim detail chf chi chs chv chramp '
        'length normalize fit fit01 rand noise sin cos pow sqrt abs min max '
        'clamp lerp smooth cross dot addpoint addprim addvertex removeprim '
        'removepoint npoints nprims printf sprintf push pop append resize len '
        'find sort sample_direction_uniform pcopen pcfilter nearpoint '
        'nearpoints xyzdist primuv'.split()
    )

    # ---- Python ----
    PY_KW = frozenset(
        'import from def class return if else elif for while try except finally '
        'with as in not and or is None True False pass break continue raise '
        'yield lambda global nonlocal del assert'.split()
    )
    PY_BI = frozenset(
        'print len range str int float list dict tuple set type isinstance '
        'enumerate zip map filter sorted reversed open super property '
        'staticmethod classmethod hasattr getattr setattr'.split()
    )

    # ---- JavaScript / TypeScript ----
    JS_KW = frozenset(
        'var let const function return if else for while do switch case default '
        'break continue new this typeof instanceof void delete throw try catch '
        'finally class extends import export from as async await yield of in '
        'static get set super'.split()
    )
    JS_TY = frozenset(
        'string number boolean any void never unknown object symbol bigint '
        'undefined null Array Promise Map Set Record Partial Required Readonly '
        'interface type enum namespace'.split()
    )
    JS_BI = frozenset(
        'console log warn error parseInt parseFloat isNaN isFinite '
        'JSON Math Date RegExp Object Array String Number Boolean '
        'setTimeout setInterval clearTimeout clearInterval '
        'fetch require module exports process'.split()
    )

    # ---- Bash / Shell ----
    BASH_KW = frozenset(
        'if then else elif fi for do done while until case esac in '
        'function return exit break continue select'.split()
    )
    BASH_BI = frozenset(
        'echo printf cd ls cp mv rm mkdir rmdir cat grep sed awk find '
        'chmod chown tar gzip gunzip curl wget git pip python node npm '
        'export source alias unalias set unset read eval exec test '
        'true false shift'.split()
    )

    # ---- HScript ----
    HSCRIPT_KW = frozenset(
        'if else endif for foreach end set setenv echo opcf opcd '
        'opparm oprm opadd opsave opload chadd chkey chls optype '
        'opflag opname opset oppane opproperty'.split()
    )

    # ---- GLSL ----
    GLSL_KW = frozenset(
        'if else for while do return break continue discard switch case default '
        'struct void const in out inout uniform varying attribute '
        'layout precision highp mediump lowp flat smooth noperspective '
        'centroid sample'.split()
    )
    GLSL_TY = frozenset(
        'float vec2 vec3 vec4 int ivec2 ivec3 ivec4 uint uvec2 uvec3 uvec4 '
        'bool bvec2 bvec3 bvec4 mat2 mat3 mat4 mat2x2 mat2x3 mat2x4 '
        'mat3x2 mat3x3 mat3x4 mat4x2 mat4x3 mat4x4 '
        'sampler1D sampler2D sampler3D samplerCube sampler2DShadow'.split()
    )
    GLSL_BI = frozenset(
        'texture texture2D textureCube normalize length distance dot cross '
        'reflect refract mix clamp smoothstep step min max abs sign floor '
        'ceil fract mod pow exp log sqrt inversesqrt sin cos tan asin acos atan '
        'radians degrees dFdx dFdy fwidth'.split()
    )

    @classmethod
    def highlight_vex(cls, code: str) -> str:
        return cls._tokenize(code, cls.VEX_KW, cls.VEX_TY, cls.VEX_BI,
                              '//', ('/*', '*/'), '@')

    @classmethod
    def highlight_python(cls, code: str) -> str:
        return cls._tokenize(code, cls.PY_KW, frozenset(), cls.PY_BI,
                              '#', None, None)

    @classmethod
    def highlight_javascript(cls, code: str) -> str:
        return cls._tokenize(code, cls.JS_KW, cls.JS_TY, cls.JS_BI,
                              '//', ('/*', '*/'), None)

    @classmethod
    def highlight_bash(cls, code: str) -> str:
        return cls._tokenize(code, cls.BASH_KW, frozenset(), cls.BASH_BI,
                              '#', None, '$')

    @classmethod
    def highlight_hscript(cls, code: str) -> str:
        return cls._tokenize(code, cls.HSCRIPT_KW, frozenset(), frozenset(),
                              '#', None, '$')

    @classmethod
    def highlight_glsl(cls, code: str) -> str:
        return cls._tokenize(code, cls.GLSL_KW, cls.GLSL_TY, cls.GLSL_BI,
                              '//', ('/*', '*/'), None)

    @classmethod
    def highlight_json(cls, code: str) -> str:
        """JSON 高亮：key 和 value 区分着色"""
        parts: list = []
        i, n = 0, len(code)
        # 简单状态：上一个非空白字符是 { 或 , 或行首 → 下一个字符串是 key
        expect_key = True

        while i < n:
            c = code[i]

            # 空白
            if c in (' ', '\t', '\n', '\r'):
                parts.append(c)
                if c == '\n':
                    expect_key = True
                i += 1
                continue

            # 字符串
            if c == '"':
                j = i + 1
                while j < n and code[j] != '"':
                    if code[j] == '\\':
                        j += 1
                    j += 1
                if j < n:
                    j += 1
                s = code[i:j]
                # 判断是 key 还是 value
                # key 后面（跳过空白）应该是 :
                rest = code[j:].lstrip()
                if expect_key and rest.startswith(':'):
                    parts.append(cls._span('key', s))
                    expect_key = False
                else:
                    parts.append(cls._span('string', s))
                i = j
                continue

            # 冒号
            if c == ':':
                parts.append(html.escape(c))
                expect_key = False
                i += 1
                continue

            # 逗号
            if c == ',':
                parts.append(html.escape(c))
                expect_key = True
                i += 1
                continue

            # 大括号 / 方括号
            if c in ('{', '['):
                parts.append(html.escape(c))
                expect_key = True
                i += 1
                continue
            if c in ('}', ']'):
                parts.append(html.escape(c))
                i += 1
                continue

            # 数字
            if c.isdigit() or (c == '-' and i + 1 < n and code[i + 1].isdigit()):
                j = i + 1 if c == '-' else i
                while j < n and (code[j].isdigit() or code[j] in ('.', 'e', 'E', '+', '-')):
                    j += 1
                parts.append(cls._span('number', code[i:j]))
                i = j
                continue

            # true / false / null
            for kw in ('true', 'false', 'null'):
                if code[i:i + len(kw)] == kw:
                    parts.append(cls._span('constant', kw))
                    i += len(kw)
                    break
            else:
                parts.append(html.escape(c))
                i += 1

        return ''.join(parts)

    @classmethod
    def highlight_yaml(cls, code: str) -> str:
        """YAML 高亮：key-value 区分、注释、列表标记"""
        parts: list = []
        lines = code.split('\n')
        for li, line in enumerate(lines):
            if li > 0:
                parts.append('\n')

            stripped = line.lstrip()

            # 注释
            if stripped.startswith('#'):
                parts.append(cls._span('comment', line))
                continue

            # 文档分隔符 ---
            if stripped in ('---', '...'):
                parts.append(cls._span('directive', line))
                continue

            # 列表项 - xxx: value
            indent = line[:len(line) - len(stripped)]
            if indent:
                parts.append(html.escape(indent))

            # 检查 key: value 格式
            colon_pos = stripped.find(':')
            if colon_pos > 0 and (colon_pos + 1 >= len(stripped) or stripped[colon_pos + 1] == ' '):
                # 处理列表标记
                key_part = stripped[:colon_pos]
                if key_part.startswith('- '):
                    parts.append(html.escape('- '))
                    key_part = key_part[2:]

                parts.append(cls._span('key', key_part))
                parts.append(html.escape(':'))

                value_part = stripped[colon_pos + 1:]
                if value_part:
                    # 检查 value 中的注释
                    comment_pos = value_part.find(' #')
                    if comment_pos >= 0:
                        val = value_part[:comment_pos]
                        comment = value_part[comment_pos:]
                        parts.append(cls._highlight_yaml_value(val))
                        parts.append(cls._span('comment', comment))
                    else:
                        parts.append(cls._highlight_yaml_value(value_part))
            else:
                # 列表项或纯值
                if stripped.startswith('- '):
                    parts.append(html.escape('- '))
                    parts.append(cls._highlight_yaml_value(stripped[2:]))
                else:
                    parts.append(html.escape(stripped))

        return ''.join(parts)

    @classmethod
    def _highlight_yaml_value(cls, value: str) -> str:
        """高亮 YAML 值"""
        v = value.strip()
        if not v:
            return html.escape(value)

        # 保留前导空格
        leading = value[:len(value) - len(value.lstrip())]
        result = html.escape(leading) if leading else ''

        # 字符串（带引号）
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            return result + cls._span('string', v)
        # 布尔 / null
        if v.lower() in ('true', 'false', 'yes', 'no', 'on', 'off', 'null', '~'):
            return result + cls._span('constant', v)
        # 数字
        try:
            float(v)
            return result + cls._span('number', v)
        except ValueError:
            pass
        return result + html.escape(v)

    @classmethod
    def _tokenize(cls, code, keywords, types, builtins,
                   comment_single, comment_multi, attr_prefix):
        parts: list = []
        i, n = 0, len(code)
        while i < n:
            c = code[i]
            # --- single-line comment ---
            if comment_single and code[i:i + len(comment_single)] == comment_single:
                end = code.find('\n', i)
                if end == -1:
                    end = n
                parts.append(cls._span('comment', code[i:end]))
                i = end
                continue
            # --- multi-line comment ---
            if comment_multi and code[i:i + len(comment_multi[0])] == comment_multi[0]:
                end = code.find(comment_multi[1], i + len(comment_multi[0]))
                end = n if end == -1 else end + len(comment_multi[1])
                parts.append(cls._span('comment', code[i:end]))
                i = end
                continue
            # --- strings ---
            if c in ('"', "'", '`'):
                # Template literals (JS backtick strings)
                if c == '`':
                    j = i + 1
                    while j < n and code[j] != '`':
                        if code[j] == '\\':
                            j += 1
                        j += 1
                    if j < n:
                        j += 1
                    parts.append(cls._span('string', code[i:j]))
                    i = j
                    continue
                triple = code[i:i + 3]
                if triple in ('"""', "'''"):
                    end = code.find(triple, i + 3)
                    end = n if end == -1 else end + 3
                    parts.append(cls._span('string', code[i:end]))
                    i = end
                    continue
                j = i + 1
                while j < n and code[j] != c and code[j] != '\n':
                    if code[j] == '\\':
                        j += 1
                    j += 1
                if j < n and code[j] == c:
                    j += 1
                parts.append(cls._span('string', code[i:j]))
                i = j
                continue
            # --- attribute prefix (@P, $VAR etc.) ---
            if (attr_prefix and c == attr_prefix
                    and i + 1 < n and (code[i + 1].isalpha() or code[i + 1] == '_')):
                j = i + 1
                while j < n and (code[j].isalnum() or code[j] in ('_', '.')):
                    j += 1
                parts.append(cls._span('attr', code[i:j]))
                i = j
                continue
            # --- preprocessor directive (#include, #define) ---
            if c == '#' and (not comment_single or comment_single != '#'):
                if i == 0 or code[i - 1] == '\n':
                    end = code.find('\n', i)
                    if end == -1:
                        end = n
                    parts.append(cls._span('directive', code[i:end]))
                    i = end
                    continue
            # --- identifier / keyword ---
            if c.isalpha() or c == '_':
                j = i
                while j < n and (code[j].isalnum() or code[j] == '_'):
                    j += 1
                word = code[i:j]
                if word in keywords:
                    parts.append(cls._span('keyword', word))
                elif word in types:
                    parts.append(cls._span('type', word))
                elif word in builtins:
                    parts.append(cls._span('builtin', word))
                else:
                    parts.append(html.escape(word))
                i = j
                continue
            # --- number (including hex 0x...) ---
            if c.isdigit() or (c == '.' and i + 1 < n and code[i + 1].isdigit()):
                j = i
                if c == '0' and j + 1 < n and code[j + 1] in ('x', 'X'):
                    j += 2
                    while j < n and (code[j].isdigit() or code[j] in 'abcdefABCDEF'):
                        j += 1
                else:
                    while j < n and (code[j].isdigit() or code[j] in ('.', 'e', 'E', '+', '-', 'f')):
                        if code[j] in ('+', '-') and j > 0 and code[j - 1] not in ('e', 'E'):
                            break
                        j += 1
                parts.append(cls._span('number', code[i:j]))
                i = j
                continue
            parts.append(html.escape(c))
            i += 1
        return ''.join(parts)

    @classmethod
    def _span(cls, tok_type: str, text: str) -> str:
        color = cls.COL.get(tok_type, '#D4D4D4')
        return f'<span style="color:{color};">{html.escape(text)}</span>'


# ============================================================
# 可折叠 Shell 输出区域（Python Shell / System Shell 共用）
# ============================================================

class _CollapsibleShellOutput(QtWidgets.QWidget):
    """可折叠的 Shell 输出区域
    
    - 默认折叠：只显示 4 行，滚轮穿透到父窗口
    - 展开后：显示全部内容，滚轮可滚动内联区域
    """

    _COLLAPSED_LINES = 4
    _MAX_EXPANDED_H = 400  # 展开后最大高度

    def __init__(self, content_html: str, bg_color: str = "#141428",
                 parent=None):
        super().__init__(parent)
        self._collapsed = True
        self._full_h = 0
        self._collapsed_h = 0
        # 根据背景色推断 variant（python / system）
        self._variant = "system" if bg_color == "#141414" else "python"

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── QTextEdit（输出内容）──
        self._text = QtWidgets.QTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self._text.setObjectName("shellOutput")
        self._text.setProperty("variant", self._variant)
        self._text.setHtml(
            f'<pre style="margin:0;white-space:pre;font-family:Consolas,Monaco,monospace;'
            f'font-size:12px;">{content_html}</pre>'
        )
        lay.addWidget(self._text)

        # 计算尺寸
        doc = self._text.document()
        doc.setDocumentMargin(4)
        self._full_h = int(doc.size().height()) + 16

        # 计算折叠高度（4 行）
        fm = self._text.fontMetrics()
        line_h = fm.lineSpacing() if fm.lineSpacing() > 0 else 17
        self._collapsed_h = self._COLLAPSED_LINES * line_h + 16  # 16 = padding

        # 判断是否需要折叠（内容不足 4 行则不折叠）
        self._needs_collapse = self._full_h > self._collapsed_h + line_h

        if self._needs_collapse:
            # 初始折叠状态
            self._text.setFixedHeight(self._collapsed_h)
            self._text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._text.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            # 安装事件过滤器拦截滚轮
            self._text.viewport().installEventFilter(self)

            # 计算总行数
            total_lines = content_html.count('<br>') + content_html.count('\n') + 1
            remaining = max(0, total_lines - self._COLLAPSED_LINES)

            # ── 展开/收起 toggle bar ──
            self._toggle = QtWidgets.QLabel(
                f"  ▼ 展开 ({remaining} 更多行)"
            )
            self._toggle.setCursor(QtCore.Qt.PointingHandCursor)
            self._toggle.setObjectName("shellToggle")
            self._toggle.setProperty("variant", self._variant)
            self._toggle.mousePressEvent = lambda e: self._toggle_collapse()
            self._toggle.setFixedHeight(22)
            lay.addWidget(self._toggle)
            self._remaining = remaining
        else:
            # 内容较短，不需要折叠，直接显示全部
            h = min(self._full_h, self._MAX_EXPANDED_H)
            self._text.setFixedHeight(h)
            self._text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._text.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)

    def _toggle_collapse(self):
        """切换折叠/展开"""
        self._collapsed = not self._collapsed
        if self._collapsed:
            # 折叠
            self._text.setFixedHeight(self._collapsed_h)
            self._text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._text.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._text.verticalScrollBar().setValue(0)
            self._toggle.setText(f"  ▼ 展开 ({self._remaining} 更多行)")
        else:
            # 展开
            h = min(self._full_h, self._MAX_EXPANDED_H)
            self._text.setFixedHeight(h)
            if self._full_h > self._MAX_EXPANDED_H:
                self._text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            else:
                self._text.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._text.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self._toggle.setText("  ▲ 收起")

    def eventFilter(self, obj, event):
        """折叠状态下，滚轮事件穿透到父窗口"""
        if (event.type() == QtCore.QEvent.Wheel
                and self._collapsed and self._needs_collapse):
            # 把滚轮事件转发给父 ScrollArea
            parent = self.parent()
            while parent:
                if isinstance(parent, QtWidgets.QScrollArea):
                    QtWidgets.QApplication.sendEvent(parent.viewport(), event)
                    return True
                parent = parent.parent()
            return True  # 即使没找到也吃掉，避免内联滚动
        return super().eventFilter(obj, event)


# ============================================================
# Python Shell 执行窗口
# ============================================================

class PythonShellWidget(QtWidgets.QFrame):
    """Python Shell 执行结果 — 显示代码 + 输出 + 错误"""
    
    def __init__(self, code: str, output: str = "", error: str = "",
                 exec_time: float = 0.0, success: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("PythonShellWidget")
        
        self.setProperty("state", "ok" if success else "error")
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # ---- header: Python Shell + 执行时间 ----
        header = QtWidgets.QWidget()
        header.setObjectName("pyShellHeader")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(6)
        
        title_lbl = QtWidgets.QLabel("PYTHON SHELL")
        title_lbl.setObjectName("pyShellTitle")
        hl.addWidget(title_lbl)
        
        hl.addStretch()
        
        if exec_time > 0:
            time_lbl = QtWidgets.QLabel(f"{exec_time:.2f}s")
            time_lbl.setObjectName("shellTimeLbl")
            hl.addWidget(time_lbl)
        
        status_lbl = QtWidgets.QLabel("ok" if success else "err")
        status_lbl.setObjectName("shellStatusOk" if success else "shellStatusErr")
        hl.addWidget(status_lbl)
        
        layout.addWidget(header)
        
        # ---- 代码区域 ----
        code_widget = QtWidgets.QTextEdit()
        code_widget.setReadOnly(True)
        code_widget.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        code_widget.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        code_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        code_widget.setObjectName("shellCodeEdit")
        
        # Python 语法高亮
        highlighted_code = SyntaxHighlighter.highlight_python(code)
        code_widget.setHtml(f'<pre style="margin:0;white-space:pre;">{highlighted_code}</pre>')
        
        # 代码区高度自适应 (最高 200px)
        doc = code_widget.document()
        doc.setDocumentMargin(4)
        code_h = min(int(doc.size().height()) + 16, 200)
        code_widget.setFixedHeight(code_h)
        layout.addWidget(code_widget)
        
        # ---- 输出区域（可折叠）----
        has_output = bool(output and output.strip())
        has_error = bool(error and error.strip())
        
        if has_output or has_error:
            parts = []
            if has_output:
                parts.append(f'<span style="color:{CursorTheme.TEXT_PRIMARY};">'
                             f'{html.escape(output.strip())}</span>')
            if has_error:
                parts.append(f'<span style="color:{CursorTheme.ACCENT_RED};">'
                             f'{html.escape(error.strip())}</span>')
            content_html = '<br>'.join(parts)
            layout.addWidget(_CollapsibleShellOutput(content_html, "#141428", self))
        
        elif not success:
            err_label = QtWidgets.QLabel("执行失败（无详细信息）")
            err_label.setObjectName("shellErrFallback")
            layout.addWidget(err_label)


class SystemShellWidget(QtWidgets.QFrame):
    """System Shell 执行结果 — 显示命令 + stdout/stderr + 退出码"""

    def __init__(self, command: str, output: str = "", error: str = "",
                 exit_code: int = 0, exec_time: float = 0.0,
                 success: bool = True, cwd: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SystemShellWidget")

        self.setProperty("state", "ok" if success else "error")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- header: SHELL + cwd + 执行时间 + 退出码 ----
        header = QtWidgets.QWidget()
        header.setObjectName("sysShellHeader")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(8, 4, 8, 4)
        hl.setSpacing(6)

        title_lbl = QtWidgets.QLabel("SHELL")
        title_lbl.setObjectName("sysShellTitle")
        hl.addWidget(title_lbl)

        if cwd:
            # 只显示最后两层目录
            parts = cwd.replace('\\', '/').rstrip('/').split('/')
            short_cwd = '/'.join(parts[-2:]) if len(parts) >= 2 else cwd
            cwd_lbl = QtWidgets.QLabel(short_cwd)
            cwd_lbl.setObjectName("shellCwdLbl")
            hl.addWidget(cwd_lbl)

        hl.addStretch()

        if exec_time > 0:
            time_lbl = QtWidgets.QLabel(f"{exec_time:.2f}s")
            time_lbl.setObjectName("shellTimeLbl")
            hl.addWidget(time_lbl)

        code_lbl = QtWidgets.QLabel(f"exit {exit_code}")
        code_lbl.setObjectName("shellStatusOk" if exit_code == 0 else "shellStatusErr")
        hl.addWidget(code_lbl)

        layout.addWidget(header)

        # ---- 命令区域 ----
        cmd_widget = QtWidgets.QTextEdit()
        cmd_widget.setReadOnly(True)
        cmd_widget.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        cmd_widget.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        cmd_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        cmd_widget.setObjectName("shellCmdEdit")

        # 命令显示：带 $ 或 > 前缀
        import html as _html
        prefix = "&gt;" if "win" in sys.platform else "$"
        cmd_html = (
            f'<pre style="margin:0;white-space:pre;">'
            f'<span style="color:{CursorTheme.ACCENT_GREEN};">{prefix}</span> '
            f'{_html.escape(command)}</pre>'
        )
        cmd_widget.setHtml(cmd_html)

        doc = cmd_widget.document()
        doc.setDocumentMargin(4)
        cmd_h = min(int(doc.size().height()) + 16, 80)
        cmd_widget.setFixedHeight(cmd_h)
        layout.addWidget(cmd_widget)

        # ---- 输出区域（可折叠）----
        has_output = bool(output and output.strip())
        has_error = bool(error and error.strip())

        if has_output or has_error:
            parts = []
            if has_output:
                parts.append(f'<span style="color:{CursorTheme.TEXT_PRIMARY};">'
                             f'{_html.escape(output.strip())}</span>')
            if has_error:
                parts.append(f'<span style="color:{CursorTheme.ACCENT_RED};">'
                             f'{_html.escape(error.strip())}</span>')
            content_html = '<br>'.join(parts)
            layout.addWidget(_CollapsibleShellOutput(content_html, "#141414", self))

        elif not success:
            err_label = QtWidgets.QLabel("命令执行失败（无详细信息）")
            err_label.setObjectName("shellErrFallback")
            layout.addWidget(err_label)


# ============================================================
# 代码块组件
# ============================================================

class CodeBlockWidget(QtWidgets.QFrame):
    """代码块 — 语法高亮 + 行号 + 复制 + 折叠 + 创建 Wrangle（VEX 专属）
    
    ★ Phase 6 增强:
    - 大于 5 行时自动显示行号
    - 超过 15 行默认折叠，点击展开
    - 语言标签显示在 header
    """

    createWrangleRequested = QtCore.Signal(str)  # vex_code

    _VEX_INDICATORS = (
        '@P', '@Cd', '@N', '@v', '@ptnum', '@numpt', '@opinput',
        'chf(', 'chi(', 'chs(', 'chv(', 'chramp(',
        'addpoint', 'addprim', 'setattrib', 'getattrib',
        'vector ', 'float ', '#include',
    )

    _COLLAPSE_THRESHOLD = 15   # 超过此行数默认折叠
    _LINE_NUM_THRESHOLD = 5    # 超过此行数显示行号
    _MAX_HEIGHT = 400          # 最大高度

    def __init__(self, code: str, language: str = "", parent=None):
        super().__init__(parent)
        self._code = code
        self._lang = self._normalize_language(language)
        self._line_count = code.count('\n') + 1
        self._collapsed = self._line_count > self._COLLAPSE_THRESHOLD
        self._show_line_numbers = self._line_count > self._LINE_NUM_THRESHOLD

        self.setObjectName("CodeBlockWidget")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- header ----
        header = QtWidgets.QWidget()
        header.setObjectName("codeBlockHeader")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(8, 3, 4, 3)
        hl.setSpacing(4)

        lang_text = self._lang.upper() or ("VEX" if self._is_vex() else "CODE")
        # 语言标签 + 行数信息
        lang_info = f"{lang_text}"
        if self._line_count > 1:
            lang_info += f"  ({self._line_count} 行)"
        lang_lbl = QtWidgets.QLabel(lang_info)
        lang_lbl.setObjectName("codeBlockLang")
        hl.addWidget(lang_lbl)
        hl.addStretch()

        # 操作按钮列表（hover 时显示）
        self._action_btns: list = []

        # 折叠/展开按钮（仅在超过阈值时显示，始终可见）
        if self._line_count > self._COLLAPSE_THRESHOLD:
            self._toggle_btn = QtWidgets.QPushButton(
                f"展开 ({self._line_count} 行)" if self._collapsed else "收起"
            )
            self._toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self._toggle_btn.setObjectName("codeBlockBtn")
            self._toggle_btn.clicked.connect(self._toggle_collapse)
            hl.addWidget(self._toggle_btn)

        copy_btn = QtWidgets.QPushButton("复制")
        copy_btn.setCursor(QtCore.Qt.PointingHandCursor)
        copy_btn.setObjectName("codeBlockBtn")
        copy_btn.clicked.connect(self._on_copy)
        copy_btn.setVisible(False)
        hl.addWidget(copy_btn)
        self._action_btns.append(copy_btn)

        if self._lang in ('vex', 'vfl', '') and self._is_vex():
            wrangle_btn = QtWidgets.QPushButton("创建 Wrangle")
            wrangle_btn.setCursor(QtCore.Qt.PointingHandCursor)
            wrangle_btn.setObjectName("codeBlockBtnGreen")
            wrangle_btn.clicked.connect(lambda: self.createWrangleRequested.emit(self._code))
            wrangle_btn.setVisible(False)
            hl.addWidget(wrangle_btn)
            self._action_btns.append(wrangle_btn)

        layout.addWidget(header)

        # ---- code area ----
        self._code_edit = QtWidgets.QTextEdit()
        self._code_edit.setReadOnly(True)
        self._code_edit.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self._code_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._code_edit.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._code_edit.setObjectName("codeBlockEdit")

        highlighted = self._highlight()
        code_html = self._add_line_numbers(highlighted) if self._show_line_numbers else highlighted
        self._code_edit.setHtml(
            f'<pre style="margin:0;white-space:pre;">{code_html}</pre>'
        )
        doc = self._code_edit.document()
        doc.setDocumentMargin(4)

        # ★ 用行高×行数估算高度 — doc.size() 在 widget 未 show() 时是懒布局值，
        #   不可靠，导致 setFixedHeight 过小，手动跨行选中时内容被截断。
        #   showEvent 里会用真实文档高度校正一次（兜底）。
        fm = self._code_edit.fontMetrics()
        line_h = fm.lineSpacing() if fm.lineSpacing() > 0 else 17
        self._full_h = line_h * self._line_count + 24 + int(doc.documentMargin()) * 2

        # 计算折叠高度（COLLAPSE_THRESHOLD 行）
        self._collapsed_h = self._COLLAPSE_THRESHOLD * line_h + 20

        if self._collapsed:
            self._code_edit.setFixedHeight(min(self._collapsed_h, self._MAX_HEIGHT))
            self._code_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        else:
            self._code_edit.setFixedHeight(min(self._full_h, self._MAX_HEIGHT))

        layout.addWidget(self._code_edit)

    def showEvent(self, event):
        """首次显示后用真实文档高度校正 — 消除懒布局估算偏差"""
        super().showEvent(event)
        if not self._collapsed:
            real_h = int(self._code_edit.document().size().height()) + 20
            if real_h != self._full_h:
                self._full_h = real_h
                self._code_edit.setFixedHeight(min(real_h, self._MAX_HEIGHT))

    def _add_line_numbers(self, highlighted_code: str) -> str:
        """为高亮代码添加行号（使用 HTML table 布局）"""
        lines = highlighted_code.split('\n')
        width = len(str(len(lines)))
        result: list = []
        num_color = '#4a5568'  # 暗灰色行号
        sep_color = 'rgba(255,255,255,6)'  # 分隔线

        for i, line in enumerate(lines, 1):
            num = str(i).rjust(width)
            result.append(
                f'<span style="color:{num_color};user-select:none;'
                f'padding-right:12px;border-right:1px solid {sep_color};'
                f'margin-right:12px;">{num}</span>{line}'
            )
        return '\n'.join(result)

    def _toggle_collapse(self):
        """切换代码块折叠/展开"""
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._code_edit.setFixedHeight(min(self._collapsed_h, self._MAX_HEIGHT))
            self._code_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._code_edit.verticalScrollBar().setValue(0)
            self._toggle_btn.setText(f"展开 ({self._line_count} 行)")
        else:
            self._code_edit.setFixedHeight(min(self._full_h, self._MAX_HEIGHT))
            if self._full_h > self._MAX_HEIGHT:
                self._code_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            else:
                self._code_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self._toggle_btn.setText("收起")

    # --- helpers ---
    def _normalize_language(self, language: str) -> str:
        lang = (language or '').strip().lower()
        if lang in ('text', 'txt', 'plain', 'plaintext', 'none'):
            return 'text'
        if lang in ('c', 'cpp', 'c++', 'cxx', 'h', 'hpp') and self._is_vex():
            return 'vex'
        return lang

    def _is_vex(self) -> bool:
        return any(ind in self._code for ind in self._VEX_INDICATORS)

    def _highlight(self) -> str:
        lang = self._lang
        # VEX 自动检测
        if lang in ('vex', 'vfl') or (not lang and self._is_vex()):
            return SyntaxHighlighter.highlight_vex(self._code)
        # Python
        if lang in ('python', 'py'):
            return SyntaxHighlighter.highlight_python(self._code)
        # JSON
        if lang == 'json':
            return SyntaxHighlighter.highlight_json(self._code)
        # YAML
        if lang in ('yaml', 'yml'):
            return SyntaxHighlighter.highlight_yaml(self._code)
        # Bash / Shell
        if lang in ('bash', 'sh', 'shell', 'zsh', 'powershell', 'ps1', 'bat', 'cmd'):
            return SyntaxHighlighter.highlight_bash(self._code)
        # JavaScript / TypeScript
        if lang in ('javascript', 'js', 'typescript', 'ts', 'jsx', 'tsx'):
            return SyntaxHighlighter.highlight_javascript(self._code)
        # HScript
        if lang in ('hscript', 'hs'):
            return SyntaxHighlighter.highlight_hscript(self._code)
        # GLSL / HLSL / shader
        if lang in ('glsl', 'hlsl', 'shader', 'frag', 'vert', 'wgsl'):
            return SyntaxHighlighter.highlight_glsl(self._code)
        # C / C++ / C# (use GLSL tokenizer as base — similar syntax)
        if lang in ('c', 'cpp', 'c++', 'cxx', 'h', 'hpp', 'cs', 'csharp'):
            return SyntaxHighlighter.highlight_glsl(self._code)
        # XML / HTML — use plain escaped (simple approach)
        if lang in ('xml', 'html', 'svg'):
            return html.escape(self._code)
        if lang == 'text':
            return html.escape(self._code)
        # Fallback: no highlighting
        return html.escape(self._code)

    def enterEvent(self, event):
        for btn in self._action_btns:
            btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        for btn in self._action_btns:
            btn.setVisible(False)
        super().leaveEvent(event)

    def _on_copy(self):
        QtWidgets.QApplication.clipboard().setText(self._code)
        btn = self.sender()
        if btn:
            btn.setText("已复制")
            QtCore.QTimer.singleShot(1500, lambda: btn.setText("复制"))

    # _btn_css removed — styling now via QSS objectName selectors


# ============================================================
# 富文本内容组件
# ============================================================

class RichContentWidget(QtWidgets.QWidget):
    """渲染 Markdown 文本 + 交互式代码块

    采用与 Cursor / GitHub Copilot Chat 类似的排版风格：
    - 文本段落紧凑、行高舒适
    - 代码块与正文之间有清晰分隔
    - 表格、链接、列表等完整支持
    - Houdini 节点路径自动变为可点击链接
    """

    createWrangleRequested = QtCore.Signal(str)
    nodePathClicked = QtCore.Signal(str)  # 节点路径被点击

    # _TEXT_STYLE removed — use objectName-based QSS instead

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)  # 段落间距由 HTML margin 控制

        segments = SimpleMarkdown.parse_segments(text)

        for seg in segments:
            if seg[0] == 'text':
                lbl = QtWidgets.QLabel()
                lbl.setWordWrap(True)
                lbl.setTextFormat(QtCore.Qt.RichText)
                lbl.setOpenExternalLinks(False)  # 我们自己处理链接
                lbl.setTextInteractionFlags(
                    QtCore.Qt.TextSelectableByMouse
                    | QtCore.Qt.LinksAccessibleByMouse
                )
                lbl.setText(seg[1])
                lbl.setObjectName("richText")
                lbl.linkActivated.connect(self._on_link)
                layout.addWidget(lbl)
            elif seg[0] == 'code':
                cb = CodeBlockWidget(seg[2], seg[1], self)
                cb.createWrangleRequested.connect(self.createWrangleRequested.emit)
                cb.setContentsMargins(0, 6, 0, 6)
                layout.addWidget(cb)
            elif seg[0] == 'image':
                img_url = seg[1]
                img_alt = seg[2] if len(seg) > 2 else ''
                img_lbl = QtWidgets.QLabel()
                img_lbl.setObjectName("richImage")
                img_lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                img_lbl.setWordWrap(False)
                img_lbl.setText(
                    f'<div style="margin:4px 0;">'
                    f'<img src="{html.escape(img_url)}" '
                    f'alt="{html.escape(img_alt)}" '
                    f'style="max-width:100%;max-height:300px;border-radius:6px;">'
                    f'</div>'
                )
                img_lbl.setTextFormat(QtCore.Qt.RichText)
                layout.addWidget(img_lbl)

    def _on_link(self, url: str):
        """处理链接点击"""
        if url.startswith('houdini://'):
            self.nodePathClicked.emit(url[len('houdini://'):])
        else:
            # 外部链接用浏览器打开
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
