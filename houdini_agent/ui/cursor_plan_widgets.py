# -*- coding: utf-8 -*-
"""Plan workflow widgets."""

import math

from houdini_agent.qt_compat import QtWidgets, QtCore, QtGui

from .cursor_theme import CursorTheme


# ============================================================
# 计划块（兼容旧代码）
# ============================================================

class PlanBlock(QtWidgets.QWidget):
    """执行计划显示"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps = []
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)
        
        self.title = QtWidgets.QLabel("Plan")
        self.title.setObjectName("planTitle")
        layout.addWidget(self.title)
        
        self.steps_layout = QtWidgets.QVBoxLayout()
        self.steps_layout.setSpacing(1)
        layout.addLayout(self.steps_layout)
    
    def add_step(self, text: str, status: str = "pending") -> QtWidgets.QLabel:
        icons = {"pending": "○", "running": "◎", "done": "●", "error": "✗"}
        
        label = QtWidgets.QLabel(f"{icons[status]} {text}")
        label.setObjectName("planStep")
        label.setProperty("state", status)
        label.style().unpolish(label)
        label.style().polish(label)
        self.steps_layout.addWidget(label)
        self._steps.append((label, text))
        return label
    
    def update_step(self, index: int, status: str):
        if 0 <= index < len(self._steps):
            label, text = self._steps[index]
            icons = {"pending": "○", "running": "◎", "done": "●", "error": "✗"}
            label.setText(f"{icons[status]} {text}")
            label.setProperty("state", status)
            label.style().unpolish(label)
            label.style().polish(label)


# ============================================================
# PlanDAGWidget — QPainter 自绘 DAG 流程图
# ============================================================

class PlanDAGWidget(QtWidgets.QWidget):
    """Houdini 节点网络架构蓝图，用 QPainter 自绘。

    展示 Plan 执行完成后的 **节点网络拓扑**（设计蓝图），
    而不是执行步骤顺序。

    特性：
    - 按节点类型着色（SOP=蓝、OBJ=橙、MAT=绿 等）
    - 分组容器（地形系统、散布系统 等）
    - 新节点 vs 已有节点 视觉区分
    - 贝塞尔曲线连线 + 箭头
    - 自动分层布局
    - QScrollArea 包裹，窗口窄时横向滚动
    """

    # 节点类型 → (填充色, 边框色, 文字色)
    _TYPE_COLORS = {
        "sop":    ("#0d1f3c", "#4a9eff", "#a3d4ff"),
        "obj":    ("#2d1f0d", "#e8a838", "#ffe0a0"),
        "mat":    ("#0d2d1a", "#34d399", "#6ee7b7"),
        "vop":    ("#1f0d2d", "#a78bfa", "#c4b5fd"),
        "rop":    ("#2d0d1a", "#f472b6", "#f9a8d4"),
        "dop":    ("#0d2d2d", "#22d3ee", "#67e8f9"),
        "lop":    ("#1a2d0d", "#a3e635", "#d9f99d"),
        "cop":    ("#2d2d0d", "#facc15", "#fef08a"),
        "chop":   ("#1f2d0d", "#84cc16", "#bef264"),
        "out":    ("#2d1215", "#f87171", "#fca5a5"),
        "subnet": ("#1a1a2e", "#818cf8", "#c7d2fe"),
        "null":   ("#1a1a1a", "#6b7280", "#9ca3af"),
        "other":  ("#1e2030", "#4a5068", "#8892a8"),
    }

    # 已有节点的暗化系数
    _EXISTING_ALPHA = 0.5

    NODE_W = 160
    NODE_H = 42
    H_GAP = 50       # 层间距（水平，连线区域）
    V_GAP = 20       # 同层节点间距（垂直）
    PAD = 30          # 画布内边距
    GROUP_PAD = 16    # 分组容器内边距
    GROUP_TITLE_H = 22  # 分组标题高度

    def __init__(self, arch_data: dict = None, parent=None):
        """
        Args:
            arch_data: architecture 字段数据，包含 nodes, connections, groups
        """
        super().__init__(parent)
        self._arch = arch_data or {}
        self._nodes = self._arch.get("nodes", [])
        self._connections = self._arch.get("connections", [])
        self._groups = self._arch.get("groups", [])
        self._node_rects = {}      # node_id -> QRectF
        self._group_rects = {}     # group_name -> QRectF
        self._collapsed = True
        self.setObjectName("planDAG")
        self._content_w = 0
        self._content_h = 0
        self._layout_nodes()
        self._pulse_phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)   # ~25fps

    def _tick(self):
        self._pulse_phase = (self._pulse_phase + 0.04) % (math.pi * 2)
        # 架构图有新节点标记时微弱脉动
        has_new = any(n.get("is_new", True) for n in self._nodes)
        if has_new:
            self.update()

    def set_collapsed(self, collapsed: bool):
        self._collapsed = collapsed
        if collapsed:
            self.setFixedHeight(0)
            self.setMinimumWidth(0)
        else:
            self._layout_nodes()
        self.update()

    def update_architecture(self, arch_data: dict):
        """更新架构数据并重新布局"""
        self._arch = arch_data or {}
        self._nodes = self._arch.get("nodes", [])
        self._connections = self._arch.get("connections", [])
        self._groups = self._arch.get("groups", [])
        self._layout_nodes()
        self.update()

    # ----------------------------------------------------------
    # 布局算法
    # ----------------------------------------------------------
    def _layout_nodes(self):
        """Sugiyama 分层布局：按连接拓扑自动分层排列节点。"""
        if self._collapsed:
            self.setFixedHeight(0)
            self.setMinimumWidth(0)
            return
        if not self._nodes:
            self.setFixedHeight(0)
            self.setMinimumWidth(0)
            return

        node_map = {n["id"]: n for n in self._nodes}

        # ── 1) 构建邻接表 ──
        children = {n["id"]: [] for n in self._nodes}      # from → [to, ...]
        parents = {n["id"]: [] for n in self._nodes}        # to   → [from, ...]
        for conn in self._connections:
            f, t = conn.get("from", ""), conn.get("to", "")
            if f in node_map and t in node_map:
                children[f].append(t)
                parents[t].append(f)

        # ── 2) 计算深度（从源头开始 BFS） ──
        depths = {}
        def get_depth(nid, visited=None):
            if nid in depths:
                return depths[nid]
            if visited is None:
                visited = set()
            if nid in visited:  # 防环
                depths[nid] = 0
                return 0
            visited.add(nid)
            if not parents[nid]:
                depths[nid] = 0
                return 0
            d = max(get_depth(p, visited) for p in parents[nid]) + 1
            depths[nid] = d
            return d

        for n in self._nodes:
            get_depth(n["id"])

        # ── 3) 分层 ──
        layers = {}
        for nid, d in depths.items():
            layers.setdefault(d, []).append(nid)

        max_depth = max(layers.keys()) if layers else 0
        max_per_layer = max(len(v) for v in layers.values()) if layers else 1

        # 垂直方向布局（从上到下，更符合 Houdini 节点网络习惯）
        total_w = max_per_layer * (self.NODE_W + self.H_GAP) - self.H_GAP
        total_h = (max_depth + 1) * (self.NODE_H + self.V_GAP + 10) - self.V_GAP

        self._node_rects.clear()
        for depth, nids in layers.items():
            y = self.PAD + depth * (self.NODE_H + self.V_GAP + 10)
            layer_w = len(nids) * (self.NODE_W + self.H_GAP) - self.H_GAP
            start_x = self.PAD + (total_w - layer_w) / 2
            for i, nid in enumerate(nids):
                x = start_x + i * (self.NODE_W + self.H_GAP)
                self._node_rects[nid] = QtCore.QRectF(x, y, self.NODE_W, self.NODE_H)

        # ── 4) 计算分组容器 ──
        self._group_rects.clear()
        for grp in self._groups:
            grp_name = grp.get("name", "")
            grp_nids = [nid for nid in grp.get("node_ids", []) if nid in self._node_rects]
            if not grp_name or not grp_nids:
                continue
            rects = [self._node_rects[nid] for nid in grp_nids]
            gp = self.GROUP_PAD
            min_x = min(r.left() for r in rects) - gp
            min_y = min(r.top() for r in rects) - gp - self.GROUP_TITLE_H
            max_x = max(r.right() for r in rects) + gp
            max_y = max(r.bottom() for r in rects) + gp
            self._group_rects[grp_name] = (
                QtCore.QRectF(min_x, min_y, max_x - min_x, max_y - min_y),
                grp.get("color", ""),
            )

        # ── 5) 最终尺寸 ──
        all_rects = list(self._node_rects.values())
        all_rects += [r for r, _ in self._group_rects.values()]
        if all_rects:
            max_right = max(r.right() for r in all_rects)
            max_bottom = max(r.bottom() for r in all_rects)
            self._content_w = int(max_right + self.PAD)
            self._content_h = int(max_bottom + self.PAD)
        else:
            self._content_w = 200
            self._content_h = 80

        self.setMinimumWidth(self._content_w)
        self.setFixedHeight(self._content_h)

    # ----------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------
    def _elide_text(self, painter, text: str, max_width: int) -> str:
        """按像素宽度截断文字（支持 CJK）"""
        fm = painter.fontMetrics()
        if fm.horizontalAdvance(text) <= max_width:
            return text
        for i in range(len(text), 0, -1):
            candidate = text[:i] + "…"
            if fm.horizontalAdvance(candidate) <= max_width:
                return candidate
        return "…"

    _GROUP_HINT_COLORS = {
        "blue":    (74, 158, 255),
        "green":   (52, 211, 153),
        "purple":  (167, 139, 250),
        "orange":  (232, 168, 56),
        "red":     (248, 113, 113),
        "cyan":    (34, 211, 238),
        "yellow":  (250, 204, 21),
        "pink":    (244, 114, 182),
    }

    # ----------------------------------------------------------
    # 绘制
    # ----------------------------------------------------------
    def paintEvent(self, event):
        if self._collapsed or not self._nodes:
            return

        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing)

        # ── 0) 背景 ──
        bg_grad = QtGui.QLinearGradient(0, 0, self.width(), self.height())
        bg_grad.setColorAt(0.0, QtGui.QColor("#0d0f1a"))
        bg_grad.setColorAt(1.0, QtGui.QColor("#111420"))
        p.fillRect(self.rect(), bg_grad)

        # 背景网格点
        grid_color = QtGui.QColor(100, 116, 139, 12)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(grid_color)
        for gx in range(0, self.width(), 20):
            for gy in range(0, self.height(), 20):
                p.drawEllipse(QtCore.QPointF(gx, gy), 0.5, 0.5)

        # ── 1) 分组容器 ──
        for grp_name, (grect, color_hint) in self._group_rects.items():
            r, g, b = self._GROUP_HINT_COLORS.get(color_hint, (167, 139, 250))
            # 半透明填充
            p.setBrush(QtGui.QColor(r, g, b, 8))
            pen = QtGui.QPen(QtGui.QColor(r, g, b, 40), 1.0, QtCore.Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(grect, 10, 10)
            # 标题
            title_font = QtGui.QFont(CursorTheme.FONT_BODY.split(",")[0].strip("' "), 8)
            title_font.setWeight(QtGui.QFont.Medium)
            p.setFont(title_font)
            p.setPen(QtGui.QColor(r, g, b, 140))
            title_rect = QtCore.QRectF(grect.left() + 10, grect.top() + 3,
                                        grect.width() - 20, self.GROUP_TITLE_H - 4)
            p.drawText(title_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, grp_name)

        node_map = {n["id"]: n for n in self._nodes}

        # ── 2) 连线（贝塞尔曲线）──
        for conn in self._connections:
            src_id = conn.get("from", "")
            dst_id = conn.get("to", "")
            src_rect = self._node_rects.get(src_id)
            dst_rect = self._node_rects.get(dst_id)
            if not src_rect or not dst_rect:
                continue

            # 连线颜色（取源节点类型色的淡化版）
            src_node = node_map.get(src_id, {})
            ntype = src_node.get("type", "other")
            _, border_c_hex, _ = self._TYPE_COLORS.get(ntype, self._TYPE_COLORS["other"])
            line_color = QtGui.QColor(border_c_hex)
            line_color.setAlpha(80)

            # 从源底部中点 → 目标顶部中点（垂直布局）
            x1 = src_rect.center().x()
            y1 = src_rect.bottom()
            x2 = dst_rect.center().x()
            y2 = dst_rect.top()

            path = QtGui.QPainterPath()
            path.moveTo(x1, y1)
            ctrl_v = abs(y2 - y1) * 0.4
            if abs(x2 - x1) < 5:
                # 纯垂直
                path.cubicTo(x1, y1 + ctrl_v, x2, y2 - ctrl_v, x2, y2)
            else:
                # S 形曲线
                mid_y = (y1 + y2) / 2
                path.cubicTo(x1, mid_y, x2, mid_y, x2, y2)

            p.setPen(QtGui.QPen(line_color, 1.4))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawPath(path)

            # 箭头（向下）
            al = 6
            arr_angle = math.pi / 2
            arr_tip_x, arr_tip_y = x2, y2
            ax1 = arr_tip_x - al * math.cos(arr_angle - 0.4)
            ay1 = arr_tip_y - al * math.sin(arr_angle - 0.4)
            ax2 = arr_tip_x - al * math.cos(arr_angle + 0.4)
            ay2 = arr_tip_y - al * math.sin(arr_angle + 0.4)
            arrow = QtGui.QPolygonF([
                QtCore.QPointF(arr_tip_x, arr_tip_y),
                QtCore.QPointF(ax1, ay1),
                QtCore.QPointF(ax2, ay2),
            ])
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(line_color)
            p.drawPolygon(arrow)

            # 连线标签（如果有）
            conn_label = conn.get("label", "")
            if conn_label:
                lbl_font = QtGui.QFont(CursorTheme.FONT_BODY.split(",")[0].strip("' "), 7)
                p.setFont(lbl_font)
                lbl_color = QtGui.QColor(border_c_hex)
                lbl_color.setAlpha(100)
                p.setPen(lbl_color)
                mid_x = (x1 + x2) / 2
                mid_y_lbl = (y1 + y2) / 2
                p.drawText(QtCore.QPointF(mid_x + 4, mid_y_lbl), conn_label)

        # ── 3) 节点 ──
        label_font = QtGui.QFont(CursorTheme.FONT_BODY.split(",")[0].strip("' "), 9)
        type_font = QtGui.QFont(CursorTheme.FONT_BODY.split(",")[0].strip("' "), 7)

        for n in self._nodes:
            nid = n["id"]
            rect = self._node_rects.get(nid)
            if not rect:
                continue

            ntype = n.get("type", "other")
            is_new = n.get("is_new", True)
            fill_c, border_c, text_c = self._TYPE_COLORS.get(ntype, self._TYPE_COLORS["other"])

            # 新节点微弱脉动光晕
            if is_new:
                pulse = 0.7 + 0.3 * math.sin(self._pulse_phase)
                glow_color = QtGui.QColor(border_c)
                glow_color.setAlpha(int(30 * pulse))
                glow_rect = rect.adjusted(-3, -3, 3, 3)
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(glow_color)
                p.drawRoundedRect(glow_rect, 10, 10)

            # 节点背景
            bg = QtGui.QColor(fill_c)
            alpha = 220 if is_new else int(220 * self._EXISTING_ALPHA)
            bg.setAlpha(alpha)
            p.setBrush(bg)

            # 边框
            bc = QtGui.QColor(border_c)
            if not is_new:
                bc.setAlpha(int(255 * self._EXISTING_ALPHA))
            p.setPen(QtGui.QPen(bc, 1.5 if is_new else 1.0))
            p.drawRoundedRect(rect, 6, 6)

            # 左侧类型色条
            bar_w = 3
            bar_rect = QtCore.QRectF(rect.left() + 2, rect.top() + 4,
                                      bar_w, rect.height() - 8)
            p.setPen(QtCore.Qt.NoPen)
            bar_color = QtGui.QColor(border_c)
            if not is_new:
                bar_color.setAlpha(int(200 * self._EXISTING_ALPHA))
            p.setBrush(bar_color)
            p.drawRoundedRect(bar_rect, 1.5, 1.5)

            # 上行：节点标签（label）
            p.setFont(label_font)
            label_text = n.get("label", nid)
            label_text = self._elide_text(p, label_text, int(self.NODE_W - 20))
            tc = QtGui.QColor(text_c)
            if not is_new:
                tc.setAlpha(int(255 * self._EXISTING_ALPHA))
            p.setPen(tc)
            label_rect = QtCore.QRectF(rect.left() + 10, rect.top() + 3,
                                        rect.width() - 14, 20)
            p.drawText(label_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, label_text)

            # 下行：类型 + 节点名
            p.setFont(type_font)
            sub_text = f"{ntype.upper()}: {nid}"
            sub_text = self._elide_text(p, sub_text, int(self.NODE_W - 20))
            sub_color = QtGui.QColor(border_c)
            if not is_new:
                sub_color.setAlpha(int(180 * self._EXISTING_ALPHA))
            else:
                sub_color.setAlpha(180)
            p.setPen(sub_color)
            sub_rect = QtCore.QRectF(rect.left() + 10, rect.top() + 22,
                                      rect.width() - 14, 16)
            p.drawText(sub_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, sub_text)

            # 已有节点标记（虚线边框覆盖）
            if not is_new:
                exist_pen = QtGui.QPen(QtGui.QColor(border_c), 0.8, QtCore.Qt.DotLine)
                exist_pen.setColor(QtGui.QColor(border_c).darker(150))
                p.setPen(exist_pen)
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 5, 5)

        p.end()


# ============================================================
# StreamingPlanCard — 流式 Plan 生成 + 最终交互卡片（二合一）
# ============================================================

class StreamingPlanCard(QtWidgets.QWidget):
    """流式 Plan 卡片 — 生成阶段逐步构建，完成后原地升级为完整交互卡片。

    生命周期：
    1. 创建时只有标题骨架 + STREAMING 标签
    2. on_tool_args_delta 驱动 update_from_accumulated()，逐步渲染标题 → 概述 → 步骤
    3. 工具执行完毕后，调用 finalize_with_data(plan_data) 原地补充：
       - 步骤详情（sub_steps, tools, risk, deps, expected, fallback, notes）
       - DAG 架构图
       - 进度条
       - Confirm / Reject 按钮
    4. 后续 update_step_status / set_confirmed / set_rejected 等方法与旧 PlanViewer 完全兼容
    """

    planConfirmed = QtCore.Signal(dict)
    planRejected = QtCore.Signal()

    _STATUS_ICONS = {
        "pending": "○", "running": "◎", "done": "●", "error": "✗",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plan = {}
        self._step_labels = {}   # step_id -> (icon_w, title_lbl)
        self._confirmed = False
        self._rejected = False
        self._finalized = False

        self.setObjectName("planViewerOuter")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 6)
        outer.setSpacing(0)

        self._card = QtWidgets.QFrame(self)
        self._card.setObjectName("planViewerCard")
        self._card_lay = QtWidgets.QVBoxLayout(self._card)
        self._card_lay.setContentsMargins(14, 10, 14, 10)
        self._card_lay.setSpacing(6)

        # ── 标题行 ──
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)
        icon_lbl = QtWidgets.QLabel("📋")
        icon_lbl.setFixedWidth(18)
        header.addWidget(icon_lbl)

        self._title_lbl = QtWidgets.QLabel("Planning...")
        self._title_lbl.setObjectName("planViewerTitle")
        self._title_lbl.setWordWrap(True)
        header.addWidget(self._title_lbl, 1)

        self._status_badge = QtWidgets.QLabel("STREAMING")
        self._status_badge.setObjectName("planStatusBadge")
        self._status_badge.setAlignment(QtCore.Qt.AlignCenter)
        self._status_badge.setFixedHeight(20)
        self._status_badge.setMinimumWidth(60)
        header.addWidget(self._status_badge)
        self._card_lay.addLayout(header)

        # ── 概述 ──
        self._overview_lbl = QtWidgets.QLabel("")
        self._overview_lbl.setObjectName("planOverview")
        self._overview_lbl.setWordWrap(True)
        self._overview_lbl.setVisible(False)
        self._card_lay.addWidget(self._overview_lbl)

        # ── 分隔线 ──
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setObjectName("planSeparator")
        self._card_lay.addWidget(sep)

        # ── 步骤容器（流式填充） ──
        self._steps_container = QtWidgets.QWidget()
        self._steps_lay = QtWidgets.QVBoxLayout(self._steps_container)
        self._steps_lay.setContentsMargins(0, 0, 0, 0)
        self._steps_lay.setSpacing(2)
        self._card_lay.addWidget(self._steps_container)

        # ── 正在生成指示器 ──
        self._loading_lbl = QtWidgets.QLabel("  ⋯ generating steps...")
        self._loading_lbl.setObjectName("planStepDep")
        self._card_lay.addWidget(self._loading_lbl)

        # ── 以下区域在 finalize_with_data 时动态添加 ──
        # DAG, 进度条, 按钮 → 预留 placeholder
        self._dag_widget = None
        self._dag_scroll = None
        self._dag_toggle = None
        self._progress_bar = None
        self._btn_row = None
        self._btn_confirm = None
        self._btn_reject = None

        outer.addWidget(self._card)

        # ── 流式跟踪状态 ──
        self._rendered_step_count = 0
        self._current_title = ""
        self._current_overview = ""

    # ==================================================================
    # 流式阶段 API — 由 on_tool_args_delta 驱动
    # ==================================================================

    def update_from_accumulated(self, accumulated: str):
        """从 create_plan 的不完整 JSON 中增量提取并渲染内容。"""
        if self._finalized:
            return
        import re as _re

        # 提取 title
        m_title = _re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', accumulated)
        if m_title and m_title.group(1) != self._current_title:
            self._current_title = m_title.group(1)
            self._title_lbl.setText(self._current_title)

        # 提取 overview
        m_ov = _re.search(r'"overview"\s*:\s*"((?:[^"\\]|\\.)*)"', accumulated)
        if m_ov and m_ov.group(1) != self._current_overview:
            self._current_overview = m_ov.group(1)
            self._overview_lbl.setText(self._current_overview)
            self._overview_lbl.setVisible(True)

        # 匹配 steps 数组中的每个 step 对象
        steps_match = _re.search(r'"steps"\s*:\s*\[', accumulated)
        if not steps_match:
            return

        steps_json_start = steps_match.end()
        step_pattern = _re.compile(
            r'\{\s*"id"\s*:\s*"(step-\d+)"\s*,\s*'
            r'"(?:title|description)"\s*:\s*"((?:[^"\\]|\\.)*)"',
        )
        all_steps = list(step_pattern.finditer(accumulated, steps_json_start))

        # 仅渲染新出现的 step
        for i in range(self._rendered_step_count, len(all_steps)):
            m = all_steps[i]
            self._add_streaming_step(m.group(1), m.group(2))
            self._rendered_step_count += 1

        # 检查是否进入 architecture 部分
        if '"architecture"' in accumulated:
            self._loading_lbl.setText("  ⋯ generating architecture...")

    def _add_streaming_step(self, step_id: str, text: str):
        """流式阶段：添加一行简化版步骤"""
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(4, 2, 0, 0)

        icon_w = QtWidgets.QLabel("○")
        icon_w.setFixedWidth(14)
        icon_w.setObjectName("planStepIcon")
        icon_w.setProperty("state", "pending")
        row.addWidget(icon_w)

        sid_lbl = QtWidgets.QLabel(step_id)
        sid_lbl.setObjectName("planStepId")
        sid_lbl.setFixedWidth(50)
        row.addWidget(sid_lbl)

        title_lbl = QtWidgets.QLabel(text)
        title_lbl.setObjectName("planStepTitle")
        title_lbl.setWordWrap(True)
        row.addWidget(title_lbl, 1)

        w = QtWidgets.QWidget()
        w.setLayout(row)
        self._steps_lay.addWidget(w)

        # 记录引用以便 finalize 时更新
        self._step_labels[step_id] = (icon_w, title_lbl)

    # ==================================================================
    # 完成阶段 API — 工具执行结束后调用
    # ==================================================================

    def finalize_with_data(self, plan_data: dict):
        """用完整的 plan_data 原地升级卡片 — 补充详情、DAG、进度条、按钮。

        此方法只会被调用一次。调用后卡片与旧 PlanViewer 功能完全等价。
        """
        if self._finalized:
            return
        self._finalized = True
        self._plan = plan_data

        # 隐藏加载指示器
        self._loading_lbl.setVisible(False)

        # 用完整数据刷新标题 + 概述（覆盖流式阶段的可能不完整内容）
        self._title_lbl.setText(plan_data.get("title", self._current_title or "Plan"))
        overview = plan_data.get("overview", "")
        if overview:
            self._overview_lbl.setText(overview)
            self._overview_lbl.setVisible(True)

        # ── 清空流式步骤，用完整步骤重建（含详情、deps 等） ──
        while self._steps_lay.count():
            item = self._steps_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._step_labels.clear()

        steps = plan_data.get("steps", [])
        phases = plan_data.get("phases", [])
        step_phase_map = {}
        for phase in phases:
            for sid in phase.get("step_ids", []):
                step_phase_map[sid] = phase.get("name", "")

        rendered_phases = set()
        for s in steps:
            step_id = s.get("id", "")

            # Phase 标题
            phase_name = step_phase_map.get(step_id, "")
            if phase_name and phase_name not in rendered_phases:
                rendered_phases.add(phase_name)
                phase_sep = QtWidgets.QFrame()
                phase_sep.setFrameShape(QtWidgets.QFrame.HLine)
                phase_sep.setObjectName("planPhaseSeparator")
                self._steps_lay.addWidget(phase_sep)
                phase_lbl = QtWidgets.QLabel(phase_name)
                phase_lbl.setObjectName("planPhaseHeader")
                self._steps_lay.addWidget(phase_lbl)

            # 步骤主行
            step_row = QtWidgets.QHBoxLayout()
            step_row.setSpacing(6)
            step_row.setContentsMargins(4, 2, 0, 0)

            status = s.get("status", "pending")
            icon_w = QtWidgets.QLabel(self._STATUS_ICONS.get(status, "○"))
            icon_w.setFixedWidth(14)
            icon_w.setObjectName("planStepIcon")
            icon_w.setProperty("state", status)
            step_row.addWidget(icon_w)

            sid_lbl = QtWidgets.QLabel(step_id)
            sid_lbl.setObjectName("planStepId")
            sid_lbl.setFixedWidth(50)
            step_row.addWidget(sid_lbl)

            title_text = s.get("title", s.get("description", ""))
            title_lbl = QtWidgets.QLabel(title_text)
            title_lbl.setObjectName("planStepTitle")
            title_lbl.setWordWrap(True)
            step_row.addWidget(title_lbl, 1)

            # 风险标记
            risk = s.get("risk", "")
            if risk and risk != "low":
                risk_lbl = QtWidgets.QLabel(f"⚠ {risk.upper()}")
                risk_lbl.setObjectName("planStepRisk")
                risk_lbl.setProperty("risk", risk)
                step_row.addWidget(risk_lbl)

            # 依赖标记
            deps = s.get("depends_on", [])
            if deps:
                short_deps = [d.replace("step-", "s") for d in deps]
                dep_lbl = QtWidgets.QLabel(f"← {','.join(short_deps)}")
                dep_lbl.setObjectName("planStepDep")
                dep_lbl.setMaximumWidth(80)
                step_row.addWidget(dep_lbl)

            row_w = QtWidgets.QWidget()
            row_w.setLayout(step_row)
            self._steps_lay.addWidget(row_w)

            # 步骤详情
            detail_w = QtWidgets.QWidget()
            detail_w.setObjectName("planStepDetail")
            detail_lay = QtWidgets.QVBoxLayout(detail_w)
            detail_lay.setContentsMargins(24, 0, 4, 4)
            detail_lay.setSpacing(2)

            for sub in s.get("sub_steps", []):
                lbl = QtWidgets.QLabel(f"  ├ {sub}")
                lbl.setObjectName("planSubStep")
                lbl.setWordWrap(True)
                detail_lay.addWidget(lbl)
            step_tools = s.get("tools", [])
            if step_tools:
                detail_lay.addWidget(QtWidgets.QLabel(f"Tools: {', '.join(step_tools)}"))
            expected = s.get("expected_result", "")
            if expected:
                lbl = QtWidgets.QLabel(f"Expected: {expected}")
                lbl.setObjectName("planStepExpected")
                lbl.setWordWrap(True)
                detail_lay.addWidget(lbl)
            fallback = s.get("fallback", "")
            if fallback:
                lbl = QtWidgets.QLabel(f"Fallback: {fallback}")
                lbl.setObjectName("planStepFallback")
                lbl.setWordWrap(True)
                detail_lay.addWidget(lbl)
            notes = s.get("notes", "")
            if notes:
                lbl = QtWidgets.QLabel(f"Note: {notes}")
                lbl.setObjectName("planStepNotes")
                lbl.setWordWrap(True)
                detail_lay.addWidget(lbl)

            if detail_lay.count() > 0:
                self._steps_lay.addWidget(detail_w)

            self._step_labels[step_id] = (icon_w, title_lbl)

        # ── DAG 架构图 ──
        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.HLine)
        sep2.setObjectName("planSeparator")
        self._card_lay.addWidget(sep2)

        dag_header_row = QtWidgets.QHBoxLayout()
        arch_data = plan_data.get("architecture", {})
        has_real_arch = bool(arch_data and arch_data.get("nodes"))
        if not has_real_arch:
            arch_data = PlanViewer._build_step_dag(steps)

        dag_title = "Architecture" if has_real_arch else "Flow"
        dag_label = QtWidgets.QLabel(dag_title)
        dag_label.setObjectName("planSectionHeader")
        dag_header_row.addWidget(dag_label)
        dag_header_row.addStretch()

        self._dag_toggle = QtWidgets.QPushButton("▾ Collapse")
        self._dag_toggle.setObjectName("planDAGToggle")
        self._dag_toggle.setCursor(QtCore.Qt.PointingHandCursor)
        self._dag_toggle.setFixedHeight(20)
        self._dag_toggle.clicked.connect(self._toggle_dag)
        dag_header_row.addWidget(self._dag_toggle)
        self._card_lay.addLayout(dag_header_row)

        self._dag_widget = PlanDAGWidget(arch_data, self)
        self._dag_widget.set_collapsed(False)

        self._dag_scroll = QtWidgets.QScrollArea()
        self._dag_scroll.setObjectName("planDAGScroll")
        self._dag_scroll.setWidgetResizable(False)
        self._dag_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._dag_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._dag_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._dag_scroll.setWidget(self._dag_widget)
        # ★ 高度完全跟随 DAG 内容，不设上限，确保架构图完整显示
        h = self._dag_widget._content_h
        scrollbar_h = 14  # 横向滚动条高度预留
        self._dag_scroll.setFixedHeight((h + scrollbar_h) if h > 0 else 200)
        self._card_lay.addWidget(self._dag_scroll)

        # ── 进度条 ──
        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setObjectName("planProgress")
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, max(len(steps), 1))
        self._progress_bar.setValue(0)
        self._card_lay.addWidget(self._progress_bar)

        # ── Confirm / Reject 按钮 ──
        self._btn_row = QtWidgets.QWidget()
        btn_lay = QtWidgets.QHBoxLayout(self._btn_row)
        btn_lay.setContentsMargins(0, 4, 0, 0)
        btn_lay.setSpacing(8)
        btn_lay.addStretch()

        self._btn_reject = QtWidgets.QPushButton("Reject")
        self._btn_reject.setObjectName("planBtnReject")
        self._btn_reject.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_reject.setFixedHeight(28)
        self._btn_reject.setMinimumWidth(80)
        self._btn_reject.clicked.connect(self._do_reject)
        btn_lay.addWidget(self._btn_reject)

        self._btn_confirm = QtWidgets.QPushButton("Confirm")
        self._btn_confirm.setObjectName("planBtnConfirm")
        self._btn_confirm.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_confirm.setFixedHeight(28)
        self._btn_confirm.setMinimumWidth(80)
        self._btn_confirm.clicked.connect(self._do_confirm)
        btn_lay.addWidget(self._btn_confirm)

        self._card_lay.addWidget(self._btn_row)

        # 刷新状态
        self._refresh_ui()

    # ==================================================================
    # PlanViewer 兼容 API — finalize 后可直接使用
    # ==================================================================

    def set_confirmed(self):
        self._confirmed = True
        self._plan["status"] = "confirmed"
        if self._btn_confirm:
            self._btn_confirm.setEnabled(False)
            self._btn_reject.setEnabled(False)
            self._btn_confirm.setText("✓ Confirmed")
        self._refresh_ui()

    def set_rejected(self):
        self._rejected = True
        self._plan["status"] = "rejected"
        if self._btn_confirm:
            self._btn_confirm.setEnabled(False)
            self._btn_reject.setEnabled(False)
            self._btn_reject.setText("✗ Rejected")
        self._refresh_ui()

    def update_step_status(self, step_id: str, status: str, result_summary: str = ""):
        for s in self._plan.get("steps", []):
            if s["id"] == step_id:
                s["status"] = status
                if result_summary:
                    s["result_summary"] = result_summary
                break
        if step_id in self._step_labels:
            icon_w, _ = self._step_labels[step_id]
            icon_w.setText(self._STATUS_ICONS.get(status, "○"))
            icon_w.setProperty("state", status)
            icon_w.style().unpolish(icon_w)
            icon_w.style().polish(icon_w)
        if self._progress_bar:
            self._update_progress()
        all_done = all(
            s.get("status") in ("done", "error")
            for s in self._plan.get("steps", [])
        )
        if all_done:
            self._plan["status"] = "completed"
            self._refresh_ui()

    def get_plan_data(self) -> dict:
        return self._plan

    # ==================================================================
    # 内部方法
    # ==================================================================

    def _do_confirm(self):
        if self._confirmed or self._rejected:
            return
        self.set_confirmed()
        self.planConfirmed.emit(dict(self._plan))

    def _do_reject(self):
        if self._confirmed or self._rejected:
            return
        self.set_rejected()
        self.planRejected.emit()

    def _toggle_dag(self):
        if not self._dag_widget:
            return
        collapsed = not self._dag_widget._collapsed
        self._dag_widget.set_collapsed(collapsed)
        self._dag_toggle.setText("▸ Expand" if collapsed else "▾ Collapse")
        if collapsed:
            self._dag_scroll.setFixedHeight(0)
        else:
            # ★ 高度完全跟随 DAG 内容，不设上限
            h = self._dag_widget._content_h
            scrollbar_h = 14
            self._dag_scroll.setFixedHeight((h + scrollbar_h) if h > 0 else 200)

    def _update_progress(self):
        if not self._progress_bar:
            return
        steps = self._plan.get("steps", [])
        done = sum(1 for s in steps if s.get("status") == "done")
        self._progress_bar.setValue(done)

    def _refresh_ui(self):
        status = self._plan.get("status", "draft")
        badge_map = {
            "draft":     ("DRAFT",     "#64748b"),
            "confirmed": ("CONFIRMED", "#a78bfa"),
            "executing": ("EXECUTING", "#3b82f6"),
            "completed": ("COMPLETED", "#10b981"),
            "rejected":  ("REJECTED",  "#ef4444"),
        }
        text, color = badge_map.get(status, ("DRAFT", "#64748b"))
        style = (
            f"color: {color}; background: rgba(0,0,0,0.3); "
            f"border: 1px solid {color}; border-radius: 4px; "
            f"font-size: 10px; padding: 1px 8px; font-weight: bold;"
        )
        if getattr(self, '_badge_text_cache', None) != text:
            self._status_badge.setText(text)
            self._badge_text_cache = text
        if getattr(self, '_badge_style_cache', None) != style:
            self._status_badge.setStyleSheet(style)
            self._badge_style_cache = style
        if self._btn_row:
            show = status == "draft" and not self._confirmed and not self._rejected
            self._btn_row.setVisible(show)
        if self._progress_bar:
            self._update_progress()


# ============================================================
# PlanViewer — Plan 模式交互卡片（嵌入聊天流）
# ============================================================

class PlanViewer(QtWidgets.QWidget):
    """Plan 执行计划交互卡片。

    在聊天流中渲染为可折叠的卡片，包含：
    - 标题 + 状态
    - 概述
    - 步骤列表（含状态图标）
    - DAG 流程图（可展开/收起）
    - 进度条
    - Confirm / Reject 按钮（仅在 awaiting_confirmation 状态可见）
    """

    planConfirmed = QtCore.Signal(dict)   # 发射 plan_data
    planRejected = QtCore.Signal()

    _STATUS_ICONS = {
        "pending":  "○",
        "running":  "◎",
        "done":     "●",
        "error":    "✗",
    }

    def __init__(self, plan_data: dict, parent=None):
        super().__init__(parent)
        self._plan = plan_data
        self._step_labels = {}  # step_id -> QLabel
        self._confirmed = False
        self._rejected = False

        self.setObjectName("planViewerOuter")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 6)
        outer.setSpacing(0)

        # ── 卡片容器 ──
        self._card = QtWidgets.QFrame(self)
        self._card.setObjectName("planViewerCard")
        card_lay = QtWidgets.QVBoxLayout(self._card)
        card_lay.setContentsMargins(14, 10, 14, 10)
        card_lay.setSpacing(6)

        # ── 标题行 ──
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)

        icon_lbl = QtWidgets.QLabel("📋")
        icon_lbl.setFixedWidth(18)
        header.addWidget(icon_lbl)

        self._title_lbl = QtWidgets.QLabel(plan_data.get("title", "Plan"))
        self._title_lbl.setObjectName("planViewerTitle")
        self._title_lbl.setWordWrap(True)
        header.addWidget(self._title_lbl, 1)

        self._status_badge = QtWidgets.QLabel("DRAFT")
        self._status_badge.setObjectName("planStatusBadge")
        self._status_badge.setAlignment(QtCore.Qt.AlignCenter)
        self._status_badge.setFixedHeight(20)
        self._status_badge.setMinimumWidth(60)
        header.addWidget(self._status_badge)

        card_lay.addLayout(header)

        # ── 概述 ──
        overview = plan_data.get("overview", "")
        if overview:
            ov_lbl = QtWidgets.QLabel(overview)
            ov_lbl.setObjectName("planOverview")
            ov_lbl.setWordWrap(True)
            card_lay.addWidget(ov_lbl)

        # ── 复杂度 & 预估操作数 ──
        complexity = plan_data.get("complexity", "")
        est_ops = plan_data.get("estimated_total_operations", 0)
        if complexity or est_ops:
            meta_parts = []
            if complexity:
                meta_parts.append(f"Complexity: {complexity.upper()}")
            if est_ops:
                meta_parts.append(f"Est. Operations: {est_ops}")
            meta_lbl = QtWidgets.QLabel("  |  ".join(meta_parts))
            meta_lbl.setObjectName("planMetaInfo")
            card_lay.addWidget(meta_lbl)

        # ── 分隔线 ──
        sep1 = QtWidgets.QFrame()
        sep1.setFrameShape(QtWidgets.QFrame.HLine)
        sep1.setObjectName("planSeparator")
        card_lay.addWidget(sep1)

        # ── 步骤列表（增强版：支持 phases 分组 + 子步骤 + 详情）──
        steps = plan_data.get("steps", [])
        phases = plan_data.get("phases", [])

        # 构建 step_id → phase 映射
        step_phase_map = {}
        for phase in phases:
            for sid in phase.get("step_ids", []):
                step_phase_map[sid] = phase.get("name", "")

        rendered_phases = set()
        for s in steps:
            step_id = s.get("id", "")

            # 如果此步骤属于某个 phase，且 phase 还未渲染过 → 插入 phase 标题
            phase_name = step_phase_map.get(step_id, "")
            if phase_name and phase_name not in rendered_phases:
                rendered_phases.add(phase_name)
                phase_sep = QtWidgets.QFrame()
                phase_sep.setFrameShape(QtWidgets.QFrame.HLine)
                phase_sep.setObjectName("planPhaseSeparator")
                card_lay.addWidget(phase_sep)
                phase_lbl = QtWidgets.QLabel(phase_name)
                phase_lbl.setObjectName("planPhaseHeader")
                card_lay.addWidget(phase_lbl)

            # ── 步骤标题行 ──
            step_row = QtWidgets.QHBoxLayout()
            step_row.setSpacing(6)
            step_row.setContentsMargins(4, 2, 0, 0)

            status = s.get("status", "pending")
            icon = self._STATUS_ICONS.get(status, "○")

            icon_w = QtWidgets.QLabel(icon)
            icon_w.setFixedWidth(14)
            icon_w.setObjectName("planStepIcon")
            icon_w.setProperty("state", status)
            step_row.addWidget(icon_w)

            sid_lbl = QtWidgets.QLabel(step_id)
            sid_lbl.setObjectName("planStepId")
            sid_lbl.setFixedWidth(50)
            step_row.addWidget(sid_lbl)

            # 使用 title 作为步骤列表显示文本，description 放在详情中
            title_text = s.get("title", s.get("description", ""))
            title_lbl = QtWidgets.QLabel(title_text)
            title_lbl.setObjectName("planStepTitle")
            title_lbl.setWordWrap(True)
            step_row.addWidget(title_lbl, 1)

            # 风险标记
            risk = s.get("risk", "")
            if risk and risk != "low":
                risk_lbl = QtWidgets.QLabel(f"⚠ {risk.upper()}")
                risk_lbl.setObjectName("planStepRisk")
                risk_lbl.setProperty("risk", risk)
                step_row.addWidget(risk_lbl)

            # 依赖标记（紧凑格式）
            deps = s.get("depends_on", [])
            if deps:
                # 将 "step-1" 缩写为 "s1"，节省空间
                short_deps = [d.replace("step-", "s") for d in deps]
                dep_lbl = QtWidgets.QLabel(f"← {','.join(short_deps)}")
                dep_lbl.setObjectName("planStepDep")
                dep_lbl.setMaximumWidth(80)
                step_row.addWidget(dep_lbl)

            row_w = QtWidgets.QWidget()
            row_w.setLayout(step_row)
            card_lay.addWidget(row_w)

            # ── 步骤详情区域（sub_steps + tools + expected + fallback）──
            detail_w = QtWidgets.QWidget()
            detail_w.setObjectName("planStepDetail")
            detail_lay = QtWidgets.QVBoxLayout(detail_w)
            detail_lay.setContentsMargins(24, 0, 4, 4)
            detail_lay.setSpacing(2)

            # 子步骤
            sub_steps = s.get("sub_steps", [])
            for sub in sub_steps:
                sub_lbl = QtWidgets.QLabel(f"  ├ {sub}")
                sub_lbl.setObjectName("planSubStep")
                sub_lbl.setWordWrap(True)
                detail_lay.addWidget(sub_lbl)

            # 工具列表
            tools = s.get("tools", [])
            if tools:
                tools_lbl = QtWidgets.QLabel(f"Tools: {', '.join(tools)}")
                tools_lbl.setObjectName("planStepTools")
                detail_lay.addWidget(tools_lbl)

            # 预期结果
            expected = s.get("expected_result", "")
            if expected:
                exp_lbl = QtWidgets.QLabel(f"Expected: {expected}")
                exp_lbl.setObjectName("planStepExpected")
                exp_lbl.setWordWrap(True)
                detail_lay.addWidget(exp_lbl)

            # 回退策略
            fallback = s.get("fallback", "")
            if fallback:
                fb_lbl = QtWidgets.QLabel(f"Fallback: {fallback}")
                fb_lbl.setObjectName("planStepFallback")
                fb_lbl.setWordWrap(True)
                detail_lay.addWidget(fb_lbl)

            # 备注
            notes = s.get("notes", "")
            if notes:
                notes_lbl = QtWidgets.QLabel(f"Note: {notes}")
                notes_lbl.setObjectName("planStepNotes")
                notes_lbl.setWordWrap(True)
                detail_lay.addWidget(notes_lbl)

            if detail_lay.count() > 0:
                card_lay.addWidget(detail_w)

            self._step_labels[step_id] = (icon_w, title_lbl)

        # ── DAG 流程图区域 ──
        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.HLine)
        sep2.setObjectName("planSeparator")
        card_lay.addWidget(sep2)

        dag_header_row = QtWidgets.QHBoxLayout()

        # 根据数据类型决定标题
        arch_data = plan_data.get("architecture", {})
        has_real_arch = bool(arch_data and arch_data.get("nodes"))

        if not has_real_arch:
            # ── 回退：从 steps 的 depends_on 自动生成步骤依赖图 ──
            arch_data = self._build_step_dag(steps)

        dag_title = "Architecture" if has_real_arch else "Flow"
        dag_label = QtWidgets.QLabel(dag_title)
        dag_label.setObjectName("planSectionHeader")
        dag_header_row.addWidget(dag_label)
        dag_header_row.addStretch()

        self._dag_toggle = QtWidgets.QPushButton("▾ Collapse")
        self._dag_toggle.setObjectName("planDAGToggle")
        self._dag_toggle.setCursor(QtCore.Qt.PointingHandCursor)
        self._dag_toggle.setFixedHeight(20)
        self._dag_toggle.clicked.connect(self._toggle_dag)
        dag_header_row.addWidget(self._dag_toggle)
        card_lay.addLayout(dag_header_row)

        self._dag_widget = PlanDAGWidget(arch_data, self)
        self._dag_widget.set_collapsed(False)

        # ★ 用 QScrollArea 包裹 DAG，窗口窄时自动出横向滚动条
        self._dag_scroll = QtWidgets.QScrollArea()
        self._dag_scroll.setObjectName("planDAGScroll")
        self._dag_scroll.setWidgetResizable(False)  # 保持 DAG 原始尺寸
        self._dag_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._dag_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._dag_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._dag_scroll.setWidget(self._dag_widget)
        # ★ 高度完全跟随 DAG 内容，不设上限，确保架构图完整显示
        h = self._dag_widget._content_h
        scrollbar_h = 14  # 横向滚动条高度预留
        self._dag_scroll.setFixedHeight((h + scrollbar_h) if h > 0 else 200)
        card_lay.addWidget(self._dag_scroll)

        # ── 进度条 ──
        self._progress_bar = QtWidgets.QProgressBar()
        self._progress_bar.setObjectName("planProgress")
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, max(len(steps), 1))
        self._progress_bar.setValue(0)
        card_lay.addWidget(self._progress_bar)

        # ── 按钮行 ──
        self._btn_row = QtWidgets.QWidget()
        btn_lay = QtWidgets.QHBoxLayout(self._btn_row)
        btn_lay.setContentsMargins(0, 4, 0, 0)
        btn_lay.setSpacing(8)
        btn_lay.addStretch()

        self._btn_reject = QtWidgets.QPushButton("Reject")
        self._btn_reject.setObjectName("planBtnReject")
        self._btn_reject.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_reject.setFixedHeight(28)
        self._btn_reject.setMinimumWidth(80)
        self._btn_reject.clicked.connect(self._do_reject)
        btn_lay.addWidget(self._btn_reject)

        self._btn_confirm = QtWidgets.QPushButton("Confirm")
        self._btn_confirm.setObjectName("planBtnConfirm")
        self._btn_confirm.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_confirm.setFixedHeight(28)
        self._btn_confirm.setMinimumWidth(80)
        self._btn_confirm.clicked.connect(self._do_confirm)
        btn_lay.addWidget(self._btn_confirm)

        card_lay.addWidget(self._btn_row)

        outer.addWidget(self._card)
        self._refresh_ui()

    # ----------------------------------------------------------
    # 公共方法
    # ----------------------------------------------------------

    def set_confirmed(self):
        """确认后禁用按钮"""
        self._confirmed = True
        self._plan["status"] = "confirmed"
        self._btn_confirm.setEnabled(False)
        self._btn_reject.setEnabled(False)
        self._btn_confirm.setText("✓ Confirmed")
        self._refresh_ui()

    def set_rejected(self):
        """拒绝后禁用按钮"""
        self._rejected = True
        self._plan["status"] = "rejected"
        self._btn_confirm.setEnabled(False)
        self._btn_reject.setEnabled(False)
        self._btn_reject.setText("✗ Rejected")
        self._refresh_ui()

    def update_step_status(self, step_id: str, status: str, result_summary: str = ""):
        """实时更新某个步骤的状态（执行阶段调用）"""
        # 更新内部数据
        for s in self._plan.get("steps", []):
            if s["id"] == step_id:
                s["status"] = status
                if result_summary:
                    s["result_summary"] = result_summary
                break

        # 更新步骤列表 UI
        if step_id in self._step_labels:
            icon_w, desc_lbl = self._step_labels[step_id]
            icon = self._STATUS_ICONS.get(status, "○")
            icon_w.setText(icon)
            icon_w.setProperty("state", status)
            icon_w.style().unpolish(icon_w)
            icon_w.style().polish(icon_w)

        # 架构图为静态蓝图，步骤状态变更时无需更新
        # self._dag_widget 展示的是最终节点网络拓扑

        # 更新进度条
        self._update_progress()

        # 检查是否全部完成
        all_done = all(
            s.get("status") in ("done", "error")
            for s in self._plan.get("steps", [])
        )
        if all_done:
            self._plan["status"] = "completed"
            self._refresh_ui()

    def get_plan_data(self) -> dict:
        return self._plan

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _do_confirm(self):
        if self._confirmed or self._rejected:
            return
        self.set_confirmed()
        self.planConfirmed.emit(dict(self._plan))

    def _do_reject(self):
        if self._confirmed or self._rejected:
            return
        self.set_rejected()
        self.planRejected.emit()

    @staticmethod
    def _build_step_dag(steps: list) -> dict:
        """从 steps 的 depends_on 关系自动构建步骤依赖 DAG 数据。

        当 plan 没有 architecture 字段时作为回退方案，
        将步骤列表转换为 PlanDAGWidget 可接受的 architecture 格式。
        """
        nodes = []
        connections = []

        # 收集所有 depends_on 关系
        has_any_deps = any(s.get("depends_on") for s in steps)

        for s in steps:
            sid = s.get("id", "")
            title = s.get("title", s.get("description", sid))
            # 截取前 20 字符作为 label
            label = title[:20] + ("…" if len(title) > 20 else "")
            nodes.append({
                "id": sid,
                "label": label,
                "type": "sop",   # 默认类型
                "is_new": True,
                "params": ", ".join(s.get("tools", [])[:2]) if s.get("tools") else "",
            })

            # 依赖关系 → 连线
            for dep_id in (s.get("depends_on") or []):
                connections.append({"from": dep_id, "to": sid})

        # 没有依赖关系时，自动生成线性链
        if not has_any_deps and len(steps) > 1:
            for i in range(len(steps) - 1):
                connections.append({
                    "from": steps[i]["id"],
                    "to": steps[i + 1]["id"],
                })

        # 尝试从 phases 构建分组（如果有的话不会到这里，但兼容）
        return {
            "nodes": nodes,
            "connections": connections,
            "groups": [],
        }

    def _toggle_dag(self):
        collapsed = not self._dag_widget._collapsed
        self._dag_widget.set_collapsed(collapsed)
        self._dag_toggle.setText("▸ Expand" if collapsed else "▾ Collapse")
        # ★ 同步滚动区域高度
        if collapsed:
            self._dag_scroll.setFixedHeight(0)
        else:
            # DAG 内容高度 + 滚动条可能占用的空间
            h = self._dag_widget._content_h
            scrollbar_h = 14  # 横向滚动条高度预留
            self._dag_scroll.setFixedHeight(h + scrollbar_h)
            self._dag_scroll.setMinimumHeight(h)

    def _update_progress(self):
        steps = self._plan.get("steps", [])
        done = sum(1 for s in steps if s.get("status") == "done")
        self._progress_bar.setValue(done)

    def _refresh_ui(self):
        status = self._plan.get("status", "draft")
        badge_map = {
            "draft":     ("DRAFT",     "#64748b"),
            "confirmed": ("CONFIRMED", "#a78bfa"),
            "executing": ("EXECUTING", "#3b82f6"),
            "completed": ("COMPLETED", "#10b981"),
            "rejected":  ("REJECTED",  "#ef4444"),
        }
        text, color = badge_map.get(status, ("DRAFT", "#64748b"))
        style = (
            f"color: {color}; background: rgba(0,0,0,0.3); "
            f"border: 1px solid {color}; border-radius: 4px; "
            f"font-size: 10px; padding: 1px 8px; font-weight: bold;"
        )
        if getattr(self, '_badge_text_cache', None) != text:
            self._status_badge.setText(text)
            self._badge_text_cache = text
        if getattr(self, '_badge_style_cache', None) != style:
            self._status_badge.setStyleSheet(style)
            self._badge_style_cache = style
        # 按钮可见性
        show_buttons = status in ("draft", "confirmed") and not self._confirmed and not self._rejected
        self._btn_row.setVisible(show_buttons and status == "draft")
        self._update_progress()


# ============================================================
# AskQuestionCard — AI 主动提问交互卡片（Plan 规划阶段）
# ============================================================

class AskQuestionCard(QtWidgets.QFrame):
    """嵌入聊天流中的 AI 提问卡片。

    AI 在 Plan 规划阶段需要澄清信息时，通过 ask_question 工具发起提问。
    用户通过单选/多选/自由文本回答后，点击提交按钮。
    答案通过 answered 信号返回给后台线程。

    questions 结构示例:
        [
            {
                "id": "q1",
                "prompt": "你想用 HeightField 还是 Grid？",
                "options": [
                    {"id": "hf", "label": "HeightField (推荐)"},
                    {"id": "grid", "label": "Grid"}
                ],
                "allow_multiple": false,
                "allow_free_text": true
            }
        ]
    """

    answered = QtCore.Signal(dict)    # 发射答案 dict: {q_id: [selected_option_ids], ...}
    cancelled = QtCore.Signal()       # 用户取消

    def __init__(self, questions: list, parent=None):
        super().__init__(parent)
        self._questions = questions
        self._answered = False
        self._widgets = {}  # q_id -> {"buttons": [...], "group": QButtonGroup, "free_text": QLineEdit}

        self.setObjectName("askQuestionCard")
        self.setFrameShape(QtWidgets.QFrame.NoFrame)

        main_lay = QtWidgets.QVBoxLayout(self)
        main_lay.setContentsMargins(14, 10, 14, 10)
        main_lay.setSpacing(8)

        # ── 标题 ──
        title_row = QtWidgets.QHBoxLayout()
        title_row.setSpacing(6)
        icon_lbl = QtWidgets.QLabel("❓")
        icon_lbl.setFixedWidth(18)
        title_row.addWidget(icon_lbl)
        title_lbl = QtWidgets.QLabel("AI needs your input to proceed")
        title_lbl.setObjectName("askQuestionTitle")
        title_lbl.setWordWrap(True)
        title_row.addWidget(title_lbl, 1)
        main_lay.addLayout(title_row)

        # ── 各问题 ──
        for q in questions:
            q_id = q.get("id", "")
            prompt = q.get("prompt", "")
            options = q.get("options", [])
            allow_multiple = q.get("allow_multiple", False)
            allow_free_text = q.get("allow_free_text", False)

            # 问题分隔线
            sep = QtWidgets.QFrame()
            sep.setFrameShape(QtWidgets.QFrame.HLine)
            sep.setObjectName("askQuestionSep")
            main_lay.addWidget(sep)

            # 问题文本
            q_lbl = QtWidgets.QLabel(f"{q_id.upper()}: {prompt}")
            q_lbl.setObjectName("askQuestionPrompt")
            q_lbl.setWordWrap(True)
            main_lay.addWidget(q_lbl)

            # 选项
            btn_group = None
            buttons = []
            if not allow_multiple:
                btn_group = QtWidgets.QButtonGroup(self)
                btn_group.setExclusive(True)

            for opt in options:
                opt_id = opt.get("id", "")
                opt_label = opt.get("label", "")
                if allow_multiple:
                    btn = QtWidgets.QCheckBox(opt_label)
                else:
                    btn = QtWidgets.QRadioButton(opt_label)
                    btn_group.addButton(btn)
                btn.setObjectName("askQuestionOption")
                btn.setProperty("opt_id", opt_id)
                main_lay.addWidget(btn)
                buttons.append(btn)

            # 自由文本输入
            free_text = None
            if allow_free_text:
                free_text = QtWidgets.QLineEdit()
                free_text.setObjectName("askQuestionFreeText")
                free_text.setPlaceholderText("Or type your answer here...")
                main_lay.addWidget(free_text)

            self._widgets[q_id] = {
                "buttons": buttons,
                "group": btn_group,
                "free_text": free_text,
                "allow_multiple": allow_multiple,
            }

        # ── 按钮行 ──
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(0, 6, 0, 0)
        btn_row.addStretch()

        self._btn_cancel = QtWidgets.QPushButton("Skip")
        self._btn_cancel.setObjectName("askQuestionBtnCancel")
        self._btn_cancel.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_cancel.setFixedHeight(28)
        self._btn_cancel.setMinimumWidth(60)
        self._btn_cancel.clicked.connect(self._do_cancel)
        btn_row.addWidget(self._btn_cancel)

        self._btn_submit = QtWidgets.QPushButton("Submit Answer")
        self._btn_submit.setObjectName("askQuestionBtnSubmit")
        self._btn_submit.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_submit.setFixedHeight(28)
        self._btn_submit.setMinimumWidth(100)
        self._btn_submit.clicked.connect(self._do_submit)
        btn_row.addWidget(self._btn_submit)

        main_lay.addLayout(btn_row)

    def _collect_answers(self) -> dict:
        """收集用户的回答"""
        answers = {}
        for q_id, w_info in self._widgets.items():
            selected = []
            for btn in w_info["buttons"]:
                if btn.isChecked():
                    selected.append(btn.property("opt_id"))
            # 自由文本
            free_text = w_info.get("free_text")
            if free_text and free_text.text().strip():
                selected.append(f"__free_text__:{free_text.text().strip()}")
            answers[q_id] = selected
        return answers

    def _do_submit(self):
        if self._answered:
            return
        self._answered = True
        answers = self._collect_answers()
        self._btn_submit.setEnabled(False)
        self._btn_cancel.setEnabled(False)
        self._btn_submit.setText("✓ Submitted")
        self.answered.emit(answers)

    def _do_cancel(self):
        if self._answered:
            return
        self._answered = True
        self._btn_submit.setEnabled(False)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.setText("Skipped")
        self.cancelled.emit()
