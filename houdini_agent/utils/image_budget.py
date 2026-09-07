# -*- coding: utf-8 -*-
"""Provider request-size limits for inline images."""

from typing import Callable, Tuple


MAX_IMAGE_BYTES = 2500 * 1024
_LARGE_IMAGE_PIXELS = 2_000_000


def shared_image_budget(image_count: int, total_bytes: int = MAX_IMAGE_BYTES) -> int:
    """Return the per-image raw-byte budget for one multimodal user turn."""
    return max(1, total_bytes // max(1, image_count))


def preferred_image_format(width: int, height: int, has_alpha: bool) -> Tuple[str, str, int]:
    """Avoid expensive PNG encoding for large opaque screenshots."""
    if not has_alpha and width * height >= _LARGE_IMAGE_PIXELS:
        return 'JPEG', 'image/jpeg', 90
    return 'PNG', 'image/png', -1


def encode_image_within_limit(
    image,
    image_format: str,
    media_type: str,
    encode: Callable[[object, str, int], bytes],
    resize: Callable[[object, float], object],
    initial_quality: int = -1,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> Tuple[bytes, str]:
    """Encode an image, reducing JPEG quality and dimensions until it fits."""
    raw_bytes = encode(image, image_format, initial_quality)
    if len(raw_bytes) <= max_bytes:
        return raw_bytes, media_type

    working = image
    while True:
        for jpeg_quality in (85, 75, 65, 55, 45):
            raw_bytes = encode(working, 'JPEG', jpeg_quality)
            if len(raw_bytes) <= max_bytes:
                print(
                    f"[AI Tab] 图片已压缩为 JPEG quality={jpeg_quality} "
                    f"({len(raw_bytes)//1024}KB)"
                )
                return raw_bytes, 'image/jpeg'
        smaller = resize(working, 0.8)
        if smaller is working:
            break
        working = smaller

    raise ValueError("图片压缩后仍超过 2.5MB，请裁剪图片后重试")