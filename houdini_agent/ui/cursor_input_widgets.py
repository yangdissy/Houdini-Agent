# -*- coding: utf-8 -*-
"""Input, completion, and status widgets."""

import html
import re

from houdini_agent.qt_compat import QtWidgets, QtCore, QtGui, safe_single_shot

from .cursor_chat_widgets import ThinkingBar
from .cursor_theme import CursorTheme
from .i18n import tr


# ============================================================
# 节点上下文栏 (Houdini 专属)
# ============================================================

class NodeContextBar(QtWidgets.QFrame):
    """显示当前 Houdini 网络路径 / 选中节点"""

    refreshRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setObjectName("NodeContextBar")

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 6, 0)
        lay.setSpacing(6)

        self.path_label = QtWidgets.QLabel("/obj")
        self.path_label.setObjectName("ctxPathLabel")
        lay.addWidget(self.path_label)

        self.sel_label = QtWidgets.QLabel("")
        self.sel_label.setObjectName("ctxSelLabel")
        self.sel_label.setVisible(False)
        lay.addWidget(self.sel_label)

        lay.addStretch()

        ref_btn = QtWidgets.QPushButton("R")
        ref_btn.setFixedSize(22, 22)
        ref_btn.setFlat(True)
        ref_btn.setCursor(QtCore.Qt.PointingHandCursor)
        ref_btn.setObjectName("ctxRefreshBtn")
        ref_btn.clicked.connect(self.refreshRequested.emit)
        lay.addWidget(ref_btn)

    def update_context(self, path: str = "", selected: list = None):
        self.path_label.setText(path if path else "/obj")
        if selected:
            names = [n.rsplit('/', 1)[-1] for n in selected[:3]]
            text = ', '.join(names)
            if len(selected) > 3:
                text += f" +{len(selected) - 3}"
            self.sel_label.setText(text)
            self.sel_label.setVisible(True)
        else:
            self.sel_label.setText("")
            self.sel_label.setVisible(False)


# ============================================================
# 工具执行状态栏
# ============================================================

