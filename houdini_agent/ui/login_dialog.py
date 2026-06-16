# -*- coding: utf-8 -*-
"""User login dialog for manual username input."""

from houdini_agent.qt_compat import QtWidgets, QtCore
from shared.user_paths import normalize_username


class LoginDialog(QtWidgets.QDialog):
    """Prompt user for a valid username."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Houdini Agent - 登录")
        self.setMinimumWidth(360)
        self._build_ui()
        self._load_last_username()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        self._title = QtWidgets.QLabel("请输入用户名")
        layout.addWidget(self._title)

        self._edit = QtWidgets.QLineEdit()
        self._edit.setPlaceholderText("字母/数字/下划线/中文，2-32 字符")
        self._edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._edit)

        self._hint = QtWidgets.QLabel("")
        self._hint.setStyleSheet("color: #e66;")
        layout.addWidget(self._hint)

        self._note = QtWidgets.QLabel("提示：用户名将作为数据目录名，请勿使用特殊符号（如：team_01）")
        self._note.setStyleSheet("color: #666;")
        layout.addWidget(self._note)

        self._remember = QtWidgets.QCheckBox("记住用户名")
        self._remember.setChecked(True)
        layout.addWidget(self._remember)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QtWidgets.QPushButton("取消")
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_ok = QtWidgets.QPushButton("确定")
        self._btn_ok.setDefault(True)
        self._btn_ok.clicked.connect(self._on_accept)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addWidget(self._btn_ok)
        layout.addLayout(btn_row)

    def _load_last_username(self):
        settings = QtCore.QSettings("HoudiniAgent", "HoudiniAgent")
        last_user = settings.value("last_username", "")
        if last_user:
            self._edit.setText(str(last_user))

    def _save_last_username(self, username: str):
        settings = QtCore.QSettings("HoudiniAgent", "HoudiniAgent")
        settings.setValue("last_username", username)

    def _on_text_changed(self, text: str):
        if not text:
            self._hint.setText("")
            return
        try:
            normalize_username(text.strip())
            self._hint.setText("")
        except Exception:
            self._hint.setText("用户名不合法")

    def _on_accept(self):
        raw_text = (self._edit.text() or "").strip()
        try:
            username = normalize_username(raw_text)
        except Exception:
            self._hint.setText("用户名不合法")
            return
        if self._remember.isChecked():
            self._save_last_username(username)
        self.accept()

    def get_username(self) -> str:
        return normalize_username((self._edit.text() or "").strip())
