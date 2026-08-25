# -*- coding: utf-8 -*-
"""Chat, status, and operation preview widgets."""

import html
import time
from typing import List, Optional

from houdini_agent.qt_compat import QtWidgets, QtCore, QtGui, safe_single_shot

from .cursor_theme import CursorTheme
from .i18n import tr
from .node_links import _linkify_node_paths, _linkify_node_paths_plain
from .cursor_rich_content import CodeBlockWidget, PythonShellWidget, RichContentWidget, SimpleMarkdown, SystemShellWidget


def _fmt_duration(seconds: float) -> str:
    """格式化时长: <60s -> '18s', >=60s -> '1m43s'"""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m{s % 60:02d}s"


# ============================================================
# 流光边框 — AI 响应活跃时在左侧显示流动渐变光带
# ============================================================

class AuroraBar(QtWidgets.QWidget):
    """流动渐变光带 — 放在 AIResponse 左侧，AI 回复期间持续流动。

    宽度仅 3px，银白单色系。通过在固定等距停靠点上采样
    一条虚拟循环色带（带相位偏移），保证停靠点始终递增，
    消除跳变伪影。停止后凝固为极淡银灰色。
    """

    _NUM_STOPS = 10  # 渐变采样点数量，越多越平滑

    def __init__(self, parent=None, username: Optional[str] = None):
        super().__init__(parent)
        self.setFixedWidth(3)
        self._phase = 0.0
        self._active = False
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)  # ~33 fps
        self._timer.timeout.connect(self._tick)
        # 循环色带关键色（首尾相同 → 无缝衔接）
        self._key_colors = [
            QtGui.QColor(226, 232, 240, 200),  # 亮银白
            QtGui.QColor(100, 116, 139, 100),   # 暗银
            QtGui.QColor(226, 232, 240, 200),   # 亮银白（循环闭合）
        ]

    # -- public API --------------------------------------------------

    def start(self):
        """启动流光动画"""
        self._active = True
        self._phase = 0.0
        self.setFixedWidth(3)
        self.setVisible(True)
        self._timer.start()
        self.update()

    def stop(self):
        """停止流光动画，收缩为零宽度以保持卡片干净"""
        self._active = False
        self._timer.stop()
        self.setFixedWidth(0)
        self.update()

    @property
    def running(self) -> bool:
        return self._active

    # -- internal ----------------------------------------------------

    def _tick(self):
        self._phase += 0.006
        if self._phase >= 1.0:
            self._phase -= 1.0
        self.update()

    def _sample(self, t: float) -> QtGui.QColor:
        """在虚拟循环色带上采样，t ∈ [0, 1]，平滑插值。"""
        keys = self._key_colors
        n = len(keys) - 1  # 段数（首尾同色 → n 段覆盖一整圈）
        scaled = (t % 1.0) * n
        idx = int(scaled)
        frac = scaled - idx
        c1 = keys[idx]
        c2 = keys[min(idx + 1, n)]
        return QtGui.QColor(
            int(c1.red()   + (c2.red()   - c1.red())   * frac),
            int(c1.green() + (c2.green() - c1.green()) * frac),
            int(c1.blue()  + (c2.blue()  - c1.blue())  * frac),
            int(c1.alpha() + (c2.alpha() - c1.alpha()) * frac),
        )

    def paintEvent(self, event):  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect()
        if self._active:
            grad = QtGui.QLinearGradient(0, 0, 0, rect.height())
            for i in range(self._NUM_STOPS + 1):
                pos = i / self._NUM_STOPS          # 固定递增 0.0 → 1.0
                color = self._sample(pos + self._phase)  # 相位偏移
                grad.setColorAt(pos, color)
            p.fillRect(rect, grad)
        else:
            p.fillRect(rect, QtGui.QColor(148, 163, 184, 50))
        p.end()


# ============================================================
# 可折叠区块（通用）
# ============================================================

class CollapsibleSection(QtWidgets.QWidget):
    """可折叠区块 - 点击标题展开/收起"""
    
    def __init__(self, title: str, icon: str = "", collapsed: bool = True, parent=None):
        super().__init__(parent)
        self._collapsed = collapsed
        self._title = title
        self._icon = icon
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)
        
        # 标题栏（可点击）
        self.header = QtWidgets.QPushButton()
        self.header.setFlat(True)
        self.header.setCursor(QtCore.Qt.PointingHandCursor)
        self.header.clicked.connect(self.toggle)
        self._update_header()
        self.header.setObjectName("collapseHeader")
        layout.addWidget(self.header)
        
        # 内容区
        self.content_widget = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(6, 4, 4, 4)
        self.content_layout.setSpacing(2)
        self.content_widget.setObjectName("collapseContent")
        layout.addWidget(self.content_widget)
        # ★ 必须在 addWidget 之后再 setVisible，否则无 parent 的 widget 会闪烁为独立窗口
        self.content_widget.setVisible(not collapsed)
    
    def _update_header(self):
        arrow = "▶" if self._collapsed else "▼"
        icon_part = f"{self._icon} " if self._icon else ""
        self.header.setText(f"{arrow} {icon_part}{self._title}")
    
    def toggle(self):
        self._collapsed = not self._collapsed
        self.content_widget.setVisible(not self._collapsed)
        self._update_header()
    
    def set_title(self, title: str):
        self._title = title
        self._update_header()
    
    def expand(self):
        if self._collapsed:
            self.toggle()
    
    def collapse(self):
        if not self._collapsed:
            self.toggle()
    
    def add_widget(self, widget: QtWidgets.QWidget):
        self.content_layout.addWidget(widget)
    
    def add_text(self, text: str, style: str = "normal"):
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        label.setObjectName("collapseText")
        label.setProperty("textStyle", style)
        self.content_layout.addWidget(label)
        return label


# ============================================================
# 脉冲指示器
# ============================================================

class PulseIndicator(QtWidgets.QWidget):
    """小型脉冲圆点 — 通过 opacity 动画表示"正在进行"状态"""

    def __init__(self, color: str = CursorTheme.ACCENT_PURPLE, size: int = 8, parent=None):
        super().__init__(parent)
        self._color = QtGui.QColor(color)
        self._dot_size = size
        self._opacity = 1.0
        self.setFixedSize(size + 6, size + 6)

        self._anim = QtCore.QPropertyAnimation(self, b"pulseOpacity")
        self._anim.setDuration(1200)
        self._anim.setStartValue(0.25)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QtCore.QEasingCurve.InOutSine)
        self._anim.setLoopCount(-1)  # 无限循环

    # ---- Qt Property ----
    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, v):
        self._opacity = v
        self.update()

    pulseOpacity = QtCore.Property(float, _get_opacity, _set_opacity)

    def start(self):
        self._anim.start()

    def stop(self):
        self._anim.stop()
        self._opacity = 0.0
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c = QtGui.QColor(self._color)
        c.setAlphaF(self._opacity)
        p.setBrush(c)
        p.setPen(QtCore.Qt.NoPen)
        x = (self.width() - self._dot_size) / 2
        y = (self.height() - self._dot_size) / 2
        p.drawEllipse(QtCore.QRectF(x, y, self._dot_size, self._dot_size))
        p.end()


# ============================================================
# 思考过程区块（无内置脉冲，动画移至输入框上方）
# ============================================================

