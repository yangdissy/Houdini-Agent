# -*- coding: utf-8 -*-
"""Tests for multilingual semantic node type discovery."""

import unittest
from unittest import mock

import numpy as np

from houdini_agent.utils.mcp import client as mcp_client


class SemanticNodeSearchTest(unittest.TestCase):
    def test_cross_language_description_ranks_english_node(self):
        index = {
            "sop": [
                ("scatter", "Scatters points across a geometry surface", "sop/scatter"),
                ("uvunwrap", "Unwraps geometry into UV coordinates", "sop/uvunwrap"),
            ]
        }
        fake_embedder = mock.Mock(is_semantic=True)
        fake_embedder.encode.return_value = np.array([1.0, 0.0], dtype=np.float32)
        fake_embedder.encode_batch.return_value = np.array(
            [[1.0, 0.0], [0.0, 1.0]], dtype=np.float32
        )
        fake_embedder.batch_cosine_similarity.side_effect = lambda query, matrix: matrix @ query
        client = object.__new__(mcp_client.HoudiniMCP)

        with mock.patch.object(mcp_client, "hou", object()), \
                mock.patch.object(client, "_get_node_types_index", return_value=index), \
                mock.patch("houdini_agent.utils.embedding.get_embedder", return_value=fake_embedder):
            ok, result = client.semantic_search_nodes("把点均匀铺在模型表面", "sop")

        self.assertTrue(ok)
        self.assertIn("sop/scatter", result)
        self.assertNotIn("sop/uvunwrap", result)


if __name__ == "__main__":
    unittest.main()