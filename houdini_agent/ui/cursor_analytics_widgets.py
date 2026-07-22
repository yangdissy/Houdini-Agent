# -*- coding: utf-8 -*-
"""Todo and token analytics widgets."""

import time

from houdini_agent.qt_compat import QtWidgets, QtCore, QtGui

from .cursor_theme import CursorTheme


# ============================================================

class TodoItem(QtWidgets.QWidget):
    """单个 Todo 项"""
    
    statusChanged = QtCore.Signal(str, str)
    
    def __init__(self, todo_id: str, text: str, status: str = "pending", parent=None):
        super().__init__(parent)
        self.todo_id = todo_id
        self.text = text
        self.status = status
        
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(4)
        
        self.status_label = QtWidgets.QLabel()
        self.status_label.setFixedWidth(14)
        layout.addWidget(self.status_label)
        
        self.text_label = QtWidgets.QLabel(text)
        self.text_label.setWordWrap(True)
        layout.addWidget(self.text_label, 1)
        
        self._update_style()
    
    def _update_style(self):
        icons = {
            "pending": "○",
            "in_progress": "◎", 
            "done": "●",
            "error": "✗"
        }
        
        icon = icons.get(self.status, "○")
        
        self.status_label.setText(icon)
        self.status_label.setObjectName("todoStatusIcon")
        self.status_label.setProperty("state", self.status)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        
        self.text_label.setObjectName("todoText")
        self.text_label.setProperty("state", self.status)
        self.text_label.style().unpolish(self.text_label)
        self.text_label.style().polish(self.text_label)
    
    def set_status(self, status: str):
        self.status = status
        self._update_style()
        self.statusChanged.emit(self.todo_id, status)