class ThinkingSection(CollapsibleSection):
    """思考过程 - 显示 AI 的思考内容（支持多轮思考累计计时）
    
    脉冲/动画指示器已移至输入框上方的 ThinkingBar，此处仅做内容展示。
    ★ 使用 QPlainTextEdit(readOnly)，自带滚动条。
    高度计算采用与 ChatInput 相同的可靠方案：
      QTimer.singleShot(0) 延迟 + 逐块 block.layout().lineCount() 统计视觉行。
    """
    
    # 最大高度（像素），超过此值则固定高度，内置滚动条自动出现
    _MAX_HEIGHT_PX = 400
    
    def __init__(self, parent=None):
        # ★ 默认展开（用户要求不自动折叠）；section 整体初始 setVisible(False)，
        #   首次收到思考内容时 setVisible(True) 即可，内容区已处于展开状态。
        super().__init__(tr('thinking.init'), icon="", collapsed=False, parent=parent)
        # ★ 防止被父布局拉伸 —— 内容多大就多大
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Maximum,
        )
        self._thinking_text = ""
        self._start_time = time.time()
        self._accumulated_seconds = 0.0
        self._round_start = time.time()
        self._round_count = 0
        
        # ★ 思考内容 — QPlainTextEdit(readOnly)，自带滚动条
        self._text_font = QtGui.QFont(CursorTheme.FONT_BODY)
        self._text_font.setPixelSize(13)
        
        self.thinking_label = QtWidgets.QPlainTextEdit()
        self.thinking_label.setReadOnly(True)
        self.thinking_label.setFont(self._text_font)
        self.thinking_label.document().setDefaultFont(self._text_font)
        self.thinking_label.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.thinking_label.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.thinking_label.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.thinking_label.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.thinking_label.setObjectName("thinkLabel")
        # 初始高度为一行（紧凑），流式输入时会动态增大
        self._line_h = QtGui.QFontMetrics(self._text_font).lineSpacing()
        self.thinking_label.setFixedHeight(self._line_h + 12)
        self.content_layout.addWidget(self.thinking_label)
        
        # 标题样式
        self.header.setObjectName("thinkHeader")
    
    def _update_height(self):
        """根据视觉行数（含自动换行）动态调整高度。
        
        与 ChatInput._adjust_height 相同的可靠方案：
        逐块遍历 block.layout().lineCount() 统计真实视觉行数。
        """
        doc = self.thinking_label.document()
        visual_lines = 0
        block = doc.begin()
        while block.isValid():
            bl = block.layout()
            if bl and bl.lineCount() > 0:
                visual_lines += bl.lineCount()
            else:
                visual_lines += 1
            block = block.next()
        visual_lines = max(1, visual_lines)
        
        desired = self._line_h * visual_lines + 12   # 12 = padding
        self.thinking_label.setFixedHeight(min(max(desired, self._line_h + 12), self._MAX_HEIGHT_PX))
    
    def _scroll_to_bottom(self):
        """滚动到底部"""
        vbar = self.thinking_label.verticalScrollBar()
        vbar.setValue(vbar.maximum())
    
    def _total_elapsed(self) -> float:
        if self._finalized:
            return self._accumulated_seconds
        return self._accumulated_seconds + (time.time() - self._round_start)
    
    def append_thinking(self, text: str):
        if '\ufffd' in text:
            text = text.replace('\ufffd', '')
        self._thinking_text += text
        self.thinking_label.setPlainText(self._thinking_text)
        # ★ 延迟到下一事件循环（确保 Qt 布局完成后再计算高度，和 ChatInput 同策略）
        safe_single_shot(0, self, '_update_height')
        safe_single_shot(0, self, '_scroll_to_bottom')
    
    def update_time(self):
        if self._finalized:
            return
        self.set_title(tr('thinking.progress', _fmt_duration(self._total_elapsed())))
    
    @property
    def _finalized(self):
        return getattr(self, '_is_finalized', False)
    
    def resume(self):
        self._is_finalized = False
        self._round_start = time.time()
        self._round_count += 1
        self._thinking_text += f"\n{tr('thinking.round', self._round_count + 1)}\n"
        self.thinking_label.setPlainText(self._thinking_text)
        safe_single_shot(0, self, '_update_height')
        self.set_title(tr('thinking.progress', _fmt_duration(self._total_elapsed())))
        # ★ 始终确保展开
        self.expand()
    
    def finalize(self):
        if self._finalized:
            return
        self._is_finalized = True
        self._accumulated_seconds += (time.time() - self._round_start)
        total = self._accumulated_seconds
        self.set_title(tr('thinking.done', _fmt_duration(total)))
        # ★ 防御性展开：确保思考区块在任何情况下都保持展开
        self.expand()


# ============================================================
# 输入框上方 "思考中" 指示条（流光动画）
# ============================================================

