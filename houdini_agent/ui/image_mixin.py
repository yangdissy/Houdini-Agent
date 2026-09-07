# -*- coding: utf-8 -*-
"""
Image Mixin — 图片附件与多模态消息处理

从 ai_tab.py 中拆分出的 Mixin，负责：
- 图片文件选择与加载
- 图片拖拽/粘贴处理
- 图片尺寸自动缩放
- 待发送图片预览区管理
- 多模态 content 构建（OpenAI Vision API 格式）
"""

import os

from houdini_agent.qt_compat import QtWidgets, QtCore, QtGui
from houdini_agent.utils.image_budget import (
    MAX_IMAGE_BYTES,
    encode_image_within_limit,
    preferred_image_format,
    shared_image_budget,
)
from .cursor_chat_widgets import ClickableImageLabel


class ImageMixin:
    """图片附件与多模态消息处理"""

    # 为共享 nginx 代理预留消息、工具 schema 和 JSON 开销；base64 后约 3.3MB。
    _MAX_IMAGE_DIMENSION = 2048  # 最长边不超过 2048px
    _MAX_IMAGE_BYTES = MAX_IMAGE_BYTES

    def _current_model_supports_vision(self) -> bool:
        """检查当前选中的模型是否支持图片输入"""
        model = self.model_combo.currentText()
        features = self._model_features.get(model, {})
        return features.get('supports_vision', False)

    def _on_attach_image(self):
        """打开文件对话框选择图片"""
        if not self._current_model_supports_vision():
            model = self.model_combo.currentText()
            QtWidgets.QMessageBox.information(
                self, "不支持图片",
                f"当前模型 {model} 不支持图片输入。\n请切换到支持视觉的模型（如 Claude、GPT-5.2 等）。"
            )
            return

        file_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;All Files (*)"
        )
        for fp in file_paths:
            self._add_image_from_path(fp)

    def _add_image_from_path(self, file_path: str):
        """从文件路径加载图片并添加到待发送列表（自动缩放过大图片）"""
        import base64
        try:
            # ★ 通过 QImage 加载，统一走缩放逻辑
            qimg = QtGui.QImage(file_path)
            if qimg.isNull():
                print(f"[AI Tab] 无法加载图片: {file_path}")
                return
            qimg = self._resize_image_if_needed(qimg, self._MAX_IMAGE_DIMENSION)

            ext = os.path.splitext(file_path)[1].lower()
            # 优先保持原始格式；BMP/GIF 等不适合直接发 API，统一转 PNG
            if ext in ('.jpg', '.jpeg'):
                fmt, media_type, quality = 'JPEG', 'image/jpeg', 90
            elif ext == '.webp':
                fmt, media_type, quality = 'WEBP', 'image/webp', -1
            else:
                fmt, media_type, quality = preferred_image_format(
                    qimg.width(), qimg.height(), qimg.hasAlphaChannel()
                )

            raw_bytes, media_type = self._encode_image_within_limit(
                qimg, fmt, media_type, quality,
                max_bytes=shared_image_budget(len(self._pending_images) + 1),
            )

            b64 = base64.b64encode(raw_bytes).decode('utf-8')
            self._add_pending_image(b64, media_type)
        except Exception as e:
            print(f"[AI Tab] 加载图片失败: {e}")

    @staticmethod
    def _resize_image_if_needed(image: 'QtGui.QImage', max_dim: int = 2048) -> 'QtGui.QImage':
        """如果图片超过 max_dim，等比缩放。返回缩放后的 QImage。"""
        w, h = image.width(), image.height()
        if w <= max_dim and h <= max_dim:
            return image
        if w > h:
            new_w = max_dim
            new_h = int(h * max_dim / w)
        else:
            new_h = max_dim
            new_w = int(w * max_dim / h)
        print(f"[AI Tab] 图片过大 ({w}x{h})，自动缩放至 {new_w}x{new_h}")
        return image.scaled(new_w, new_h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)

    def _on_image_dropped(self, image: 'QtGui.QImage'):
        """ChatInput 拖拽或粘贴图片的回调"""
        if not self._current_model_supports_vision():
            return
        import base64
        # ★ 自动缩放过大图片
        image = self._resize_image_if_needed(image, self._MAX_IMAGE_DIMENSION)
        fmt, media_type, quality = preferred_image_format(
            image.width(), image.height(), image.hasAlphaChannel()
        )
        raw_bytes, media_type = self._encode_image_within_limit(
            image, fmt, media_type, quality,
            max_bytes=shared_image_budget(len(self._pending_images) + 1),
        )
        b64 = base64.b64encode(raw_bytes).decode('utf-8')
        self._add_pending_image(b64, media_type)

    @classmethod
    def _encode_image_within_limit(
        cls, image, fmt, media_type, quality=-1, max_bytes=None
    ):
        """编码图片，并逐级压缩到代理可接受的单图体积。"""
        def encode(source, target_format, target_quality):
            buf = QtCore.QBuffer()
            buf.open(QtCore.QIODevice.WriteOnly)
            if not source.save(buf, target_format, target_quality):
                buf.close()
                raise ValueError(f"无法编码图片为 {target_format}")
            data = bytes(buf.data())
            buf.close()
            return data

        return encode_image_within_limit(
            image,
            fmt,
            media_type,
            encode=encode,
            resize=lambda source, scale: source.scaled(
                max(1, int(source.width() * scale)),
                max(1, int(source.height() * scale)),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            ),
            initial_quality=quality,
            max_bytes=max_bytes or cls._MAX_IMAGE_BYTES,
        )

    def _add_pending_image(self, b64_data: str, media_type: str):
        """添加图片到待发送列表并在预览区显示缩略图（点击可放大）"""
        # 创建缩略图和完整 pixmap
        img_bytes = __import__('base64').b64decode(b64_data)
        full_pixmap = QtGui.QPixmap()
        # ★ 校验加载结果：损坏/不支持的数据会返回 False，空 pixmap 进入布局
        #   会在 sizeHint 阶段触发 Qt 告警甚至崩溃，这里直接跳过。
        if not full_pixmap.loadFromData(img_bytes) or full_pixmap.isNull():
            print("[AI Tab] 图片数据无效，已跳过预览")
            return
        thumb = full_pixmap.scaled(60, 60, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)

        # 存储
        idx = len(self._pending_images)
        self._pending_images.append((b64_data, media_type, thumb))

        # 创建预览 widget
        img_widget = QtWidgets.QWidget()
        img_layout = QtWidgets.QVBoxLayout(img_widget)
        img_layout.setContentsMargins(2, 2, 2, 2)
        img_layout.setSpacing(1)

        lbl = ClickableImageLabel(thumb, full_pixmap)
        lbl.setObjectName("imgThumb")
        img_layout.addWidget(lbl)

        # 删除按钮
        rm_btn = QtWidgets.QPushButton("x")
        rm_btn.setFixedSize(16, 16)
        rm_btn.setObjectName("imgRemoveBtn")
        rm_btn.clicked.connect(lambda checked=False, i=idx: self._remove_pending_image(i))
        img_layout.addWidget(rm_btn, alignment=QtCore.Qt.AlignCenter)

        # 插入到 stretch 之前
        count = self.image_preview_layout.count()
        self.image_preview_layout.insertWidget(count - 1, img_widget)
        self.image_preview_container.setVisible(True)

    def _rebudget_pending_images(self):
        """按当前图片数量重新编码待发图片，使整组共享固定预算。"""
        import base64
        per_image_bytes = shared_image_budget(len(self._pending_images))
        changed = False
        reencoded = []
        for b64_data, media_type, thumb in self._pending_images:
            raw_bytes = base64.b64decode(b64_data)
            if len(raw_bytes) <= per_image_bytes:
                reencoded.append((b64_data, media_type, thumb))
                continue
            image = QtGui.QImage.fromData(raw_bytes)
            if image.isNull():
                raise ValueError("待发送图片数据无效")
            raw_bytes, media_type = self._encode_image_within_limit(
                image, 'JPEG', 'image/jpeg', 85, max_bytes=per_image_bytes
            )
            reencoded.append((base64.b64encode(raw_bytes).decode('utf-8'), media_type, thumb))
            changed = True
        if changed:
            self._pending_images = reencoded

    def _remove_pending_image(self, index: int):
        """移除待发送图片"""
        if 0 <= index < len(self._pending_images):
            self._pending_images[index] = None  # 标记为已删除
            self._rebuild_image_preview()  # 过滤 None 后重建整个预览区

    def _rebuild_image_preview(self):
        """重新构建图片预览区"""
        # 清除所有 widget（保留 stretch）
        while self.image_preview_layout.count() > 1:
            item = self.image_preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 重新过滤并添加
        new_images = [(b64, mt, th) for entry in self._pending_images
                      if entry is not None for b64, mt, th in [entry]]
        self._pending_images = list(new_images)

        if not self._pending_images:
            self.image_preview_container.setVisible(False)
            return

        for i, (b64, mt, thumb) in enumerate(self._pending_images):
            img_widget = QtWidgets.QWidget()
            img_layout = QtWidgets.QVBoxLayout(img_widget)
            img_layout.setContentsMargins(2, 2, 2, 2)
            img_layout.setSpacing(1)

            # 从 base64 还原完整 pixmap 用于放大预览
            full_pixmap = QtGui.QPixmap()
            if not full_pixmap.loadFromData(__import__('base64').b64decode(b64)) or full_pixmap.isNull():
                # ★ 图片数据无效则跳过，避免空 pixmap 进入布局
                img_widget.deleteLater()
                continue
            lbl = ClickableImageLabel(thumb, full_pixmap)
            lbl.setObjectName("imgThumb")
            img_layout.addWidget(lbl)

            rm_btn = QtWidgets.QPushButton("x")
            rm_btn.setFixedSize(16, 16)
            rm_btn.setObjectName("imgRemoveBtn")
            rm_btn.clicked.connect(lambda checked=False, idx=i: self._remove_pending_image(idx))
            img_layout.addWidget(rm_btn, alignment=QtCore.Qt.AlignCenter)

            count = self.image_preview_layout.count()
            self.image_preview_layout.insertWidget(count - 1, img_widget)

    def _clear_pending_images(self):
        """清空所有待发送图片"""
        self._pending_images.clear()
        while self.image_preview_layout.count() > 1:
            item = self.image_preview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.image_preview_container.setVisible(False)

    def _build_multimodal_content(self, text: str, images: list) -> list:
        """构建包含文字和图片的多模态消息内容（OpenAI Vision API 格式）

        Args:
            text: 用户文字消息
            images: List of (base64_data, media_type, thumbnail) tuples

        Returns:
            list: content 数组，包含 text 和 image_url 项
        """
        # ★ API 支持的 media type 白名单（BMP 等需要先转换）
        _SUPPORTED_MEDIA = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}

        content_parts = []
        # ★ 始终添加 text 部分（即使为空也提供占位符，某些 API 要求至少一个 text block）
        content_parts.append({"type": "text", "text": text or " "})
        # 添加图片
        for b64_data, media_type, _thumb in images:
            if not b64_data:
                continue  # 跳过空数据
            # ★ 不支持的 media type 降级为 image/png
            if media_type not in _SUPPORTED_MEDIA:
                media_type = 'image/png'
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{media_type};base64,{b64_data}"
                }
            })
        return content_parts