class ToolStatusBar(QtWidgets.QFrame):
    """底部工具状态栏 — 显示当前正在执行的工具名 + 脉冲指示器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setObjectName("toolStatusBar")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(4)

        self._pulse = PulseIndicator(CursorTheme.ACCENT_BEIGE, 5, self)
        lay.addWidget(self._pulse)

        self._label = QtWidgets.QLabel("")
        self._label.setObjectName("toolStatusLabel")
        lay.addWidget(self._label)
        lay.addStretch()

        self.setVisible(False)

    def show_tool(self, tool_name: str):
        """显示正在执行的工具"""
        self._label.setText(f"⚡ {tool_name}")
        self._pulse.start()
        self.setVisible(True)

    def hide_tool(self):
        """隐藏工具状态"""
        self._pulse.stop()
        self.setVisible(False)
        self._label.setText("")


# ============================================================
# 统一状态指示栏（合并 ThinkingBar + ToolStatusBar）
# ============================================================

class UnifiedStatusBar(QtWidgets.QWidget):
    """统一状态指示栏 — 合并思考状态、生成状态和工具执行状态为一条指示条。

    提供四个接口：
        start()                 显示思考中 + 流光动画
        show_generating()       显示生成中 + 流光动画（API 迭代等待）
        show_tool(tool_name)    显示工具执行中 + 脉冲动画
        stop()                  隐藏状态栏
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setObjectName("unifiedStatusBar")
        self.setVisible(False)

        self._mode = None  # 'thinking' | 'generating' | 'tool' | None
        self._elapsed = 0.0
        self._phase = 0.0

        # 流光定时器 ~25fps
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    # ---- 公共 API ----

    def start(self):
        """启动思考模式（兼容旧 ThinkingBar.start）"""
        self._mode = 'thinking'
        self._elapsed = 0.0
        self._phase = 0.0
        self.setVisible(True)
        self._timer.start()
        self.update()

    def stop(self):
        """停止所有状态（兼容旧 ThinkingBar.stop）"""
        self._mode = None
        self._timer.stop()
        self.setVisible(False)

    def set_elapsed(self, seconds: float):
        """更新思考耗时（兼容旧 ThinkingBar.set_elapsed）"""
        self._elapsed = seconds
        self.update()

    def show_generating(self):
        """切换到生成模式 — API 请求等待中

        在工具执行完毕后、下一轮 LLM 响应开始前显示，
        填补"思考结束 → 下轮内容到达"之间的视觉空白期。
        """
        self._mode = 'generating'
        self._phase = 0.0
        self.setVisible(True)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def show_planning(self, progress: str = ""):
        """切换到规划模式 — 显示 Plan 生成进度

        Args:
            progress: 进度文本，如 "step 3" 或空字符串
        """
        self._mode = 'planning'
        self._planning_progress = progress
        self.setVisible(True)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def show_tool(self, tool_name: str):
        """切换到工具执行模式"""
        self._mode = 'tool'
        self._tool_name = tool_name
        self._phase = 0.0
        self.setVisible(True)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def hide_tool(self):
        """隐藏工具状态 → 自动切换到 generating 模式（等待下轮 API 响应）"""
        if self._mode == 'tool':
            # 不完全隐藏，切换到 generating 模式以填补视觉空白
            self.show_generating()

    # ---- 内部 ----

    def _tick(self):
        self._phase += 0.025
        if self._phase > 1.0:
            self._phase -= 1.0
        self.update()

    def paintEvent(self, event):
        if self._mode == 'thinking':
            self._paint_thinking(event)
        elif self._mode == 'generating':
            self._paint_generating(event)
        elif self._mode == 'planning':
            self._paint_planning(event)
        elif self._mode == 'tool':
            self._paint_tool(event)

    def _paint_thinking(self, event):
        """绘制思考状态 — 流光文字 + 忙态警示"""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # ★ 忙态警示：Agent 运行全程提醒用户不要操作 Houdini，避免与主线程
        #   hou 操作/cook 竞态崩溃（crash 分析 2026-07）
        status = f"Thinking {self._elapsed:.1f}s" if self._elapsed > 0 else "Thinking..."
        self._paint_busy_text(p, w, h, status, "⚠ 请勿操作 Houdini")
        p.end()

    def _paint_generating(self, event):
        """绘制生成状态 — 流光文字（与 thinking 相似但使用暖色调 + 不同文本）"""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # ★ 忙态警示：Generating 是 Agent 运行期最常驻状态，在此提醒用户不要
        #   操作 Houdini，避免与主线程 hou 操作/cook 竞态崩溃（crash 分析 2026-07）
        self._paint_busy_text(p, w, h, "Generating...", "⚠ 请勿操作 Houdini")
        p.end()

    def _paint_busy_text(self, p, w, h, status, warning, status_base=(150, 160, 175), status_glow=(225, 235, 250)):
        """统一绘制"状态 + 忙态警示"：状态用柔和流光，警示用醒目橙红加粗。"""
        gap = "   "
        font = QtGui.QFont(CursorTheme.FONT_BODY, 12)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        sw = fm.horizontalAdvance(status + gap)
        ww = fm.horizontalAdvance(warning)
        tw = sw + ww
        x = (w - tw) // 2
        y = (h + fm.ascent() - fm.descent()) // 2
        # 状态段：柔和底色 + 流光扫过
        sx = x
        br, bg, bb = status_base
        gr, gg, gb = status_glow
        p.setPen(QtGui.QColor(br, bg, bb, 150))
        p.drawText(sx, y, status + gap)
        grad = QtGui.QLinearGradient(sx, 0, sx + sw, 0)
        pos = self._phase
        before = max(0.0, pos - 0.15)
        after = min(1.0, pos + 0.15)
        grad.setColorAt(0.0, QtGui.QColor(gr, gg, gb, 0))
        if before > 0:
            grad.setColorAt(before, QtGui.QColor(gr, gg, gb, 0))
        grad.setColorAt(pos, QtGui.QColor(gr, gg, gb, 210))
        if after < 1.0:
            grad.setColorAt(after, QtGui.QColor(gr, gg, gb, 0))
        grad.setColorAt(1.0, QtGui.QColor(gr, gg, gb, 0))
        p.setPen(QtGui.QPen(QtGui.QBrush(grad), 0))
        p.drawText(sx, y, status + gap)
        # 警示段：醒目橙红，恒亮
        p.setPen(QtGui.QColor(255, 140, 90, 255))
        p.drawText(x + sw, y, warning)

    def _paint_planning(self, event):
        """绘制规划状态 — 紫色调流光 + 进度文本"""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        progress = getattr(self, '_planning_progress', '')
        text = f"Planning... {progress}" if progress else "Planning..."
        font = QtGui.QFont(CursorTheme.FONT_BODY, 10)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        x = (w - tw) // 2
        y = (h + fm.ascent() - fm.descent()) // 2
        # 底色文字（紫灰色）
        p.setPen(QtGui.QColor(139, 120, 160, 120))
        p.drawText(x, y, text)
        # 流光高亮（紫白色扫过）
        grad = QtGui.QLinearGradient(x, 0, x + tw, 0)
        pos = self._phase
        before = max(0.0, pos - 0.15)
        after = min(1.0, pos + 0.15)
        grad.setColorAt(0.0, QtGui.QColor(200, 180, 240, 0))
        if before > 0:
            grad.setColorAt(before, QtGui.QColor(200, 180, 240, 0))
        grad.setColorAt(pos, QtGui.QColor(220, 200, 250, 220))
        if after < 1.0:
            grad.setColorAt(after, QtGui.QColor(200, 180, 240, 0))
        grad.setColorAt(1.0, QtGui.QColor(200, 180, 240, 0))
        p.setPen(QtGui.QPen(QtGui.QBrush(grad), 0))
        p.drawText(x, y, text)
        p.end()

    def _paint_tool(self, event):
        """绘制工具执行状态 — 金色调状态 + 忙态警示（与 Thinking/Generating 统一）"""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tool_name = getattr(self, '_tool_name', '')
        # ★ 忙态警示：Agent 执行工具期间提醒用户不要操作 Houdini，
        #   避免与主线程 hou 操作/cook 竞态导致崩溃（见 crash 分析 2026-07）
        status = f"⚡ {tool_name}" if tool_name else "执行中"
        self._paint_busy_text(
            p, w, h, status, "⚠ 请勿操作 Houdini 视口/节点",
            status_base=(170, 145, 100), status_glow=(230, 210, 170),
        )
        p.end()