class ThinkingBar(QtWidgets.QWidget):
    """显示在输入框上方的思考状态指示条。
    
    文字上有从左到右扫过的高亮流光效果，
    提示用户 AI 正在推理，替代原 ThinkingSection 内置的脉冲圆点。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setVisible(False)

        self._elapsed = 0.0   # 秒
        self._phase = 0.0     # 流光相位 [0, 1]

        # 流光定时器 ~25fps
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def start(self):
        self._elapsed = 0.0
        self._phase = 0.0
        self.setVisible(True)
        self._timer.start()
        self.update()

    def stop(self):
        self._timer.stop()
        self.setVisible(False)

    def set_elapsed(self, seconds: float):
        self._elapsed = seconds
        self.update()

    def _tick(self):
        self._phase += 0.025
        if self._phase > 1.0:
            self._phase -= 1.0
        self.update()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing)

        s = int(self._elapsed)
        time_str = f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s"
        display = f"  ✦ {tr('thinking.progress', time_str)}"

        font = QtGui.QFont(CursorTheme.FONT_BODY, 9)
        p.setFont(font)
        fm = QtGui.QFontMetrics(font)
        y = (self.height() + fm.ascent() - fm.descent()) // 2

        x = 8
        for i, ch in enumerate(display):
            char_pos = i / max(len(display), 1)
            dist = abs(char_pos - self._phase)
            dist = min(dist, 1.0 - dist)
            glow = max(0.0, 1.0 - dist * 5.0)

            base = QtGui.QColor(CursorTheme.ACCENT_PURPLE)
            muted = QtGui.QColor(CursorTheme.TEXT_MUTED)
            r = int(muted.red()   + (base.red()   - muted.red())   * glow)
            g = int(muted.green() + (base.green() - muted.green()) * glow)
            b = int(muted.blue()  + (base.blue()  - muted.blue())  * glow)

            p.setPen(QtGui.QColor(r, g, b))
            p.drawText(x, y, ch)
            x += fm.horizontalAdvance(ch)

        p.end()


# ============================================================
# 确认模式 — 内联预览确认控件（替代弹窗）
# ============================================================

class VEXPreviewInline(QtWidgets.QFrame):
    """嵌入对话流中的工具执行预览卡片。
    
    用户点击 ✓ 确认 或 ✕ 取消后通过 confirmed / cancelled 信号通知。
    """

    confirmed = QtCore.Signal()
    cancelled = QtCore.Signal()

    def __init__(self, tool_name: str, args: dict, parent=None):
        super().__init__(parent)
        self._decided = False
        # ★ 卡片整体不允许被父布局拉伸 —— 内容多大就多大
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Maximum,
        )
        self.setObjectName("vexPreviewInline")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(3)

        # 标题行
        title = QtWidgets.QLabel(tr('confirm.title', tool_name))
        title.setObjectName("vexPreviewTitle")
        title.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(title)

        # ★ 紧凑参数摘要（只显示关键参数，每个一行，最多 6 行）
        # ★ remember_memory 的 content 必须完整展示（上限 2000 字符），
        #   因为用户确认的依据就是这段将要写入长期记忆的总结内容。
        full_value_keys = {"content"} if tool_name == "remember_memory" else frozenset()
        summary_lines = []
        for k, v in args.items():
            sv = str(v)
            if k not in full_value_keys and len(sv) > 120:
                sv = sv[:117] + "..."
            summary_lines.append(f"  {k}: {sv}")
        if summary_lines:
            summary_text = "\n".join(summary_lines[:6])
            if len(summary_lines) > 6:
                summary_text += f"\n  {tr('confirm.params_more', len(summary_lines))}"
            summary_lbl = QtWidgets.QLabel(summary_text)
            summary_lbl.setWordWrap(True)
            summary_lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            summary_lbl.setObjectName("vexInlineSummary")
            summary_lbl.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding,
                QtWidgets.QSizePolicy.Maximum,
            )
            layout.addWidget(summary_lbl)

        # 按钮行（右对齐，紧凑）
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch()

        btn_cancel = QtWidgets.QPushButton(tr('confirm.cancel'))
        btn_cancel.setCursor(QtCore.Qt.PointingHandCursor)
        btn_cancel.setFixedHeight(24)
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(btn_cancel)

        btn_confirm = QtWidgets.QPushButton(tr('confirm.execute'))
        btn_confirm.setCursor(QtCore.Qt.PointingHandCursor)
        btn_confirm.setFixedHeight(24)
        btn_confirm.setObjectName("btnConfirmGreen")
        btn_confirm.clicked.connect(self._on_confirm)
        btn_row.addWidget(btn_confirm)

        layout.addLayout(btn_row)

    def _on_confirm(self):
        if self._decided:
            return
        self._decided = True
        # ★ 确认后直接隐藏整个卡片，不再显示"已确认执行"内嵌窗口
        self.setVisible(False)
        self.setFixedHeight(0)
        self.confirmed.emit()

    def _on_cancel(self):
        if self._decided:
            return
        self._decided = True
        # ★ 取消也直接隐藏整个卡片（和确认一致），不要内嵌窗口
        self.setVisible(False)
        self.setFixedHeight(0)
        self.cancelled.emit()

    def _show_decided(self, text: str, color: str):
        """决策后将整个卡片替换为简短状态"""
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            sub = item.layout()
            if sub:
                while sub.count():
                    si = sub.takeAt(0)
                    sw = si.widget()
                    if sw:
                        sw.deleteLater()
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("vexPreviewStatus")
        lbl.setProperty("state", "confirmed" if color == CursorTheme.ACCENT_GREEN else "cancelled")
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)
        layout.addWidget(lbl)
        self.setFixedHeight(30)


# ============================================================
# 工具调用项
# ============================================================

class ToolCallItem(CollapsibleSection):
    """单个工具调用 — CollapsibleSection 风格（与 Result 折叠一致的灰色风格）
    
    标题栏：▶ tool_name            （执行中）
           ▶ tool_name (1.2s)      （完成）
    展开后显示完整 result 文本，节点路径可点击跳转。
    """

    nodePathClicked = QtCore.Signal(str)  # 节点路径被点击

    def __init__(self, tool_name: str, parent=None):
        super().__init__(tool_name, icon="", collapsed=True, parent=parent)
        self.tool_name = tool_name
        self._result = None
        self._success = None
        self._start_time = time.time()

        self.header.setObjectName("toolCallHeader")

        # 进度条（嵌入 content_layout 顶部，执行完毕后隐藏）
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedHeight(2)
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setObjectName("toolProgress")
        self.content_layout.addWidget(self.progress_bar)

        self._result_label = None

    def set_result(self, result: str, success: bool = True):
        """设置工具执行结果"""
        self._result = result
        self._success = success
        elapsed = time.time() - self._start_time

        # 隐藏进度条
        self.progress_bar.setVisible(False)

        # 更新标题：只显示工具名 + 耗时，无图标
        self.set_title(f"{self.tool_name} ({elapsed:.1f}s)")

        # 失败时标题用白色（更亮），成功保持灰色
        if not success:
            self.header.setProperty("state", "failed")
            self.header.style().unpolish(self.header)
            self.header.style().polish(self.header)

        # 添加结果文本（灰色，失败时白色）—— 节点路径可点击
        if result.strip():
            rich_html = _linkify_node_paths_plain(result)
            self._result_label = QtWidgets.QLabel(rich_html)
            self._result_label.setWordWrap(True)
            self._result_label.setTextFormat(QtCore.Qt.RichText)
            self._result_label.setOpenExternalLinks(False)
            self._result_label.setTextInteractionFlags(
                QtCore.Qt.TextSelectableByMouse | QtCore.Qt.LinksAccessibleByMouse
            )
            self._result_label.linkActivated.connect(self._on_result_link)
            self._result_label.setObjectName("toolResultLabel")
            if not success:
                self._result_label.setProperty("state", "failed")
            self.content_layout.addWidget(self._result_label)

    def _on_result_link(self, url: str):
        """工具结果中的链接被点击"""
        if url.startswith('houdini://'):
            self.nodePathClicked.emit(url[len('houdini://'):])


# ============================================================
# 执行过程区块
# ============================================================

class ExecutionSection(CollapsibleSection):
    """执行过程 - 卡片式工具调用显示（默认折叠，用户手动展开）"""

    nodePathClicked = QtCore.Signal(str)  # 从子 ToolCallItem 冒泡上来

    def __init__(self, parent=None):
        super().__init__(tr('exec.running'), icon="", collapsed=True, parent=parent)
        self._tool_calls: List[ToolCallItem] = []
        self._start_time = time.time()
        
        # 更新标题样式
        self.header.setObjectName("execHeader")
    
    def add_tool_call(self, tool_name: str) -> ToolCallItem:
        """添加工具调用"""
        item = ToolCallItem(tool_name, self)
        item.nodePathClicked.connect(self.nodePathClicked.emit)
        self._tool_calls.append(item)
        self.content_layout.addWidget(item)
        self._update_title()
        return item
    
    def set_tool_result(self, tool_name: str, result: str, success: bool = True):
        """设置工具结果"""
        # 找到最后一个匹配的工具调用
        for item in reversed(self._tool_calls):
            if item.tool_name == tool_name and item._result is None:
                item.set_result(result, success)
                break
        self._update_title()
    
    def _update_title(self):
        """更新标题"""
        total = len(self._tool_calls)
        done = sum(1 for item in self._tool_calls if item._result is not None)
        if done < total:
            self.set_title(tr('exec.progress', done, total))
        else:
            elapsed = time.time() - self._start_time
            self.set_title(tr('exec.done', total, _fmt_duration(elapsed)))
    
    def finalize(self):
        """完成执行"""
        elapsed = time.time() - self._start_time
        total = len(self._tool_calls)
        
        # ⚠️ 兜底：强制关闭所有残留的进度条
        for item in self._tool_calls:
            if item._result is None:
                item.progress_bar.setVisible(False)
                item_elapsed = time.time() - item._start_time
                item.set_title(f"{item.tool_name} ({item_elapsed:.1f}s)")
                item._result = ""  # 标记已完成，避免被重复处理
                item._success = True
        
        success = sum(1 for item in self._tool_calls if item._success)
        failed = total - success
        
        if failed > 0:
            self.set_title(tr('exec.done_err', success, failed, _fmt_duration(elapsed)))
        else:
            self.set_title(tr('exec.done', total, _fmt_duration(elapsed)))


# ============================================================
# 图片预览弹窗（点击缩略图放大查看）
# ============================================================

class ImagePreviewDialog(QtWidgets.QDialog):
    """模态图片预览弹窗 — 点击缩略图后弹出，显示原尺寸/自适应窗口的大图"""

    def __init__(self, pixmap: QtGui.QPixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('img.preview'))
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMaximizeButtonHint)
        self._pixmap = pixmap

        # 根据图片尺寸决定初始窗口大小（不超过屏幕 80%）
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            max_w, max_h = int(avail.width() * 0.8), int(avail.height() * 0.8)
        else:
            max_w, max_h = 1200, 800
        init_w = min(pixmap.width() + 40, max_w)
        init_h = min(pixmap.height() + 40, max_h)
        self.resize(init_w, init_h)

        # 深色背景
        self.setObjectName("imgPreviewDlg")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 可滚动区域
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(QtCore.Qt.AlignCenter)
        scroll.setObjectName("chatScrollArea")

        self._img_label = QtWidgets.QLabel()
        self._img_label.setAlignment(QtCore.Qt.AlignCenter)
        scroll.setWidget(self._img_label)
        layout.addWidget(scroll)

        # 底栏：尺寸信息 + 关闭按钮
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(12, 4, 12, 8)
        info = QtWidgets.QLabel(f"{pixmap.width()} × {pixmap.height()} px")
        info.setObjectName("imgInfoLabel")
        bar.addWidget(info)
        bar.addStretch()
        close_btn = QtWidgets.QPushButton(tr('btn.close'))
        close_btn.setObjectName("imgCloseBtn")
        close_btn.clicked.connect(self.close)
        bar.addWidget(close_btn)
        layout.addLayout(bar)

        self._update_preview()

    def _update_preview(self):
        """根据窗口大小缩放图片（保持比例）"""
        viewport_w = self.width() - 20
        viewport_h = self.height() - 50
        if self._pixmap.width() > viewport_w or self._pixmap.height() > viewport_h:
            scaled = self._pixmap.scaled(
                viewport_w, viewport_h,
                QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        else:
            scaled = self._pixmap
        self._img_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
        super().keyPressEvent(event)


class ClickableImageLabel(QtWidgets.QLabel):
    """可点击的图片缩略图 — 点击后弹出 ImagePreviewDialog 放大查看"""

    def __init__(self, thumb_pixmap: QtGui.QPixmap, full_pixmap: QtGui.QPixmap, parent=None):
        super().__init__(parent)
        self._full_pixmap = full_pixmap
        self.setPixmap(thumb_pixmap)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(tr('img.click_zoom'))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            dlg = ImagePreviewDialog(self._full_pixmap, self.window())
            dlg.exec()
        else:
            super().mousePressEvent(event)


# ============================================================
# 用户消息
# ============================================================

class UserMessage(QtWidgets.QWidget):
    """用户消息 - 支持折叠（超过 2 行时自动折叠，点击展开/收起）"""

    _COLLAPSED_MAX_LINES = 2  # 折叠时显示的最大行数

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full_text = text
        self._collapsed = False  # 初始状态由 _maybe_collapse 决定

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(0)

        # ---- 主容器（带左边框） ----
        self._container = QtWidgets.QWidget()
        self._container.setObjectName("userMsgContainer")
        container_layout = QtWidgets.QVBoxLayout(self._container)
        container_layout.setContentsMargins(12, 8, 12, 4)
        container_layout.setSpacing(2)

        # ---- 内容标签 ----
        self.content = QtWidgets.QLabel(text)
        self.content.setWordWrap(True)
        self.content.setTextFormat(QtCore.Qt.PlainText)
        self.content.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.content.setObjectName("userMsgText")
        container_layout.addWidget(self.content)

        # ---- 展开/收起 按钮 ----
        self._toggle_btn = QtWidgets.QPushButton()
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._toggle_btn.setFixedHeight(20)
        self._toggle_btn.setObjectName("userMsgToggle")
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        self._toggle_btn.setVisible(False)  # 默认隐藏，_maybe_collapse 决定
        container_layout.addWidget(self._toggle_btn)

        layout.addWidget(self._container)

        # 延迟判断是否需要折叠（等 QLabel 完成布局后再算行数）
        safe_single_shot(0, self, '_maybe_collapse')

    # ------------------------------------------------------------------
    def _maybe_collapse(self):
        """检查文本是否超过阈值行数，超过则自动折叠"""
        line_count = self._full_text.count('\n') + 1
        if line_count > self._COLLAPSED_MAX_LINES:
            self._collapsed = True
            self._apply_collapsed()
            self._toggle_btn.setVisible(True)
        else:
            # 文字不够多，不需要折叠按钮
            self._toggle_btn.setVisible(False)

    def _apply_collapsed(self):
        """应用折叠状态：只显示前 N 行 + 省略号"""
        lines = self._full_text.split('\n')
        preview = '\n'.join(lines[:self._COLLAPSED_MAX_LINES])
        if len(lines) > self._COLLAPSED_MAX_LINES:
            preview += ' …'
        self.content.setText(preview)
        remaining = len(lines) - self._COLLAPSED_MAX_LINES
        self._toggle_btn.setText(tr('msg.expand', remaining))

    def _apply_expanded(self):
        """应用展开状态：显示完整文本"""
        self.content.setText(self._full_text)
        self._toggle_btn.setText(tr('msg.collapse'))

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._apply_collapsed()
        else:
            self._apply_expanded()


# ============================================================
# AI 回复块（重构版）
# ============================================================

class AIResponse(QtWidgets.QWidget):
    """AI 回复 - Cursor 风格
    
    结构：
    +-- 思考过程（可折叠，默认折叠）
    +-- 执行过程（可折叠，默认折叠）
    +-- 总结（Markdown 渲染 + 代码块高亮）
    """
    
    createWrangleRequested = QtCore.Signal(str)  # vex_code
    nodePathClicked = QtCore.Signal(str)         # 节点路径被点击
    feedbackGiven = QtCore.Signal(bool)          # 用户反馈 True=👍 False=👎

    def __init__(self, parent=None, session_node_map: dict = None):
        super().__init__(parent)
        self._session_node_map = session_node_map if session_node_map is not None else {}
        self._start_time = time.time()
        self._content = ""
        self._has_thinking = False
        self._has_execution = False
        self._shell_count = 0  # Python Shell 执行计数
        
        # ★ 增量渲染状态
        self._frozen_segments: list = []    # 已冻结的富文本段落
        self._pending_text = ""             # 尚未冻结的尾部文本
        self._in_code_fence = False         # 是否在代码块内
        self._code_fence_lang = ""          # 代码块语言
        self._incremental_enabled = True    # 是否启用增量渲染
        
        # ★ 顶层水平布局：AuroraBar（左）+ 内容（右）
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 8)
        outer.setSpacing(0)
        
        # 流光边框（AI 响应活跃时流动）
        self.aurora_bar = AuroraBar(self)
        outer.addWidget(self.aurora_bar)
        
        # 内容列
        content_col = QtWidgets.QVBoxLayout()
        content_col.setContentsMargins(0, 0, 0, 0)
        content_col.setSpacing(4)
        outer.addLayout(content_col, 1)
        
        # 供外部引用（原来直接用 layout 的地方）
        layout = content_col
        
        # === 思考过程区块 ===
        self.thinking_section = ThinkingSection(self)
        self.thinking_section.setVisible(False)
        layout.addWidget(self.thinking_section)
        
        # === 执行过程区块 ===
        self.execution_section = ExecutionSection(self)
        self.execution_section.setVisible(False)
        self.execution_section.nodePathClicked.connect(self.nodePathClicked.emit)
        layout.addWidget(self.execution_section)
        
        # === Python Shell 区块（可折叠，默认折叠）===
        self.shell_section = CollapsibleSection("Python Shell", collapsed=True, parent=self)
        self.shell_section.setVisible(False)
        self.shell_section.header.setObjectName("shellHeaderPython")
        layout.addWidget(self.shell_section)
        
        # === System Shell 区块（可折叠，默认折叠）===
        self._sys_shell_count = 0
        self.sys_shell_section = CollapsibleSection("System Shell", collapsed=True, parent=self)
        self.sys_shell_section.setVisible(False)
        self.sys_shell_section.header.setObjectName("shellHeaderSystem")
        layout.addWidget(self.sys_shell_section)
        
        # === 总结/回复区域 ===
        self.summary_frame = QtWidgets.QFrame()
        self.summary_frame.setObjectName("aiSummary")
        self._summary_layout = QtWidgets.QVBoxLayout(self.summary_frame)
        self._summary_layout.setContentsMargins(8, 8, 6, 8)
        self._summary_layout.setSpacing(4)
        
        # 状态行（水平布局：状态文字 + 复制按钮）
        status_row = QtWidgets.QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        
        self.status_label = QtWidgets.QLabel(tr('thinking.init'))
        self.status_label.setObjectName("aiStatusLabel")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        
        # 复制全部按钮（完成后才显示）
        self._copy_btn = QtWidgets.QPushButton(tr('btn.copy'))
        self._copy_btn.setVisible(False)
        self._copy_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._copy_btn.setFixedHeight(22)
        self._copy_btn.setObjectName("aiCopyBtn")
        self._copy_btn.clicked.connect(self._copy_content)
        status_row.addWidget(self._copy_btn)

        # ★ 用户反馈按钮 👍/👎（finalize 后可见，仅在有工具调用时有意义）
        self._feedback_state = None  # None / True(👍) / False(👎)
        self._thumb_up_btn = QtWidgets.QPushButton(tr('feedback.up'))
        self._thumb_up_btn.setVisible(False)
        self._thumb_up_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._thumb_up_btn.setFixedHeight(22)
        self._thumb_up_btn.setObjectName("aiThumbUpBtn")
        self._thumb_up_btn.setToolTip(tr('feedback.good'))
        self._thumb_up_btn.clicked.connect(lambda: self._on_feedback(True))
        status_row.addWidget(self._thumb_up_btn)

        self._thumb_down_btn = QtWidgets.QPushButton(tr('feedback.down'))
        self._thumb_down_btn.setVisible(False)
        self._thumb_down_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._thumb_down_btn.setFixedHeight(22)
        self._thumb_down_btn.setObjectName("aiThumbDownBtn")
        self._thumb_down_btn.setToolTip(tr('feedback.bad'))
        self._thumb_down_btn.clicked.connect(lambda: self._on_feedback(False))
        status_row.addWidget(self._thumb_down_btn)

        self._summary_layout.addLayout(status_row)
        
        # ★ 独立的停止/警示横幅（默认隐藏）—— 与 status_label / content_label
        #   完全解耦，finalize 不会改写它，避免"执行完成/no_reply/Stopped"覆盖提醒。
        self._warning_banner = QtWidgets.QLabel()
        self._warning_banner.setObjectName("aiWarningBanner")
        self._warning_banner.setWordWrap(True)
        self._warning_banner.setVisible(False)
        self._summary_layout.addWidget(self._warning_banner)
        
        # ★ 已冻结段落容器 — 增量渲染时冻结的富文本/代码块放在这里
        self._frozen_container = QtWidgets.QWidget()
        self._frozen_layout = QtWidgets.QVBoxLayout(self._frozen_container)
        self._frozen_layout.setContentsMargins(0, 0, 0, 0)
        self._frozen_layout.setSpacing(0)  # 段落间距由 HTML margin 控制
        self._frozen_container.setVisible(False)
        self._summary_layout.addWidget(self._frozen_container)
        
        # 内容区域 —— 流式阶段使用 QPlainTextEdit（增量追加 O(1)），
        # finalize 时按需替换为 RichContentWidget（Markdown 渲染）。
        # ★ 关键：流式阶段的字体和间距必须与渲染后的 richText QLabel 一致，
        #   以避免 finalize 时产生"跳变"感。
        self.content_label = QtWidgets.QPlainTextEdit()
        self.content_label.setReadOnly(True)
        self.content_label.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.content_label.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.content_label.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.content_label.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        # 让 size hint 跟随内容自动增长（不设固定高度）
        self.content_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
        )
        self.content_label.setObjectName("aiContentLabel")
        # ★ 显式设置字体，确保流式和渲染后使用同一字体族和大小
        _stream_font = QtGui.QFont()
        _stream_font.setFamilies(['Microsoft YaHei', 'SimSun', 'Segoe UI'])
        _stream_font.setPixelSize(14)  # 与 {FS_MD}=14 一致
        self.content_label.setFont(_stream_font)
        self.content_label.document().setDefaultFont(_stream_font)
        # ★ 设置行间距为 1.6 倍，与 HTML 中的 line-height:1.6 保持一致
        self.content_label.document().setDocumentMargin(0)
        self._apply_line_spacing(160)  # 160% 行间距
        # 初始高度紧凑，流式输入时自动增长
        # 使用与 line-height 一致的行高计算
        fm = QtGui.QFontMetrics(_stream_font)
        self._content_line_h = int(fm.height() * 1.6)
        self.content_label.setFixedHeight(self._content_line_h + 4)
        self.content_label.document().contentsChanged.connect(self._auto_resize_content)
        self._summary_layout.addWidget(self.content_label)
        
        layout.addWidget(self.summary_frame)
        
        # === 详情区域（可折叠内容等）===
        self.details_layout = QtWidgets.QVBoxLayout()
        self.details_layout.setSpacing(2)
        layout.addLayout(self.details_layout)
    
    def add_thinking(self, text: str):
        """添加思考内容"""
        if not self._has_thinking:
            self._has_thinking = True
            self.thinking_section.setVisible(True)
            # 确保思考区块处于展开状态
            self.thinking_section.expand()
        self.thinking_section.append_thinking(text)
    
    def update_thinking_time(self):
        """更新思考时间（思考结束后不再更新状态标签）"""
        if self._has_thinking:
            if self.thinking_section._finalized:
                return  # 思考已结束，不再更新
            self.thinking_section.update_time()
            total = self.thinking_section._total_elapsed()
            self.status_label.setText(tr('thinking.progress', _fmt_duration(total)))
    
    def add_shell_widget(self, widget: 'PythonShellWidget'):
        """将 PythonShellWidget 添加到 Python Shell 折叠区块"""
        self._shell_count += 1
        if not self.shell_section.isVisible():
            self.shell_section.setVisible(True)
        self.shell_section.set_title(f"Python Shell ({self._shell_count})")
        self.shell_section.add_widget(widget)
    
    def add_sys_shell_widget(self, widget: 'SystemShellWidget'):
        """将 SystemShellWidget 添加到 System Shell 折叠区块"""
        self._sys_shell_count += 1
        if not self.sys_shell_section.isVisible():
            self.sys_shell_section.setVisible(True)
        self.sys_shell_section.set_title(f"System Shell ({self._sys_shell_count})")
        self.sys_shell_section.add_widget(widget)
    
    def add_status(self, text: str):
        """添加状态（处理工具调用）"""
        if text.startswith("[tool]"):
            tool_name = text[6:].strip()
            self._add_tool_call(tool_name)
        else:
            self.status_label.setText(text)
    
    def show_warning(self, text: str):
        """★ 在独立横幅显示警示（如自动停止原因），不受 finalize 覆盖。"""
        try:
            self._warning_banner.setText(text)
            self._warning_banner.setVisible(True)
        except RuntimeError:
            pass
    
    def _add_tool_call(self, tool_name: str):
        """添加工具调用"""
        if not self._has_execution:
            self._has_execution = True
            self.execution_section.setVisible(True)
        self.execution_section.add_tool_call(tool_name)
        self.status_label.setText(tr('exec.tool', tool_name))
    
    def add_tool_result(self, tool_name: str, result: str):
        """添加工具结果"""
        success = not result.startswith("[err]") and not result.startswith("错误") and not result.startswith("Error")
        clean_result = result.removeprefix("[ok] ").removeprefix("[err] ")
        self.execution_section.set_tool_result(tool_name, clean_result, success)
    
    def _apply_line_spacing(self, percent: int = 160):
        """为 QPlainTextEdit 设置 proportional 行间距。
        
        Qt 的 QPlainTextEdit 不直接支持 CSS line-height，
        需要通过 QTextBlockFormat.setLineHeight 来实现。
        percent: 160 = 1.6 倍行间距。
        """
        doc = self.content_label.document()
        cursor = QtGui.QTextCursor(doc)
        cursor.select(QtGui.QTextCursor.Document)
        fmt = QtGui.QTextBlockFormat()
        fmt.setLineHeight(percent, 1)  # 1 = ProportionalHeight
        cursor.mergeBlockFormat(fmt)

    def _auto_resize_content(self):
        """根据 document 的实际渲染高度动态调整 QPlainTextEdit 的高度。
        
        使用 doc.size().height() 获取已布局的真实像素高度，
        加上一个小的底部边距作为最终高度。
        """
        doc = self.content_label.document()
        # 确保布局信息是最新的
        doc.adjustSize()
        doc_height = int(doc.size().height())
        target = doc_height + 4  # 底部留 4px 余量
        min_h = self._content_line_h + 4
        target = max(target, min_h)
        current_h = self.content_label.height()
        if abs(target - current_h) > 1:
            self.content_label.setFixedHeight(target)
    
    def append_content(self, text: str):
        """追加内容（流式场景高频调用，需要高效）
        
        ★ 增量渲染策略（借鉴 markstream-vue）：
        1. 文本追加到 _pending_text
        2. 检查是否有已完成的段落（双换行分隔 / 代码块闭合）
        3. 已完成段落冻结为 RichText Widget，不再变动
        4. 不完整的尾部保留在 QPlainTextEdit 中继续接收 delta
        """
        # ★ 修复：不丢弃包含换行符的 chunk
        # 纯换行符（\n\n）是 Markdown 段落分隔的关键信号，
        # 丢弃它们会导致多段内容粘连在一起
        if not text.strip() and '\n' not in text:
            return
        # 清除 U+FFFD 替换符（encoding 异常残留）
        if '\ufffd' in text:
            text = text.replace('\ufffd', '')
        self._content += text
        self._pending_text += text

        # 尝试冻结已完成的段落
        if self._incremental_enabled:
            self._try_freeze_completed()

        # 更新活跃区域显示（只显示未冻结的文本）
        self.content_label.setPlainText(self._pending_text)
        # setPlainText 会重置 block format，需要重新应用行间距
        self._apply_line_spacing(160)
        # 光标移到末尾
        cursor = self.content_label.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.content_label.setTextCursor(cursor)

    def _try_freeze_completed(self):
        """检测并冻结已完成的段落
        
        检测规则：
        - 代码块: ``` 开启 → ``` 关闭，闭合后整个代码块冻结
        - 文本段落: 两个连续换行 (\n\n) 分隔的文本段落冻结
        """
        text = self._pending_text
        if not text:
            return

        # 按行扫描，寻找可冻结的边界
        lines = text.split('\n')
        freeze_up_to = -1  # 冻结到第几行（不含）
        i = 0
        in_fence = self._in_code_fence

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if in_fence:
                # 在代码块内，检查关闭围栏
                if stripped.startswith('```'):
                    in_fence = False
                    # 代码块结束 → 可冻结到此行（含）
                    freeze_up_to = i + 1
                i += 1
                continue

            # 检查代码块开启
            if stripped.startswith('```'):
                # 如果之前有未冻结的文本段落，先冻结它们
                if i > 0 and freeze_up_to < i:
                    # 检查代码块之前是否有空行分隔
                    pass
                in_fence = True
                self._code_fence_lang = stripped[3:].strip()
                i += 1
                continue

            # 检查双换行分隔（空行）
            if not stripped:
                # 空行 → 如果之前有内容，可以冻结到上一个非空行
                if i > 0 and freeze_up_to < i:
                    # 找到一个段落边界
                    # 但只有在空行之前有实质内容时才冻结
                    has_content_before = any(lines[j].strip() for j in range(max(0, freeze_up_to + 1 if freeze_up_to >= 0 else 0), i))
                    if has_content_before:
                        freeze_up_to = i  # 冻结到空行（含空行）
            i += 1

        self._in_code_fence = in_fence

        # 执行冻结
        if freeze_up_to > 0 and not in_fence:
            frozen_text = '\n'.join(lines[:freeze_up_to])
            remaining_text = '\n'.join(lines[freeze_up_to:])

            if frozen_text.strip():
                self._freeze_text(frozen_text)

            self._pending_text = remaining_text

    def _freeze_text(self, text: str):
        """将一段文本冻结为富文本 Widget"""
        # 使用 SimpleMarkdown 解析
        segments = SimpleMarkdown.parse_segments(text)

        for seg in segments:
            if seg[0] == 'text':
                lbl = QtWidgets.QLabel()
                lbl.setWordWrap(True)
                lbl.setTextFormat(QtCore.Qt.RichText)
                lbl.setOpenExternalLinks(False)
                lbl.setTextInteractionFlags(
                    QtCore.Qt.TextSelectableByMouse
                    | QtCore.Qt.TextSelectableByKeyboard
                    | QtCore.Qt.LinksAccessibleByMouse
                )
                lbl.setText(_linkify_node_paths(seg[1], self._session_node_map))
                lbl.setObjectName("richText")
                lbl.linkActivated.connect(self._on_link_activated)
                self._frozen_layout.addWidget(lbl)
            elif seg[0] == 'code':
                cb = CodeBlockWidget(seg[2], seg[1], self)
                cb.createWrangleRequested.connect(self.createWrangleRequested.emit)
                # 代码块与前后段落之间需要额外间距
                cb.setContentsMargins(0, 6, 0, 6)
                self._frozen_layout.addWidget(cb)
            elif seg[0] == 'image':
                img_lbl = QtWidgets.QLabel()
                img_lbl.setObjectName("richImage")
                img_lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                img_lbl.setText(
                    f'<div style="margin:4px 0;">'
                    f'<img src="{html.escape(seg[1])}" '
                    f'style="max-width:100%;max-height:300px;border-radius:6px;">'
                    f'</div>'
                )
                img_lbl.setTextFormat(QtCore.Qt.RichText)
                self._frozen_layout.addWidget(img_lbl)

        # 显示冻结容器
        if not self._frozen_container.isVisible():
            self._frozen_container.setVisible(True)
        self._frozen_segments.append(text)

    def _clear_rendered_content(self):
        """清空已经冻结的正文 widget，用于 finalize 后完整重渲染。"""
        while self._frozen_layout.count():
            item = self._frozen_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self._frozen_segments.clear()
        self._frozen_container.setVisible(False)
    
    def set_content(self, text: str):
        """设置内容（一次性，非流式场景，如历史恢复）
        
        ★ 直接渲染为富文本，避免历史恢复时也出现跳变。
        """
        self._content = text
        self._pending_text = ""
        self._incremental_enabled = False
        
        content = self._clean_content(text)
        if not content:
            self.content_label.setPlainText("")
            return
        
        # 直接渲染为富文本 Widget，保持一致的外观
        self.content_label.setVisible(False)
        self._freeze_text(content)
    
    @staticmethod
    def _clean_content(text: str) -> str:
        """清理内容中的多余空白（仅在 finalize 时调用一次）"""
        if not text:
            return ""
        import re
        cleaned = re.sub(r'\n{3,}', '\n\n', text)
        return cleaned.strip()
    
    def add_collapsible(self, title: str, content: str) -> CollapsibleSection:
        """添加可折叠内容"""
        section = CollapsibleSection(title, collapsed=True, parent=self)
        section.add_text(content, "muted")
        self.details_layout.addWidget(section)
        return section
    
    def _copy_content(self):
        """复制完整正式回复内容到剪贴板"""
        content = self._clean_content(self._content)
        if content:
            QtWidgets.QApplication.clipboard().setText(content)
            # 临时反馈
            self._copy_btn.setText(tr('btn.copied'))
            self._copy_btn.setProperty("state", "copied")
            self._copy_btn.style().unpolish(self._copy_btn)
            self._copy_btn.style().polish(self._copy_btn)
            QtCore.QTimer.singleShot(1500, self._reset_copy_btn)
    
    def _reset_copy_btn(self):
        """恢复复制按钮样式"""
        try:
            self._copy_btn.setText(tr('btn.copy'))
            self._copy_btn.setProperty("state", "")
            self._copy_btn.style().unpolish(self._copy_btn)
            self._copy_btn.style().polish(self._copy_btn)
        except RuntimeError:
            pass  # widget 已销毁
    
    def start_aurora(self):
        """启动左侧流光边框动画"""
        self.aurora_bar.start()

    def stop_aurora(self):
        """停止左侧流光边框动画"""
        self.aurora_bar.stop()

    def finalize(self):
        """完成回复 - 提取最终总结
        
        ★ 增量渲染模式下，大部分段落已经冻结为 Widget，
        finalize 只需处理最后的 _pending_text 尾部残留。
        """
        # ★ 停止流光边框
        self.aurora_bar.stop()
        
        elapsed = time.time() - self._start_time
        
        # 完成思考区块
        if self._has_thinking:
            self.thinking_section.finalize()
        
        # 完成执行区块
        if self._has_execution:
            self.execution_section.finalize()
        
        # 更新状态
        parts = []
        if self._has_thinking:
            parts.append(tr('status.thinking'))
        if self._has_execution:
            tool_count = len(self.execution_section._tool_calls)
            parts.append(tr('status.calls', tool_count))
        
        status_text = tr('status.done', _fmt_duration(elapsed))
        if parts:
            status_text += f" | {', '.join(parts)}"
        
        self.status_label.setText(status_text)
        
        # 有内容时显示复制按钮
        if self._clean_content(self._content):
            self._copy_btn.setVisible(True)

        # ★ 有工具调用时显示反馈按钮（纯问答无 episodic 记忆可反馈）
        if self._has_execution:
            self._thumb_up_btn.setVisible(True)
            self._thumb_down_btn.setVisible(True)

        # ★ finalize 后用完整正文重渲染一次，避免流式半截 Markdown 影响最终 UI
        content = self._clean_content(self._content)
        
        if not content:
            if self._has_execution:
                self.content_label.setPlainText(tr('status.exec_done_see_above'))
            else:
                self.content_label.setPlainText(tr('status.no_reply'))
            self.content_label.setProperty("state", "empty")
            self.content_label.style().unpolish(self.content_label)
            self.content_label.style().polish(self.content_label)
        else:
            self._clear_rendered_content()
            self._pending_text = ""
            self.content_label.setVisible(False)
            self._freeze_text(content)
    
    def _on_link_activated(self, url: str):
        """处理链接点击 — houdini:// 协议 → nodePathClicked 信号"""
        if url.startswith('houdini://'):
            node_path = url[len('houdini://'):]
            self.nodePathClicked.emit(node_path)

    def _on_feedback(self, positive: bool):
        """用户点击 👍/👎：toggle 逻辑 + 更新按钮视觉 + 发出信号"""
        # 再次点击同一按钮 = 取消反馈
        if self._feedback_state is positive:
            self._feedback_state = None
        else:
            self._feedback_state = positive
        # 更新按钮选中态
        self._thumb_up_btn.setProperty("active", self._feedback_state is True)
        self._thumb_down_btn.setProperty("active", self._feedback_state is False)
        for btn in (self._thumb_up_btn, self._thumb_down_btn):
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if self._feedback_state is not None:
            self.feedbackGiven.emit(self._feedback_state)