class TodoList(QtWidgets.QWidget):
    """Todo 列表 - 显示 AI 的任务计划（卡片式框体）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._todos = {}
        
        # 最外层无间距
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(0)
        
        # 卡片容器
        self._card = QtWidgets.QFrame(self)
        self._card.setObjectName("todoCard")
        card_layout = QtWidgets.QVBoxLayout(self._card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(4)
        
        # 标题行
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(6)
        
        self.title_label = QtWidgets.QLabel("Todo")
        self.title_label.setObjectName("todoTitle")
        header.addWidget(self.title_label)
        
        self.count_label = QtWidgets.QLabel("0/0")
        self.count_label.setObjectName("todoCount")
        header.addWidget(self.count_label)
        
        header.addStretch()
        
        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.clear_btn.setFixedHeight(20)
        self.clear_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.clear_btn.setObjectName("todoClearBtn")
        self.clear_btn.clicked.connect(self.clear_all)
        header.addWidget(self.clear_btn)
        
        card_layout.addLayout(header)
        
        # 分隔线
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setObjectName("todoSeparator")
        card_layout.addWidget(sep)
        
        # 任务列表
        self.list_layout = QtWidgets.QVBoxLayout()
        self.list_layout.setSpacing(2)
        self.list_layout.setContentsMargins(0, 2, 0, 0)
        card_layout.addLayout(self.list_layout)
        
        outer.addWidget(self._card)
        self.setVisible(False)
    
    def add_todo(self, todo_id: str, text: str, status: str = "pending") -> TodoItem:
        if todo_id in self._todos:
            self._todos[todo_id].text_label.setText(text)
            self._todos[todo_id].set_status(status)
            return self._todos[todo_id]
        
        item = TodoItem(todo_id, text, status, self)
        self._todos[todo_id] = item
        self.list_layout.addWidget(item)
        self._update_count()
        self.setVisible(True)
        return item
    
    def update_todo(self, todo_id: str, status: str):
        if todo_id in self._todos:
            self._todos[todo_id].set_status(status)
            self._update_count()
    
    def remove_todo(self, todo_id: str):
        if todo_id in self._todos:
            item = self._todos.pop(todo_id)
            item.deleteLater()
            self._update_count()
            if not self._todos:
                self.setVisible(False)
    
    def clear_all(self):
        for item in self._todos.values():
            item.deleteLater()
        self._todos.clear()
        self._update_count()
        self.setVisible(False)
    
    def _update_count(self):
        total = len(self._todos)
        done = sum(1 for item in self._todos.values() if item.status == "done")
        self.count_label.setText(f"{done}/{total}")
    
    def get_pending_todos(self) -> list:
        return [
            {"id": todo_id, "text": item.text, "status": item.status}
            for todo_id, item in self._todos.items()
            if item.status not in ("done", "error")
        ]
    
    def get_all_todos(self) -> list:
        return [
            {"id": todo_id, "text": item.text, "status": item.status}
            for todo_id, item in self._todos.items()
        ]
    
    def get_todos_data(self) -> list:
        """返回可序列化的 todo 列表（用于缓存保存/恢复）"""
        return [
            {"id": todo_id, "text": item.text, "status": item.status}
            for todo_id, item in self._todos.items()
        ]

    def restore_todos(self, todos_data: list):
        """从序列化数据恢复 todo 列表"""
        if not todos_data:
            return
        for td in todos_data:
            tid = td.get('id', '')
            text = td.get('text', '')
            status = td.get('status', 'pending')
            if tid and text:
                self.add_todo(tid, text, status)

    def get_todos_summary(self) -> str:
        if not self._todos:
            return ""
        
        lines = ["Current Todo List:"]
        for todo_id, item in self._todos.items():
            status_icons = {
                "pending": "[ ]",
                "in_progress": "[~]",
                "done": "[x]",
                "error": "[!]"
            }
            icon = status_icons.get(item.status, "[ ]")
            lines.append(f"  {icon} {item.text}")
        
        pending = [item for item in self._todos.values() if item.status == "pending"]
        if pending:
            lines.append(f"\nReminder: {len(pending)} tasks pending.")
        
        return "\n".join(lines)


# ============================================================
# Token Analytics Panel — 现代简约可视化分析面板
# ============================================================

class _BarWidget(QtWidgets.QWidget):
    """水平柱状图条——用于可视化 token 占比"""

    def __init__(self, segments: list, max_val: float, parent=None):
        """
        segments: [(value, color_hex), ...]
        max_val: 全局最大值（用于对齐）
        """
        super().__init__(parent)
        self._segments = segments
        self._max = max(max_val, 1)
        self.setFixedHeight(14)
        self.setMinimumWidth(60)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        x = 0.0
        for val, color in self._segments:
            seg_w = (val / self._max) * w
            if seg_w < 0.5:
                continue
            painter.setBrush(QtGui.QColor(color))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(QtCore.QRectF(x, 1, seg_w, h - 2), 2, 2)
            x += seg_w
        painter.end()


class TokenAnalyticsPanel(QtWidgets.QDialog):
    """Token 使用分析面板 - 对齐 Cursor 风格
    
    新增：
    - 预估费用（按实际模型定价）
    - 推理 Token（Reasoning）
    - 延迟（Latency）
    - 每行费用
    """

    _COL_HEADERS = [
        "#", "时间", "模型", "Input", "Cache↓", "Cache↑",
        "Output", "Think", "Total", "延迟", "费用", "",
    ]

    def __init__(self, call_records: list, token_stats: dict, harness_records: list = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Token 使用分析")
        self.setMinimumSize(920, 560)
        self.resize(1020, 640)
        self.setObjectName("tokenPanel")
        self._harness_records = harness_records or []

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        # ---- 摘要卡片 ----
        root.addWidget(self._build_summary(call_records, token_stats))

        # ---- Harness 概览（第五批：调度可观测性）----
        if self._harness_records:
            root.addWidget(self._build_harness_summary(self._harness_records))
            root.addWidget(self._build_harness_table(self._harness_records), 1)

        # ---- 调用明细表 ----
        root.addWidget(self._build_table(call_records), 1)

        # ---- 底部按钮 ----
        self.should_reset_stats = False
        foot = QtWidgets.QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)

        reset_btn = QtWidgets.QPushButton("重置统计")
        reset_btn.setFixedWidth(82)
        reset_btn.setObjectName("tokenResetBtn")
        reset_btn.clicked.connect(self._on_reset)
        foot.addWidget(reset_btn)

        foot.addStretch()
        close_btn = QtWidgets.QPushButton("关闭")
        close_btn.setFixedWidth(72)
        close_btn.setObjectName("tokenCloseBtn")
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        root.addLayout(foot)

    def _on_reset(self):
        """用户点击了重置按钮"""
        self.should_reset_stats = True
        self.accept()

    # -------- 摘要区 --------
    def _build_summary(self, records, stats) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setObjectName("tokenSummaryCard")
        grid = QtWidgets.QGridLayout(card)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)

        total_in = stats.get('input_tokens', 0)
        total_out = stats.get('output_tokens', 0)
        reasoning = stats.get('reasoning_tokens', 0)
        cache_r = stats.get('cache_read', 0)
        cache_w = stats.get('cache_write', 0)
        reqs = stats.get('requests', 0)
        total = stats.get('total_tokens', 0)
        cost = stats.get('estimated_cost', 0.0)
        cache_total = cache_r + cache_w
        hit_rate = (cache_r / cache_total * 100) if cache_total > 0 else 0

        # 平均延迟
        latencies = [r.get('latency', 0) for r in records if r.get('latency', 0) > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        # 费用格式化
        if cost >= 1.0:
            cost_str = f"${cost:.2f}"
        elif cost > 0:
            cost_str = f"${cost:.4f}"
        else:
            cost_str = "$0.00"

        metrics = [
            ("Requests",       f"{reqs}",               CursorTheme.ACCENT_BLUE),
            ("Input",          self._fmt_k(total_in),    CursorTheme.ACCENT_PURPLE),
            ("Output",         self._fmt_k(total_out),   CursorTheme.ACCENT_GREEN),
            ("Reasoning",      self._fmt_k(reasoning),   CursorTheme.ACCENT_YELLOW),
            ("Cache Hit",      self._fmt_k(cache_r),     "#10b981"),
            ("Hit Rate",       f"{hit_rate:.1f}%",       "#10b981"),
            ("Avg Latency",    f"{avg_latency:.1f}s",    CursorTheme.TEXT_SECONDARY),
            ("Est. Cost",      cost_str,                 CursorTheme.ACCENT_BLUE),
        ]
        for col, (label, value, color) in enumerate(metrics):
            lbl = QtWidgets.QLabel(label)
            lbl.setObjectName("tokenMetricLabel")
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            grid.addWidget(lbl, 0, col)

            val = QtWidgets.QLabel(value)
            val.setObjectName("tokenMetricValue")
            # Per-metric dynamic color via inline (unique per column)
            val.setStyleSheet(f"color:{color};")
            val.setAlignment(QtCore.Qt.AlignCenter)
            grid.addWidget(val, 1, col)

        # 进度条: input vs output vs cache
        if total > 0:
            bar = _BarWidget([
                (cache_r, "#10b981"),
                (cache_w, CursorTheme.ACCENT_ORANGE),
                (max(total_in - cache_r - cache_w, 0), CursorTheme.ACCENT_PURPLE),
                (reasoning, CursorTheme.ACCENT_YELLOW),
                (max(total_out - reasoning, 0), CursorTheme.ACCENT_GREEN),
            ], total)
            bar.setFixedHeight(8)
            grid.addWidget(bar, 2, 0, 1, len(metrics))

        return card

    # -------- 明细表 --------
    def _build_table(self, records) -> QtWidgets.QWidget:
        container = QtWidgets.QFrame()
        container.setObjectName("tokenTableCard")
        vbox = QtWidgets.QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # 标题
        title_lbl = QtWidgets.QLabel(f"  调用明细 ({len(records)} calls)")
        title_lbl.setObjectName("tokenTableTitle")
        vbox.addWidget(title_lbl)

        if not records:
            empty = QtWidgets.QLabel("  暂无 API 调用记录")
            empty.setObjectName("tokenTableEmpty")
            vbox.addWidget(empty)
            return container

        # 滚动表格区域
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setObjectName("chatScrollArea")

        table_widget = QtWidgets.QWidget()
        table_layout = QtWidgets.QVBoxLayout(table_widget)
        table_layout.setContentsMargins(8, 0, 8, 8)
        table_layout.setSpacing(0)

        # 表头
        hdr = self._make_row_widget(self._COL_HEADERS, is_header=True)
        table_layout.addWidget(hdr)

        # 找最大 total 以绘制柱状图
        max_total = max((r.get('total_tokens', 0) for r in records), default=1)

        # 最新的调用显示在最上面
        for display_idx, (orig_idx, rec) in enumerate(
            reversed(list(enumerate(records)))
        ):
            row = self._make_record_row(orig_idx, rec, max_total)
            table_layout.addWidget(row)

        table_layout.addStretch()
        scroll.setWidget(table_widget)
        vbox.addWidget(scroll, 1)

        return container

    # -------- Harness 概览 --------
    def _build_harness_summary(self, records) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setObjectName("tokenSummaryCard")
        grid = QtWidgets.QGridLayout(card)
        grid.setContentsMargins(16, 10, 16, 10)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)

        iters = len(records)
        total_tools = sum(int(r.get('tool_count', 0) or 0) for r in records)
        dedup_hits = sum(int(r.get('dedup_hits', 0) or 0) for r in records)
        early_skips = sum(int(r.get('early_skips', 0) or 0) for r in records)
        failed_tools = sum(int(r.get('failed_tools', 0) or 0) for r in records)
        async_tools = sum(int(r.get('async_tools', 0) or 0) for r in records)
        houdini_tools = sum(int(r.get('houdini_tools', 0) or 0) for r in records)

        dedup_rate = (dedup_hits / total_tools * 100.0) if total_tools > 0 else 0.0
        fail_rate = (failed_tools / total_tools * 100.0) if total_tools > 0 else 0.0

        metrics = [
            ("Harness Iter", f"{iters}", CursorTheme.TEXT_SECONDARY),
            ("Tool Calls", self._fmt_k(total_tools), CursorTheme.ACCENT_BLUE),
            ("Dedup Hits", self._fmt_k(dedup_hits), "#10b981"),
            ("Dedup Rate", f"{dedup_rate:.1f}%", "#10b981"),
            ("Early Skip", self._fmt_k(early_skips), CursorTheme.ACCENT_ORANGE),
            ("Failed", self._fmt_k(failed_tools), CursorTheme.ACCENT_RED),
            ("Fail Rate", f"{fail_rate:.1f}%", CursorTheme.ACCENT_RED),
            ("Async/Houdini", f"{async_tools}/{houdini_tools}", CursorTheme.ACCENT_PURPLE),
        ]

        for col, (label, value, color) in enumerate(metrics):
            lbl = QtWidgets.QLabel(label)
            lbl.setObjectName("tokenMetricLabel")
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            grid.addWidget(lbl, 0, col)

            val = QtWidgets.QLabel(value)
            val.setObjectName("tokenMetricValue")
            val.setStyleSheet(f"color:{color};")
            val.setAlignment(QtCore.Qt.AlignCenter)
            grid.addWidget(val, 1, col)

        return card

    def _build_harness_table(self, records) -> QtWidgets.QWidget:
        container = QtWidgets.QFrame()
        container.setObjectName("tokenTableCard")
        vbox = QtWidgets.QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        title_lbl = QtWidgets.QLabel(f"  Harness 调度明细 ({len(records)} rows)")
        title_lbl.setObjectName("tokenTableTitle")
        vbox.addWidget(title_lbl)

        table = QtWidgets.QTableWidget()
        table.setObjectName("tokenTable")
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([
            "时间", "模型", "迭代", "Tools", "Dedup", "Skip", "Failed", "Async/Hou"
        ])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        table.setRowCount(len(records))

        h = table.horizontalHeader()
        h.setStretchLastSection(True)
        h.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        h.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)
        h.setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeToContents)

        for row_idx, rec in enumerate(records):
            time_s = str(rec.get('time', '-'))
            model = str(rec.get('model', '-'))
            iteration = str(rec.get('iteration', '-'))
            tools = str(rec.get('tool_count', 0))
            dedup = str(rec.get('dedup_hits', 0))
            skip = str(rec.get('early_skips', 0))
            failed = str(rec.get('failed_tools', 0))
            async_hou = f"{rec.get('async_tools', 0)}/{rec.get('houdini_tools', 0)}"

            values = [time_s, model, iteration, tools, dedup, skip, failed, async_hou]
            for col_idx, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                table.setItem(row_idx, col_idx, item)

        vbox.addWidget(table, 1)
        return container

    # 列宽定义
    _COL_WIDTHS = [24, 50, 90, 54, 54, 54, 54, 48, 54, 44, 52, 0]

    def _make_row_widget(self, cells: list, is_header=False) -> QtWidgets.QWidget:
        """创建一行（表头或数据行）"""
        row_w = QtWidgets.QWidget()
        row_h = QtWidgets.QHBoxLayout(row_w)
        row_h.setContentsMargins(4, 3, 4, 3)
        row_h.setSpacing(2)

        font_size = "10px" if is_header else "11px"
        fg = CursorTheme.TEXT_MUTED if is_header else CursorTheme.TEXT_PRIMARY
        weight = "bold" if is_header else "normal"
        font_family = f"font-family:'Consolas','Monaco',monospace;" if not is_header else ""

        widths = self._COL_WIDTHS

        for i, text in enumerate(cells):
            lbl = QtWidgets.QLabel(str(text))
            lbl.setObjectName("tokenHeaderCell" if is_header else "tokenDataCell")
            if i < len(widths) and widths[i] > 0:
                lbl.setFixedWidth(widths[i])
            # 数字列右对齐
            lbl.setAlignment(QtCore.Qt.AlignRight if 3 <= i <= 10 else QtCore.Qt.AlignLeft)
            if i < len(widths) and widths[i] == 0:
                row_h.addWidget(lbl, 1)
            else:
                row_h.addWidget(lbl)

        if is_header:
            row_w.setObjectName("tokenHeaderRow")

        return row_w

    def _make_record_row(self, idx: int, rec: dict, max_total: float) -> QtWidgets.QWidget:
        """构建单条记录行"""
        row_w = QtWidgets.QWidget()
        row_w.setObjectName("tokenDataRow")
        row_h = QtWidgets.QHBoxLayout(row_w)
        row_h.setContentsMargins(4, 2, 4, 2)
        row_h.setSpacing(2)

        ts = rec.get('timestamp', '')
        if len(ts) > 10:
            ts = ts[11:19]
        model = rec.get('model', '-')
        if len(model) > 12:
            model = model[:10] + '..'
        inp = rec.get('input_tokens', 0)
        c_hit = rec.get('cache_hit', 0)
        c_miss = rec.get('cache_miss', 0)
        out = rec.get('output_tokens', 0)
        reasoning = rec.get('reasoning_tokens', 0)
        total = rec.get('total_tokens', 0)
        latency = rec.get('latency', 0)

        # 单次费用（优先使用预计算值）
        row_cost = rec.get('estimated_cost', 0.0)
        if not row_cost:
            try:
                from houdini_agent.utils.token_optimizer import calculate_cost
                row_cost = calculate_cost(
                    model=rec.get('model', ''),
                    input_tokens=inp,
                    output_tokens=out,
                    cache_hit=c_hit,
                    cache_miss=c_miss,
                    reasoning_tokens=reasoning,
                )
            except Exception:
                row_cost = 0.0

        cost_str = f"${row_cost:.4f}" if row_cost > 0 else "-"
        latency_str = f"{latency:.1f}s" if latency > 0 else "-"

        cells = [
            str(idx + 1),
            ts,
            model,
            self._fmt_k(inp),
            self._fmt_k(c_hit),
            self._fmt_k(c_miss),
            self._fmt_k(out),
            self._fmt_k(reasoning) if reasoning > 0 else "-",
            self._fmt_k(total),
            latency_str,
            cost_str,
        ]
        widths = self._COL_WIDTHS[:-1]  # 除去最后的 stretch
        colors = [
            CursorTheme.TEXT_MUTED,       # #
            CursorTheme.TEXT_MUTED,       # 时间
            CursorTheme.TEXT_PRIMARY,     # 模型
            CursorTheme.ACCENT_PURPLE,    # Input
            "#10b981",                    # Cache Hit
            CursorTheme.ACCENT_ORANGE,    # Cache Write
            CursorTheme.ACCENT_GREEN,     # Output
            CursorTheme.ACCENT_YELLOW,    # Reasoning
            CursorTheme.TEXT_BRIGHT,      # Total
            CursorTheme.TEXT_SECONDARY,   # 延迟
            CursorTheme.ACCENT_BLUE,      # 费用
        ]
        for i, text in enumerate(cells):
            lbl = QtWidgets.QLabel(text)
            lbl.setObjectName("tokenDataCell")
            if i < len(widths):
                lbl.setFixedWidth(widths[i])
            align = QtCore.Qt.AlignRight if i >= 3 else QtCore.Qt.AlignLeft
            lbl.setAlignment(align)
            c = colors[i] if i < len(colors) else CursorTheme.TEXT_PRIMARY
            # Per-column unique color via inline
            lbl.setStyleSheet(f"color:{c};")
            row_h.addWidget(lbl)

        # 迷你柱状图
        bar = _BarWidget([
            (c_hit, "#10b981"),
            (c_miss, CursorTheme.ACCENT_ORANGE),
            (max(inp - c_hit - c_miss, 0), CursorTheme.ACCENT_PURPLE),
            (reasoning, CursorTheme.ACCENT_YELLOW),
            (max(out - reasoning, 0), CursorTheme.ACCENT_GREEN),
        ], max_total)
        row_h.addWidget(bar, 1)

        return row_w

    @staticmethod
    def _fmt_k(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 10_000:
            return f"{n / 1000:.1f}K"
        if n >= 1000:
            return f"{n / 1000:.1f}K"
        return str(n)


# ============================================================
# 更新通知横幅（启动时检测到新版本 → 输入区上方横幅）
