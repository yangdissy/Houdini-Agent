# -*- coding: utf-8 -*-
"""Image request-size regression tests."""

import unittest
import base64

from houdini_agent.utils.image_budget import (
    MAX_IMAGE_BYTES,
    encode_image_within_limit,
    preferred_image_format,
    shared_image_budget,
)


class ImageMixinEncodingTest(unittest.TestCase):
    def test_large_png_is_compressed_below_inline_image_budget(self):
        calls = []

        def encode(image, image_format, quality):
            calls.append((image, image_format, quality))
            if image_format == 'BMP':
                return b'x' * (6 * 1024 * 1024)
            return b'x' * (2 * 1024 * 1024)

        raw_bytes, media_type = encode_image_within_limit(
            object(), 'BMP', 'image/bmp', encode, lambda image, scale: image
        )

        self.assertLessEqual(len(raw_bytes), MAX_IMAGE_BYTES)
        self.assertLessEqual(len(base64.b64encode(raw_bytes)), 4 * 1024 * 1024)
        self.assertEqual(media_type, 'image/jpeg')
        self.assertEqual(calls[-1][1:], ('JPEG', 85))

    def test_quality_is_reduced_before_dimensions(self):
        calls = []
        resize_calls = []

        def encode(image, image_format, quality):
            calls.append((image_format, quality))
            if image_format == 'PNG' or quality > 65:
                return b'x' * 2000
            return b'x' * 800

        raw_bytes, _ = encode_image_within_limit(
            object(), 'PNG', 'image/png', encode,
            lambda image, scale: resize_calls.append(scale) or image,
            max_bytes=1000,
        )

        self.assertEqual(len(raw_bytes), 800)
        self.assertEqual(calls, [('PNG', -1), ('JPEG', 85), ('JPEG', 75), ('JPEG', 65)])
        self.assertEqual(resize_calls, [])

    def test_large_opaque_image_skips_png_encoding(self):
        self.assertEqual(preferred_image_format(2048, 2048, False), ('JPEG', 'image/jpeg', 90))
        self.assertEqual(preferred_image_format(800, 600, False), ('PNG', 'image/png', -1))
        self.assertEqual(preferred_image_format(2048, 2048, True), ('PNG', 'image/png', -1))

    def test_multiple_images_share_total_budget(self):
        self.assertEqual(shared_image_budget(1), MAX_IMAGE_BYTES)
        self.assertEqual(shared_image_budget(2), MAX_IMAGE_BYTES // 2)
        self.assertEqual(shared_image_budget(10), MAX_IMAGE_BYTES // 10)


if __name__ == '__main__':
    unittest.main()