# ============================================================
# VEX 预览确认对话框
# ============================================================

class VEXPreviewDialog(QtWidgets.QDialog):
    """VEX 代码预览对话框 — 用户确认后才执行创建操作"""

    def __init__(self, tool_name: str, args: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"确认执行: {tool_name}")
        self.setMinimumSize(560, 400)
        self.setObjectName("vexPreviewDlg")

        self._accepted = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 工具名称
        title = QtWidgets.QLabel(f"工具: {tool_name}")
        title.setObjectName("vexDlgTitle")
        layout.addWidget(title)

        # 参数摘要
        summary_parts = []
        if 'node_name' in args:
            summary_parts.append(f"节点名: {args['node_name']}")
        if 'wrangle_type' in args:
            summary_parts.append(f"类型: {args['wrangle_type']}")
        if 'run_over' in args:
            summary_parts.append(f"Run Over: {args['run_over']}")
        if 'parent_path' in args:
            summary_parts.append(f"父路径: {args['parent_path']}")
        if 'node_type' in args:
            summary_parts.append(f"节点类型: {args['node_type']}")
        if 'node_path' in args:
            summary_parts.append(f"节点路径: {args['node_path']}")
        if summary_parts:
            info = QtWidgets.QLabel("  |  ".join(summary_parts))
            info.setObjectName("vexDlgInfo")
            info.setWordWrap(True)
            layout.addWidget(info)

        # VEX 代码 / 主要参数
        vex_code = args.get('vex_code', '')
        param_value = args.get('value', '')
        code_text = vex_code or param_value or str(args)

        code_edit = QtWidgets.QPlainTextEdit()
        code_edit.setPlainText(code_text)
        code_edit.setReadOnly(True)
        code_edit.setObjectName("vexDlgCode")
        layout.addWidget(code_edit, 1)

        # 按钮行
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.setFixedHeight(30)
        btn_cancel.setObjectName("dlgBtnCancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_confirm = QtWidgets.QPushButton("✓ 确认执行")
        btn_confirm.setFixedHeight(30)
        btn_confirm.setObjectName("dlgBtnConfirm")
        btn_confirm.clicked.connect(self.accept)
        btn_row.addWidget(btn_confirm)

        layout.addLayout(btn_row)


# ============================================================
# 节点路径补全弹出框
# ============================================================

class NodeCompleterPopup(QtWidgets.QListWidget):
    """节点路径自动补全弹出窗 — 在输入 @ 时显示场景节点列表"""

    pathSelected = QtCore.Signal(str)  # 用户选中了一个节点路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)
        self.setFixedWidth(320)
        self.setMaximumHeight(200)
        self.setObjectName("nodeCompleter")
        self.itemActivated.connect(self._on_item_activated)
        self.setVisible(False)
        self._all_paths: list = []

    def set_node_paths(self, paths: list):
        """设置可选的节点路径列表"""
        self._all_paths = paths

    def show_filtered(self, prefix: str, anchor_widget: QtWidgets.QWidget, cursor_rect):
        """根据前缀过滤并显示"""
        self.clear()
        lower_prefix = prefix.lower()
        matches = [p for p in self._all_paths if lower_prefix in p.lower()][:30]
        if not matches:
            self.setVisible(False)
            return
        for p in matches:
            self.addItem(p)
        # 定位到光标下方
        global_pos = anchor_widget.mapToGlobal(cursor_rect.bottomLeft())
        self.move(global_pos.x(), global_pos.y() + 4)
        self.setVisible(True)
        self.setCurrentRow(0)

    def _on_item_activated(self, item):
        self.pathSelected.emit(item.text())
        self.setVisible(False)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            current = self.currentItem()
            if current:
                self.pathSelected.emit(current.text())
                self.setVisible(False)
                return
        elif event.key() == QtCore.Qt.Key_Escape:
            self.setVisible(False)
            return
        super().keyPressEvent(event)


# ============================================================
# 斜杠命令弹出框
# ============================================================

# ── 斜杠命令注册表 ──
# 每条: (command, icon, label_zh, label_en, description_zh, description_en, category)
SLASH_COMMANDS = [
    # ── 会话管理 ──
    ("clear",     "🗑",  "清空对话",     "Clear Chat",      "清空当前对话历史",           "Clear current conversation",   "session"),
    ("new",       "✨",  "新建会话",     "New Chat",         "创建一个新的对话",           "Create a new conversation",    "session"),
    # ── 记忆系统 ──
    ("memory",    "🧠",  "记忆状态",     "Memory Status",    "查看长期记忆统计和核心记忆", "View memory stats & core memories", "memory"),
    ("remember",  "📌",  "记住偏好",     "Remember",         "将内容写入核心记忆",         "Save content to core memory",  "memory"),
    ("forget",    "🧹",  "清除记忆",     "Forget",           "搜索并删除指定记忆",         "Search and delete a memory",   "memory"),
    ("search_mem","🔍",  "搜索记忆",     "Search Memory",    "在长期记忆中搜索",           "Search long-term memory",      "memory"),
    ("memories",  "📚",  "记忆库",       "Memory Library",   "打开记忆管理窗口",         "Open memory manager (full CRUD)", "memory"),
    # ── Houdini 场景 ──
    ("network",   "🌐",  "读取网络",     "Read Network",     "读取当前网络结构",           "Read current network structure","scene"),
    ("selection", "👆",  "读取选中",     "Read Selection",   "读取当前选中节点信息",       "Read selected node info",      "scene"),
    ("skills",    "⚡",  "技能列表",     "List Skills",      "列出所有可用 Skill",         "List all available skills",    "scene"),
    # ── 工具 ──
    ("status",    "📊",  "系统状态",     "System Status",    "查看记忆/成长/上下文统计",   "View memory/growth/context stats", "tool"),
    ("diagnostics", "🧪", "导出诊断",     "Diagnostics",      "导出策略/trace诊断 JSON",    "Export policy/trace diagnostics JSON", "tool"),
    ("export",    "💾",  "导出训练",     "Export Training",  "导出对话为训练数据",         "Export conversation as training data", "tool"),
    ("image",     "🖼",  "附加图片",     "Attach Image",     "从文件选择图片附加到消息",   "Select image to attach",       "tool"),
    ("help",      "❓",  "帮助",         "Help",             "显示所有可用斜杠命令",       "Show all available commands",   "tool"),
]

# 按分类分组的标题
_SLASH_CATEGORY_LABELS = {
    "session": ("── 会话 ──", "── Session ──"),
    "memory":  ("── 记忆 ──", "── Memory ──"),
    "scene":   ("── 场景 ──", "── Scene ──"),
    "tool":    ("── 工具 ──", "── Tools ──"),
}


class SlashCommandPopup(QtWidgets.QListWidget):
    """斜杠命令弹出窗 — 在输入 / 时显示可用命令"""

    commandSelected = QtCore.Signal(str)  # 用户选中了一个命令名

    def __init__(self, parent=None):
        super().__init__(parent)
        self._flags_applied = False
        self.setFixedWidth(300)
        self.setMaximumHeight(320)
        self.setObjectName("slashCompleter")
        self.itemActivated.connect(self._on_item_activated)
        self.setVisible(False)

    def show_filtered(self, prefix: str, anchor_widget: QtWidgets.QWidget,
                      cursor_rect, lang: str = 'zh'):
        """根据前缀过滤并显示命令列表"""
        if not self._flags_applied:
            self._flags_applied = True
            self.setWindowFlags(QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)

        self.clear()
        lower_prefix = prefix.lower()
        is_zh = (lang == 'zh')

        # 按分类分组
        last_cat = None
        match_count = 0
        for cmd, icon, lbl_zh, lbl_en, desc_zh, desc_en, cat in SLASH_COMMANDS:
            label = lbl_zh if is_zh else lbl_en
            desc = desc_zh if is_zh else desc_en
            # 匹配命令名、标签、描述
            if lower_prefix and not any(lower_prefix in s.lower() for s in (cmd, label, desc)):
                continue
            # 分类标题
            if cat != last_cat:
                last_cat = cat
                cat_label = _SLASH_CATEGORY_LABELS.get(cat, ("──", "──"))
                header_item = QtWidgets.QListWidgetItem(cat_label[0] if is_zh else cat_label[1])
                header_item.setFlags(QtCore.Qt.NoItemFlags)  # 不可选
                font = header_item.font()
                font.setPointSize(max(7, font.pointSize() - 1))
                header_item.setFont(font)
                header_item.setForeground(QtGui.QColor(120, 130, 160))
                self.addItem(header_item)
            # 命令项
            display_text = f"{icon}  /{cmd}    {desc}"
            item = QtWidgets.QListWidgetItem(display_text)
            item.setData(QtCore.Qt.UserRole, cmd)
            self.addItem(item)
            match_count += 1

        if match_count == 0:
            self.setVisible(False)
            return

        # 动态调整高度
        row_h = 24
        total_h = min(320, (self.count()) * row_h + 12)
        popup_h = max(80, total_h)
        self.setFixedHeight(popup_h)

        # 智能定位：优先朝上展开（输入框通常在底部），空间不足时才朝下
        anchor_top = anchor_widget.mapToGlobal(cursor_rect.topLeft())
        anchor_bottom = anchor_widget.mapToGlobal(cursor_rect.bottomLeft())
        screen = QtWidgets.QApplication.screenAt(anchor_bottom) or QtWidgets.QApplication.primaryScreen()
        screen_rect = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1920, 1080)

        space_above = anchor_top.y() - screen_rect.top() - 4
        space_below = screen_rect.bottom() - anchor_bottom.y() - 4

        if space_above >= popup_h:
            # 朝上展开（输入框在底部的常见情况）
            self.move(anchor_top.x(), anchor_top.y() - popup_h - 4)
        else:
            # 空间不足则朝下
            self.move(anchor_bottom.x(), anchor_bottom.y() + 4)

        self.setVisible(True)
        # 选中第一个非标题项
        for i in range(self.count()):
            if self.item(i).flags() & QtCore.Qt.ItemIsSelectable:
                self.setCurrentRow(i)
                break

    def _on_item_activated(self, item):
        cmd = item.data(QtCore.Qt.UserRole)
        if cmd:
            self.commandSelected.emit(cmd)
            self.setVisible(False)

    def select_next(self):
        """选中下一个可选项"""
        row = self.currentRow()
        for i in range(row + 1, self.count()):
            if self.item(i).flags() & QtCore.Qt.ItemIsSelectable:
                self.setCurrentRow(i)
                return

    def select_prev(self):
        """选中上一个可选项"""
        row = self.currentRow()
        for i in range(row - 1, -1, -1):
            if self.item(i).flags() & QtCore.Qt.ItemIsSelectable:
                self.setCurrentRow(i)
                return

    def confirm_current(self) -> bool:
        """确认当前选中项，返回是否成功"""
        current = self.currentItem()
        if current:
            cmd = current.data(QtCore.Qt.UserRole)
            if cmd:
                self.commandSelected.emit(cmd)
                self.setVisible(False)
                return True
        return False

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.confirm_current()
            return
        elif event.key() == QtCore.Qt.Key_Escape:
            self.setVisible(False)
            return
        super().keyPressEvent(event)