# ============================================================
# 简洁状态行
# ============================================================

class StatusLine(QtWidgets.QLabel):
    """简洁状态行"""
    
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("statusLine")
        self.setWordWrap(True)


# ============================================================
# 节点操作标签
# ============================================================

class NodeOperationLabel(QtWidgets.QWidget):
    """节点操作标签 - 显示 +1 node / -2 nodes，带 undo/keep 按钮"""
    
    nodeClicked = QtCore.Signal(str)      # 发送节点路径（点击节点名跳转）
    undoRequested = QtCore.Signal()       # 请求撤销此操作
    decided = QtCore.Signal()             # undo 或 keep 完成后通知（用于更新批量操作栏）
    
    # _BTN_STYLE removed — use objectName-based QSS instead
    
    def __init__(self, operation: str, count: int, node_paths: list = None, 
                 detail_text: str = None, param_diff: dict = None, parent=None):
        """
        Args:
            operation: 'create' | 'delete' | 'modify'
            count: 操作的节点/参数数量
            node_paths: 节点路径列表
            detail_text: 简单文本详情 (旧方式, 纯文字)
            param_diff: 参数 diff 信息 {"param_name": str, "old_value": Any, "new_value": Any}
        """
        super().__init__(parent)
        self._node_paths = node_paths or []
        self._decided = False  # 用户是否已做出选择
        
        # 如果有 param_diff，使用垂直布局（标题行 + diff 区域）
        # 否则使用原来的水平布局
        if param_diff and operation == 'modify':
            self._init_modify_layout(operation, count, param_diff)
            return
        
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)
        
        if operation == 'create':
            prefix = "+"
            color = CursorTheme.ACCENT_GREEN
        elif operation == 'modify':
            prefix = "~"
            color = CursorTheme.ACCENT_YELLOW
        else:
            prefix = "-"
            color = CursorTheme.ACCENT_RED
        
        if operation == 'modify':
            plural = "params" if count > 1 else "param"
        else:
            plural = "nodes" if count > 1 else "node"
        count_text = f"{prefix}{count} {plural}"
        
        count_label = QtWidgets.QLabel(count_text)
        count_label.setObjectName("nodeOpCount")
        count_label.setProperty("op", operation)
        count_label.style().unpolish(count_label)
        count_label.style().polish(count_label)
        layout.addWidget(count_label)
        
        # 每个节点名作为可点击按钮
        display_paths = self._node_paths[:5]
        for path in display_paths:
            short_name = path.rsplit('/', 1)[-1] if '/' in path else path
            btn = QtWidgets.QPushButton(short_name)
            btn.setFlat(True)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setToolTip(tr('node.click_jump', path))
            btn.setObjectName("nodePathBtn")
            btn.clicked.connect(lambda checked=False, p=path: self.nodeClicked.emit(p))
            layout.addWidget(btn)
        
        if len(self._node_paths) > 5:
            more = QtWidgets.QLabel(f"+{len(self._node_paths) - 5} more")
            more.setObjectName("nodeOpMore")
            layout.addWidget(more)
        
        # 简单文本详情（仅在没有 param_diff 时使用）
        if detail_text:
            detail_label = QtWidgets.QLabel(detail_text)
            detail_label.setObjectName("nodeOpDetail")
            detail_label.setToolTip(detail_text)
            layout.addWidget(detail_label)
        
        layout.addStretch()
        
        # ── Undo / Keep 按钮 ──
        self._undo_btn = QtWidgets.QPushButton(tr('btn.undo'))
        self._undo_btn.setFixedHeight(20)
        self._undo_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._undo_btn.setObjectName("btnUndoOp")
        self._undo_btn.clicked.connect(self._on_undo)
        layout.addWidget(self._undo_btn)
        
        self._keep_btn = QtWidgets.QPushButton(tr('btn.keep'))
        self._keep_btn.setFixedHeight(20)
        self._keep_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._keep_btn.setObjectName("btnKeepOp")
        self._keep_btn.clicked.connect(self._on_keep)
        layout.addWidget(self._keep_btn)
        
        # 决定后的状态标签（替代按钮）
        self._status_label = QtWidgets.QLabel()
        self._status_label.setObjectName("nodeOpStatus")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)
    
    def _init_modify_layout(self, operation: str, count: int, param_diff: dict):
        """modify 操作的专用布局：标题行(黄标签+节点名+undo/keep) + diff 展示区"""
        self._decided = False
        
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 2)
        root.setSpacing(2)
        
        # ── 第一行：标签 + 节点名 + undo/keep ──
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(4)
        
        color = CursorTheme.ACCENT_YELLOW
        plural = "params" if count > 1 else "param"
        count_label = QtWidgets.QLabel(f"~{count} {plural}")
        count_label.setObjectName("nodeOpCount")
        count_label.setProperty("op", "modify")
        count_label.style().unpolish(count_label)
        count_label.style().polish(count_label)
        header.addWidget(count_label)
        
        for path in self._node_paths[:3]:
            short_name = path.rsplit('/', 1)[-1] if '/' in path else path
            btn = QtWidgets.QPushButton(short_name)
            btn.setFlat(True)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setToolTip(tr('node.click_jump', path))
            btn.setObjectName("nodePathBtn")
            btn.clicked.connect(lambda checked=False, p=path: self.nodeClicked.emit(p))
            header.addWidget(btn)
        
        header.addStretch()
        
        self._undo_btn = QtWidgets.QPushButton(tr('btn.undo'))
        self._undo_btn.setFixedHeight(20)
        self._undo_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._undo_btn.setObjectName("btnUndoOp")
        self._undo_btn.clicked.connect(self._on_undo)
        header.addWidget(self._undo_btn)
        
        self._keep_btn = QtWidgets.QPushButton(tr('btn.keep'))
        self._keep_btn.setFixedHeight(20)
        self._keep_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._keep_btn.setObjectName("btnKeepOp")
        self._keep_btn.clicked.connect(self._on_keep)
        header.addWidget(self._keep_btn)
        
        self._status_label = QtWidgets.QLabel()
        self._status_label.setObjectName("nodeOpStatus")
        self._status_label.setVisible(False)
        header.addWidget(self._status_label)
        
        root.addLayout(header)
        
        # ── 第二行：Diff 展示 ──
        self._diff_widget = ParamDiffWidget(
            param_name=param_diff.get("param_name", ""),
            old_value=param_diff.get("old_value", ""),
            new_value=param_diff.get("new_value", ""),
        )
        root.addWidget(self._diff_widget)
    
    def collapse_diff(self):
        """折叠 diff 展示区（Keep All 时调用）"""
        if hasattr(self, '_diff_widget') and self._diff_widget:
            self._diff_widget.collapse()
    
    def _on_undo(self):
        if self._decided:
            return
        self._decided = True
        self._undo_btn.setVisible(False)
        self._keep_btn.setVisible(False)
        self._status_label.setText(tr('status.undone'))
        self._status_label.setProperty("state", "undone")
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)
        self._status_label.setVisible(True)
        self.undoRequested.emit()
        self.decided.emit()
    
    def _on_keep(self):
        if self._decided:
            return
        self._decided = True
        self._undo_btn.setVisible(False)
        self._keep_btn.setVisible(False)
        self._status_label.setText(tr('status.kept'))
        self._status_label.setVisible(True)
        self.decided.emit()


