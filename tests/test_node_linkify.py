# -*- coding: utf-8 -*-
"""Node reference linkification tests."""

import unittest

from houdini_agent.ui.node_links import _linkify_node_paths, _linkify_node_paths_plain


class NodeLinkifyTest(unittest.TestCase):
    def test_full_node_path_remains_clickable(self):
        html = _linkify_node_paths_plain("Created /obj/geo1/box1")

        self.assertIn('href="houdini:///obj/geo1/box1"', html)
        self.assertIn('>/obj/geo1/box1</a>', html)

    def test_unique_short_name_displays_short_and_links_full_path(self):
        html = _linkify_node_paths_plain(
            "Created box1",
            {"box1": {"/obj/geo1/box1"}},
        )

        self.assertIn('href="houdini:///obj/geo1/box1"', html)
        self.assertIn('>box1</a>', html)
        self.assertNotIn('>/obj/geo1/box1</a>', html)

    def test_ambiguous_short_name_stays_plain(self):
        html = _linkify_node_paths_plain(
            "Created box1",
            {"box1": {"/obj/geo1/box1", "/obj/geo2/box1"}},
        )

        self.assertNotIn('href="houdini://', html)
        self.assertIn('Created box1', html)

    def test_short_name_inside_code_tag_is_not_linkified(self):
        html = _linkify_node_paths(
            '<p>Created box1</p><code>box1</code>',
            {"box1": {"/obj/geo1/box1"}},
        )

        self.assertEqual(html.count('href="houdini:///obj/geo1/box1"'), 1)
        self.assertIn('<code>box1</code>', html)


if __name__ == "__main__":
    unittest.main()