# ============================================================
# 输入区域
# ============================================================

class ChatInput(QtWidgets.QPlainTextEdit):
    """聊天输入框 — 自适应高度，支持自动换行、多行输入、图片粘贴/拖拽
    
    核心逻辑：统计文档中所有视觉行（含软换行），按行高计算目标高度，
    使输入框向上扩展而非隐藏已有行。
    支持 @节点路径 补全和从 Network Editor 拖拽节点。
    """
    
    sendRequested = QtCore.Signal()
    imageDropped = QtCore.Signal(QtGui.QImage)  # 粘贴或拖拽图片时触发
    atTriggered = QtCore.Signal(str, QtCore.QRect)  # @ 触发补全: (当前前缀, 光标矩形)
    slashTriggered = QtCore.Signal(str, QtCore.QRect)  # / 触发补全: (当前前缀, 光标矩形)
    
    _MIN_H = 92
    _MAX_H = 320
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(tr('placeholder'))
        # 确保自动换行
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
        # 隐藏滚动条（高度不够时才出现）
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # 启用拖拽
        self.setAcceptDrops(True)
        self.setObjectName("chatInput")
        self.setMinimumHeight(self._MIN_H)
        self.setMaximumHeight(self._MAX_H)
        
        # ★ PySide2 / PySide6 全平台 IME 支持（中文/日文/韩文）
        # ------------------------------------------------------------------
        # 问题背景：
        #   PySide2 嵌入 Houdini 时，macOS / Windows 上输入法可能不激活。
        #   macOS 的 NSTextInputClient 协议尤其依赖 inputMethodQuery 返回
        #   正确的光标矩形/周围文本/光标位置等信息，否则 IME 候选窗口
        #   无法定位甚至不会弹出。
        # ------------------------------------------------------------------
        # 1. 显式启用输入法
        self.setAttribute(QtCore.Qt.WA_InputMethodEnabled, True)
        # 2. 显式设置焦点策略，确保 Tab/Click 都能获取焦点
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        # 3. 设置输入法提示：自由文本
        try:
            self.setInputMethodHints(QtCore.Qt.ImhNone)
        except Exception:
            pass  # 极少数 PySide2 版本不支持此调用
        # 4. macOS 特有：确保焦点矩形可见（某些嵌入场景下默认关闭）
        try:
            self.setAttribute(QtCore.Qt.WA_MacShowFocusRect, True)
        except Exception:
            pass
        
        # 使用 textChanged，并延迟到下一事件循环执行（确保布局先完成）
        self.textChanged.connect(self._schedule_adjust)
        self.textChanged.connect(self._check_at_trigger)
        self.textChanged.connect(self._check_slash_trigger)
        # @ 补全状态
        self._at_active = False
        self._at_start_pos = -1
        self._completer_popup: 'NodeCompleterPopup | None' = None
        # / 斜杠命令补全状态
        self._slash_active = False
        self._slash_start_pos = -1
        self._slash_popup: 'SlashCommandPopup | None' = None
        # ★ IME 预编辑状态追踪
        self._ime_composing = False
        self.setFixedHeight(self._MIN_H)
    
    def set_completer_popup(self, popup: 'NodeCompleterPopup'):
        """设置节点补全弹出框引用，用于键盘导航和自动关闭"""
        self._completer_popup = popup

    def set_slash_popup(self, popup: 'SlashCommandPopup'):
        """设置斜杠命令弹出框引用"""
        self._slash_popup = popup
    
    def _schedule_adjust(self):
        """延迟调整高度，确保文档布局已更新"""
        safe_single_shot(0, self, '_adjust_height')
    
    def _adjust_height(self):
        """根据视觉行数（含软换行）自动调整高度——向上扩展"""
        doc = self.document()
        # 统计所有视觉行（包括 word-wrap 产生的软换行）
        visual_lines = 0
        block = doc.begin()
        while block.isValid():
            bl = block.layout()
            if bl and bl.lineCount() > 0:
                visual_lines += bl.lineCount()
            else:
                visual_lines += 1
            block = block.next()
        # 空文档至少算 1 行
        visual_lines = max(1, visual_lines)
        
        # 行高
        line_h = self.fontMetrics().lineSpacing()
        # 内容高度 = 行数 * 行高
        content_h = visual_lines * line_h
        # 加上 padding(8*2) + border(1*2) + 额外余量
        margins = self.contentsMargins()
        frame_w = self.frameWidth()
        padding = margins.top() + margins.bottom() + frame_w * 2 + 18
        total = content_h + padding
        
        h = max(self._MIN_H, min(self._MAX_H, total))
        if h != self.height():
            self.setFixedHeight(h)
            # 通知父布局重新分配空间
            self.updateGeometry()
    
    def _hide_completer(self):
        """隐藏补全弹出框"""
        if self._completer_popup and self._completer_popup.isVisible():
            self._completer_popup.setVisible(False)

    def _check_at_trigger(self):
        """检测输入中的 @ 字符，触发节点路径补全"""
        cursor = self.textCursor()
        pos = cursor.position()
        text = self.toPlainText()
        if not text or pos == 0:
            if self._at_active:
                self._at_active = False
                self._hide_completer()
            return

        # 查找光标前最近的 @
        left = text[:pos]
        at_idx = left.rfind('@')
        if at_idx == -1:
            if self._at_active:
                self._at_active = False
                self._hide_completer()
            return

        # @ 后面的内容不能包含空格（否则认为已结束）
        prefix_after_at = left[at_idx + 1:]
        if ' ' in prefix_after_at or '\n' in prefix_after_at:
            if self._at_active:
                self._at_active = False
                self._hide_completer()
            return

        self._at_active = True
        self._at_start_pos = at_idx
        # 发射信号，由外部(ai_tab)提供节点列表
        crect = self.cursorRect(cursor)
        self.atTriggered.emit(prefix_after_at, crect)

    def cancel_at_completion(self):
        """取消当前 @ 补全并隐藏弹出框"""
        self._at_active = False
        self._at_start_pos = -1
        self._hide_completer()

    def insert_at_completion(self, path: str):
        """将补全结果插入文本，替换 @前缀"""
        if self._at_start_pos < 0:
            return
        cursor = self.textCursor()
        pos = cursor.position()
        # 选中从 @ 到当前位置的文本并替换
        cursor.setPosition(self._at_start_pos)
        cursor.setPosition(pos, QtGui.QTextCursor.KeepAnchor)
        cursor.insertText(path + " ")
        self.setTextCursor(cursor)
        self._at_active = False
        self._at_start_pos = -1

    def _is_completer_visible(self) -> bool:
        """补全弹出框是否可见"""
        return (self._completer_popup is not None
                and self._completer_popup.isVisible()
                and self._completer_popup.count() > 0)

    # ---- 斜杠命令补全 ----

    def _check_slash_trigger(self):
        """检测输入中的 / 字符，触发斜杠命令补全（仅在行首或纯 / 开头时触发）"""
        cursor = self.textCursor()
        pos = cursor.position()
        text = self.toPlainText()

        if not text or pos == 0:
            if self._slash_active:
                self._slash_active = False
                self._hide_slash()
            return

        # 仅当 / 在文本最开头时触发（整个输入为 /xxx）
        if not text.startswith('/'):
            if self._slash_active:
                self._slash_active = False
                self._hide_slash()
            return

        # 提取 / 之后到光标位置的内容
        prefix_after_slash = text[1:pos]
        # 如果包含空格或换行，说明已超出命令名范围
        if ' ' in prefix_after_slash or '\n' in prefix_after_slash:
            if self._slash_active:
                self._slash_active = False
                self._hide_slash()
            return

        self._slash_active = True
        self._slash_start_pos = 0
        crect = self.cursorRect(cursor)
        self.slashTriggered.emit(prefix_after_slash, crect)

    def _hide_slash(self):
        """隐藏斜杠命令弹出框"""
        if self._slash_popup and self._slash_popup.isVisible():
            self._slash_popup.setVisible(False)

    def cancel_slash_completion(self):
        """取消当前斜杠命令补全"""
        self._slash_active = False
        self._slash_start_pos = -1
        self._hide_slash()

    def insert_slash_completion(self, command: str):
        """斜杠命令被选中后，清空输入框（命令将直接执行，不需要保留文字）"""
        self.clear()
        self._slash_active = False
        self._slash_start_pos = -1

    def _is_slash_visible(self) -> bool:
        """斜杠命令弹出框是否可见"""
        return (self._slash_popup is not None
                and self._slash_popup.isVisible()
                and self._slash_popup.count() > 0)

    def inputMethodQuery(self, query):
        """★ macOS IME 关键修复：为输入法提供光标位置和周围文本信息
        
        macOS 的输入法框架（NSTextInputClient 协议）通过此方法查询：
          - ImEnabled       → 此控件是否接受输入法输入
          - ImCursorRectangle → 光标在控件中的矩形区域（用于定位候选框）
          - ImSurroundingText → 光标周围的文本（辅助联想/智能选词）
          - ImCursorPosition  → 光标在周围文本中的位置
          - ImFont           → 当前字体信息
          - ImHints          → 输入法提示
        
        如果不覆写此方法，PySide2 嵌入 Houdini 时（尤其 macOS）
        可能返回错误值或零矩形，导致 IME 不激活或候选框位置异常。
        """
        qt = QtCore.Qt
        if query == qt.ImEnabled:
            return True
        if query == qt.ImCursorRectangle:
            # 返回光标在控件坐标系中的矩形
            cursor_rect = self.cursorRect()
            return cursor_rect
        if query == qt.ImFont:
            return self.font()
        if query == qt.ImCursorPosition:
            tc = self.textCursor()
            block = tc.block()
            return tc.position() - block.position()
        if query == qt.ImSurroundingText:
            tc = self.textCursor()
            block = tc.block()
            return block.text()
        if query == qt.ImCurrentSelection:
            tc = self.textCursor()
            return tc.selectedText()
        try:
            if query == qt.ImHints:
                return qt.ImhNone
        except Exception:
            pass
        # 其他查询交给父类
        return super().inputMethodQuery(query)

    def inputMethodEvent(self, event):
        """★ IME 输入法事件处理（中文/日文/韩文等）— 全平台增强版
        
        PySide2 在 Houdini 环境下需要显式处理 inputMethodEvent，
        否则中文输入法的预编辑（composing）和提交（commit）可能无法正常工作。
        
        IME 工作流程：
        1. 用户开始输入拼音 → preeditString 不为空（composing 状态）
        2. 用户选择候选词 → commitString 不为空，preeditString 清空
        3. 用户按 Esc 取消 → preeditString 清空，commitString 为空
        
        macOS 特别注意：
        - 某些 PySide2 版本在 macOS 上不会正确传递 commit 事件
        - 需要确保 commitString 被手动插入文本光标
        """
        preedit = event.preeditString()
        commit = event.commitString()
        
        # 更新 composing 状态
        self._ime_composing = bool(preedit)
        
        # 先让父类处理（标准路径）
        super().inputMethodEvent(event)
        
        # macOS PySide2 修补：如果父类没有正确处理 commitString，
        # 手动将已确认的文字插入光标位置。
        # 通过检查：如果有 commit 文字，但当前文本中找不到它（说明父类漏了），
        # 则手动插入。
        if commit and not preedit:
            tc = self.textCursor()
            current_text = self.toPlainText()
            # 简单检查：如果 commit 的文字在光标位置之前不存在，手动插入
            # 注意：这是一个保守检查，只有在父类确实没有处理时才介入
            pos = tc.position()
            before = current_text[:pos]
            if not before.endswith(commit):
                tc.insertText(commit)
                self.setTextCursor(tc)
    
    def keyPressEvent(self, event):
        key = event.key()
        
        # ★ IME composing 中：不拦截任何按键，全部交给输入法处理
        # 当用户正在输入拼音/选择候选词时，Enter/Esc 等键应由 IME 处理，
        # 而不是触发"发送消息"或"取消补全"
        if self._ime_composing:
            super().keyPressEvent(event)
            return
        
        # ── @ 补全活跃时的键盘处理 ──
        if self._at_active and self._is_completer_visible():
            popup = self._completer_popup
            
            if key == QtCore.Qt.Key_Escape:
                # Escape: 取消补全 + 隐藏弹窗
                self.cancel_at_completion()
                return
            
            if key == QtCore.Qt.Key_Up:
                # Up: 在列表中上移
                row = popup.currentRow()
                if row > 0:
                    popup.setCurrentRow(row - 1)
                return
            
            if key == QtCore.Qt.Key_Down:
                # Down: 在列表中下移
                row = popup.currentRow()
                if row < popup.count() - 1:
                    popup.setCurrentRow(row + 1)
                return
            
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and not (event.modifiers() & QtCore.Qt.ShiftModifier):
                # Enter: 选中当前项（而非发送消息）
                current = popup.currentItem()
                if current:
                    self.insert_at_completion(current.text())
                    self._hide_completer()
                return
            
            if key == QtCore.Qt.Key_Tab:
                # Tab: 也可以选中当前项
                current = popup.currentItem()
                if current:
                    self.insert_at_completion(current.text())
                    self._hide_completer()
                return
        
        elif self._at_active and key == QtCore.Qt.Key_Escape:
            # 补全活跃但弹窗不可见（如无匹配结果）：仍允许 Escape 取消
            self.cancel_at_completion()
            return

        # ── / 斜杠命令补全活跃时的键盘处理 ──
        if self._slash_active and self._is_slash_visible():
            popup = self._slash_popup

            if key == QtCore.Qt.Key_Escape:
                self.cancel_slash_completion()
                return

            if key == QtCore.Qt.Key_Up:
                popup.select_prev()
                return

            if key == QtCore.Qt.Key_Down:
                popup.select_next()
                return

            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and not (event.modifiers() & QtCore.Qt.ShiftModifier):
                if popup.confirm_current():
                    return

            if key == QtCore.Qt.Key_Tab:
                if popup.confirm_current():
                    return

        elif self._slash_active and key == QtCore.Qt.Key_Escape:
            self.cancel_slash_completion()
            return

        # ── 常规键盘处理 ──
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if event.modifiers() & QtCore.Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.sendRequested.emit()
                return
        
        super().keyPressEvent(event)
    
    def mousePressEvent(self, event):
        """点击文本区域时，如果补全弹窗可见则关闭"""
        if self._is_completer_visible():
            self.cancel_at_completion()
        if self._is_slash_visible():
            self.cancel_slash_completion()
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        """★ 获焦时确保 IME 正确激活（macOS 关键修复）
        
        macOS 上，当 QPlainTextEdit 嵌入 Houdini 等宿主应用时，
        获焦时 IME 可能不会自动激活。通过显式调用 update() 和
        重新设置 WA_InputMethodEnabled，强制系统重新检查 IME 状态。
        """
        super().focusInEvent(event)
        # 确保 IME 标志仍然有效
        self.setAttribute(QtCore.Qt.WA_InputMethodEnabled, True)
        # 触发控件重绘，间接通知系统重新查询 inputMethodQuery
        self.update()

    def focusOutEvent(self, event):
        """失焦时关闭补全弹窗并重置 IME 状态"""
        self._ime_composing = False  # 重置 IME 状态
        # 延迟关闭：如果焦点转移到弹窗本身（用户点击弹窗），不关闭
        QtCore.QTimer.singleShot(100, self._check_focus_dismiss)
        super().focusOutEvent(event)

    def _check_focus_dismiss(self):
        """检查是否需要因失焦而关闭弹窗"""
        if not self.hasFocus():
            if self._is_completer_visible():
                if self._completer_popup and not self._completer_popup.hasFocus():
                    self.cancel_at_completion()
            if self._is_slash_visible():
                if self._slash_popup and not self._slash_popup.hasFocus():
                    self.cancel_slash_completion()

    def resizeEvent(self, event):
        """窗口宽度变化时重新计算高度（自动换行可能改变行数）"""
        super().resizeEvent(event)
        self._schedule_adjust()

    # ---- 拖拽节点支持 ----
    
    def dragEnterEvent(self, event):
        """接受来自 Houdini Network Editor 的节点路径拖拽"""
        mime = event.mimeData()
        if mime.hasText():
            text = mime.text().strip()
            # 检查是否像 Houdini 节点路径
            if text.startswith('/') and '/' in text[1:]:
                event.acceptProposedAction()
                return
        # 也接受图片拖拽（原有逻辑）
        if mime.hasImage() or mime.hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        """拖拽释放：优先检查节点路径，其次处理图片"""
        mime = event.mimeData()
        # 1) Houdini 节点路径拖拽
        if mime.hasText():
            text = mime.text().strip()
            if text.startswith('/') and '/' in text[1:]:
                cursor = self.cursorForPosition(
                    event.position().toPoint() if hasattr(event.position(), 'toPoint') else event.pos()
                )
                cursor.insertText(text + " ")
                self.setTextCursor(cursor)
                event.acceptProposedAction()
                return
        # 2) 图片拖拽
        if mime.hasImage():
            image = mime.imageData()
            if image and not image.isNull():
                self.imageDropped.emit(image)
                event.acceptProposedAction()
                return
        if mime.hasUrls():
            _IMG_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
            for url in mime.urls():
                if url.isLocalFile():
                    import os
                    ext = os.path.splitext(url.toLocalFile())[1].lower()
                    if ext in _IMG_EXTS:
                        img = QtGui.QImage(url.toLocalFile())
                        if not img.isNull():
                            self.imageDropped.emit(img)
                            event.acceptProposedAction()
                            return
        super().dropEvent(event)
    
    # ---- 图片粘贴支持 ----
    
    def insertFromMimeData(self, source):
        """重写粘贴：支持从剪贴板粘贴图片"""
        if source.hasImage():
            image = source.imageData()
            if image and not image.isNull():
                self.imageDropped.emit(image)
                return
        # 粘贴文件路径中的图片
        if source.hasUrls():
            _IMG_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
            for url in source.urls():
                if url.isLocalFile():
                    import os
                    ext = os.path.splitext(url.toLocalFile())[1].lower()
                    if ext in _IMG_EXTS:
                        img = QtGui.QImage(url.toLocalFile())
                        if not img.isNull():
                            self.imageDropped.emit(img)
                            return
        # 默认文本粘贴
        super().insertFromMimeData(source)


# ============================================================
# 停止按钮
# ============================================================