# ============================================================
# 流式代码预览组件（Streaming VEX Apply）
# ============================================================

class StreamingCodePreview(QtWidgets.QWidget):
    """流式代码预览 — 像 Cursor Apply 一样逐行显示 AI 正在写的代码
    
    在 tool_call 参数流式到达时，实时显示 VEX 代码的书写过程。
    工具执行完毕后，由 ai_tab 将其替换为正式的 ParamDiffWidget。
    """

    def __init__(self, tool_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("streamingCodePreview")
        self._tool_name = tool_name

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(0)

        # 标题行
        self._title = QtWidgets.QLabel("✍ Writing code...")
        self._title.setObjectName("streamingCodeTitle")
        layout.addWidget(self._title)

        # 代码显示区（只读，固定最大高度，自动滚动）
        self._code_area = QtWidgets.QPlainTextEdit()
        self._code_area.setReadOnly(True)
        self._code_area.setObjectName("streamingCodeArea")
        self._code_area.setMaximumHeight(200)
        self._code_area.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        layout.addWidget(self._code_area)

        # 记录上次已显示的代码长度，只追加增量
        self._last_len = 0

    def update_code(self, full_code: str):
        """用完整代码字符串更新显示（增量追加新部分）"""
        if len(full_code) > self._last_len:
            delta = full_code[self._last_len:]
            self._last_len = len(full_code)
            self._code_area.moveCursor(QtGui.QTextCursor.End)
            self._code_area.insertPlainText(delta)
            # 自动滚动到底部
            sb = self._code_area.verticalScrollBar()
            sb.setValue(sb.maximum())

    def finalize(self):
        """流式结束，更新标题"""
        self._title.setText("✓ Code complete")
        self._title.setProperty("state", "done")
        self._title.style().unpolish(self._title)
        self._title.style().polish(self._title)


# ============================================================
# 参数 Diff 展示组件
# ============================================================

class ParamDiffWidget(QtWidgets.QWidget):
    """参数变更 Diff 展示 — 旧值红框 / 新值绿框
    
    - 标量/短文本: 内联显示  [old_value] → [new_value]
    - 多行文本(VEX等): 展开式 diff, 红色背景删除行, 绿色背景新增行
    """
    
    # diff 颜色
    _RED_BG = "#3d1f1f"       # 删除行背景
    _RED_BORDER = "#6e3030"   # 删除行边框
    _RED_TEXT = "#f48771"     # 删除行文字
    _GREEN_BG = "#1f3d1f"     # 新增行背景
    _GREEN_BORDER = "#2e6e30" # 新增行边框
    _GREEN_TEXT = "#89d185"   # 新增行文字
    _GREY_TEXT = "#64748b"    # 上下文行文字
    
    # 行级通用样式（紧凑无间隙，像一个完整代码块）
    _LINE_BASE = (
        "font-size: 11px; font-family: {font}; "
        "margin: 0px; padding: 0px 6px; "
        "border: none; border-radius: 0px; "
        "min-height: 16px; max-height: 16px;"
    )

    def __init__(self, param_name: str, old_value, new_value, parent=None):
        super().__init__(parent)
        self._collapsed = True  # ★ 默认折叠（露出预览窗口）
        
        old_str = self._to_str(old_value)
        new_str = self._to_str(new_value)
        is_multiline = ('\n' in old_str or '\n' in new_str
                        or len(old_str) > 60 or len(new_str) > 60)
        
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 2, 0, 2)
        root_layout.setSpacing(0)
        
        if is_multiline:
            # ── 多行 diff (VEX 等) ──
            # 标题行: param_name ▶ （默认折叠，露出预览窗口）
            self._title_text = param_name
            self._toggle_btn = QtWidgets.QPushButton(f"▶ {param_name}")
            self._toggle_btn.setFlat(True)
            self._toggle_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self._toggle_btn.setObjectName("diffToggle")
            self._toggle_btn.clicked.connect(self._toggle)
            root_layout.addWidget(self._toggle_btn)
            
            # diff 内容区（用 QScrollArea 包裹，折叠时露出预览窗口）
            self._diff_frame = QtWidgets.QFrame()
            self._diff_frame.setObjectName("diffFrame")
            diff_layout = QtWidgets.QVBoxLayout(self._diff_frame)
            diff_layout.setContentsMargins(0, 2, 0, 2)
            diff_layout.setSpacing(0)
            
            _font = CursorTheme.FONT_CODE
            
            # 使用 difflib 计算行级 diff
            import difflib
            old_lines = old_str.splitlines(keepends=True)
            new_lines = new_str.splitlines(keepends=True)
            diff = list(difflib.unified_diff(old_lines, new_lines, n=2))
            
            # 跳过 --- / +++ 头两行, 取实际 diff 行
            diff_body = diff[2:] if len(diff) > 2 else []
            
            if not diff_body:
                # 没有实际差异（或 difflib 无法处理）→ 并排显示
                self._add_block(diff_layout, tr('diff.old'), old_str, is_old=True)
                self._add_block(diff_layout, tr('diff.new'), new_str, is_old=False)
            else:
                for line in diff_body:
                    line_stripped = line.rstrip('\n')
                    lbl = QtWidgets.QLabel(line_stripped)
                    lbl.setObjectName("diffLine")
                    if line.startswith('@@'):
                        lbl.setProperty("diffType", "hunk")
                    elif line.startswith('-'):
                        lbl.setProperty("diffType", "del")
                    elif line.startswith('+'):
                        lbl.setProperty("diffType", "add")
                    else:
                        lbl.setProperty("diffType", "ctx")
                    diff_layout.addWidget(lbl)
            
            # ★ 用 QScrollArea 包裹 diff_frame，折叠时限制高度而不是完全隐藏
            self._scroll_area = QtWidgets.QScrollArea()
            self._scroll_area.setObjectName("diffScrollArea")
            self._scroll_area.setWidgetResizable(True)
            self._scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
            self._scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self._scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self._scroll_area.setWidget(self._diff_frame)
            
            # 预览高度常量
            self._PREVIEW_HEIGHT = 120   # 折叠时露出的高度(px)
            
            root_layout.addWidget(self._scroll_area)
            self._scroll_area.setMaximumHeight(self._PREVIEW_HEIGHT)  # 默认折叠，露出预览窗口
        else:
            # ── 内联 diff (标量) ──
            inline = QtWidgets.QHBoxLayout()
            inline.setContentsMargins(0, 0, 0, 0)
            inline.setSpacing(4)
            
            # 参数名
            name_lbl = QtWidgets.QLabel(f"{param_name}:")
            name_lbl.setObjectName("diffParamName")
            inline.addWidget(name_lbl)
            
            # 旧值 (红框)
            old_lbl = QtWidgets.QLabel(self._truncate(old_str, 30))
            old_lbl.setToolTip(f"{tr('diff.old')}: {old_str}")
            old_lbl.setObjectName("diffOldValue")
            inline.addWidget(old_lbl)
            
            # 箭头
            arrow = QtWidgets.QLabel("→")
            arrow.setObjectName("diffArrow")
            inline.addWidget(arrow)
            
            # 新值 (绿框)
            new_lbl = QtWidgets.QLabel(self._truncate(new_str, 30))
            new_lbl.setToolTip(f"{tr('diff.new')}: {new_str}")
            new_lbl.setObjectName("diffNewValue")
            inline.addWidget(new_lbl)
            
            root_layout.addLayout(inline)
    
    def _toggle(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            # 折叠 → 限制高度，露出预览窗口
            self._scroll_area.setMaximumHeight(self._PREVIEW_HEIGHT)
        else:
            # 展开 → 取消高度限制
            self._scroll_area.setMaximumHeight(16777215)
        arrow = "▶" if self._collapsed else "▼"
        self._toggle_btn.setText(f"{arrow} {self._title_text}")
    
    def collapse(self):
        """外部调用：强制折叠 diff（仅对多行 diff 有效）"""
        if hasattr(self, '_scroll_area') and not self._collapsed:
            self._collapsed = True
            self._scroll_area.setMaximumHeight(self._PREVIEW_HEIGHT)
            self._toggle_btn.setText(f"▶ {self._title_text}")
    
    def _add_block(self, parent_layout, title: str, text: str, is_old: bool):
        """添加旧值/新值整块（用于 difflib 无差异时的 fallback）"""
        diff_type = "del" if is_old else "add"
        header = QtWidgets.QLabel(title)
        header.setObjectName("diffLine")
        header.setProperty("diffType", "hunk")
        parent_layout.addWidget(header)
        for line in text.splitlines():
            lbl = QtWidgets.QLabel(line)
            lbl.setObjectName("diffLine")
            lbl.setProperty("diffType", diff_type)
            parent_layout.addWidget(lbl)
    
    @staticmethod
    def _to_str(value) -> str:
        if isinstance(value, dict) and "expr" in value:
            return str(value["expr"])
        if isinstance(value, (list, tuple)):
            return ', '.join(str(v) for v in value)
        return str(value)
    
    @staticmethod
    def _truncate(s: str, max_len: int) -> str:
        return s if len(s) <= max_len else s[:max_len - 1] + "…"


# ============================================================
# 可折叠内容块（兼容旧代码）
# ============================================================

class CollapsibleContent(QtWidgets.QWidget):
    """可折叠内容 - 点击标题展开/收起"""
    
    def __init__(self, title: str, content: str = "", parent=None):
        super().__init__(parent)
        self._collapsed = True
        self._title = title
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(0)
        
        self.title_btn = QtWidgets.QPushButton(f"▶ {title}")
        self.title_btn.setFlat(True)
        self.title_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.title_btn.clicked.connect(self.toggle)
        self.title_btn.setObjectName("collapseContentTitle")
        layout.addWidget(self.title_btn)
        
        self.content_label = QtWidgets.QLabel(content)
        self.content_label.setWordWrap(True)
        self.content_label.setObjectName("collapseContentLabel")
        self.content_label.setVisible(False)
        layout.addWidget(self.content_label)
    
    def toggle(self):
        self._collapsed = not self._collapsed
        self.content_label.setVisible(not self._collapsed)
        arrow = "▶" if self._collapsed else "▼"
        self.title_btn.setText(f"{arrow} {self._title}")
    
    def set_content(self, content: str):
        self.content_label.setText(content)
    
    def expand(self):
        if self._collapsed:
            self.toggle()
