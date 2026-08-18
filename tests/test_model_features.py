# -*- coding: utf-8 -*-
"""Model feature declarations used by the image-input guard."""

import ast
import unittest
from pathlib import Path


def _model_features():
    source_path = Path(__file__).parents[1] / 'houdini_agent' / 'ui' / 'header.py'
    tree = ast.parse(source_path.read_text(encoding='utf-8-sig'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Attribute) and target.attr == '_model_features'
                   for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError('_model_features declaration not found')


class ModelFeaturesTest(unittest.TestCase):
    def test_of3d_gpt_55_supports_image_input(self):
        self.assertTrue(_model_features()['gpt-5.5']['supports_vision'])


if __name__ == '__main__':
    unittest.main()