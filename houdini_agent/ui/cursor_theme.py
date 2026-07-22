# -*- coding: utf-8 -*-
"""Shared Cursor-style UI theme constants."""

class CursorTheme:
    """Glassmorphism 深色主题 — 蓝紫底色 + 玻璃质感"""
    # 背景色（深邃蓝黑）
    BG_PRIMARY = "#0f1019"
    BG_SECONDARY = "#0c0e19"
    BG_TERTIARY = "#101224"
    BG_HOVER = "#1c1e36"
    
    # 边框色（玻璃边缘）
    BORDER = "rgba(255,255,255,12)"
    BORDER_FOCUS = "#3b82f6"
    
    # 文字色（更明亮）
    TEXT_PRIMARY = "#e2e8f0"
    TEXT_SECONDARY = "#94a3b8"
    TEXT_MUTED = "#64748b"
    TEXT_BRIGHT = "#ffffff"
    
    # 强调色（更鲜艳）
    ACCENT_BLUE = "#3b82f6"
    ACCENT_GREEN = "#10b981"
    ACCENT_ORANGE = "#f59e0b"
    ACCENT_RED = "#ef4444"
    ACCENT_PURPLE = "#a78bfa"
    ACCENT_YELLOW = "#fbbf24"
    ACCENT_BEIGE = "#d4a574"       # 暖色 — 工具调用/折叠区
    
    # 消息左边界
    BORDER_USER = "rgba(148,163,184,120)"   # 用户消息 — 柔和银灰
    BORDER_AI = "rgba(167,139,250,100)"     # AI 回复 — 淡紫光晕
    
    # 字体
    FONT_BODY = "'Microsoft YaHei', 'SimSun', 'Segoe UI', sans-serif"
    FONT_CODE = "'Consolas', 'Monaco', 'Courier New', monospace"
