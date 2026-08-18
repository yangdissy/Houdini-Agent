# -*- coding: utf-8 -*-
"""Tests for houdini_agent.utils.help_source.

Pure-function tests: parse_wiki on fixture text, iter_pages on a temp zip,
find_help_dir on tmp dirs. No Houdini, no real Doc/ tree. Runs under both
pytest and unittest.
"""

import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from houdini_agent.utils.help_source import (
    find_help_dir,
    get_page,
    iter_pages,
    parse_wiki,
)
from houdini_agent.skills import search_houdini_help
from houdini_agent.utils.doc_rag import HoudiniDocIndex


# ---------------------------------------------------------------
# parse_wiki
# ---------------------------------------------------------------

WIKI_SAMPLE = """= Attribute Wrangle =
#type: node
#context: sop
#internal: attribwrangle

\"\"\"Runs a VEX snippet to modify geometry attributes.\"\"\"

Body paragraph one.
Body paragraph two.

@parameters
Group:
    The group to apply to.
Snippet:
    The VEX snippet to run.

@methods
::`setattrib(geo, name, value)`:
    Sets an attribute.
"""


class ParseWikiTest(unittest.TestCase):
    def test_full_document(self):
        doc = parse_wiki(WIKI_SAMPLE)
        self.assertEqual(doc["title"], "Attribute Wrangle")
        self.assertEqual(doc["type"], "node")
        self.assertEqual(doc["context"], "sop")
        self.assertEqual(doc["internal"], "attribwrangle")
        self.assertEqual(
            doc["description"],
            "Runs a VEX snippet to modify geometry attributes.",
        )
        self.assertIn("Body paragraph one.", doc["body"])
        self.assertIn("parameters", doc["sections"])
        self.assertIn("Group:", doc["sections"]["parameters"])
        self.assertIn("methods", doc["sections"])
        self.assertIn("setattrib", doc["sections"]["methods"])

    def test_multiline_description(self):
        text = '= T =\n#type: x\n\n"""line one\nline two\nline three"""\n\nBody.\n'
        doc = parse_wiki(text)
        self.assertEqual(doc["description"], "line one\nline two\nline three")

    def test_empty_input(self):
        doc = parse_wiki("")
        self.assertEqual(doc["title"], "")
        self.assertEqual(doc["body"], "")
        self.assertEqual(doc["sections"], {})

    def test_no_title(self):
        doc = parse_wiki("#context: dop\n\nJust body text.\n")
        self.assertEqual(doc["title"], "")
        self.assertEqual(doc["context"], "dop")


# ---------------------------------------------------------------
# iter_pages
# ---------------------------------------------------------------

def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)


class IterPagesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_filters_and_decodes(self):
        zp = self._tmp / "nodes.zip"
        _make_zip(zp, {
            "nodes/sop/attribwrangle.txt": "= AW =",
            "nodes/sop/_internal.txt": "skip me",   # path contains /_
            "_meta.txt": "skip me",                  # leading underscore
            "nodes/sop/readme.md": "not txt",        # wrong extension
            "nodes/dop/solver.txt": "= Solver =",
        })
        pages = list(iter_pages(zp))
        names = sorted(n for n, _ in pages)
        self.assertEqual(
            names,
            ["nodes/dop/solver.txt", "nodes/sop/attribwrangle.txt"],
        )
        self.assertTrue(all(isinstance(raw, str) for _, raw in pages))

    def test_max_scan(self):
        zp = self._tmp / "vex.zip"
        _make_zip(zp, {f"vex/f{i}.txt": f"content {i}" for i in range(10)})
        pages = list(iter_pages(zp, max_scan=3))
        self.assertEqual(len(pages), 3)

    def test_max_bytes(self):
        zp = self._tmp / "hom.zip"
        _make_zip(zp, {"hom/big.txt": "x" * 1000})
        pages = list(iter_pages(zp, max_bytes=100))
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0][1]), 100)

    def test_missing_zip_raises(self):
        with self.assertRaises(Exception):
            list(iter_pages(self._tmp / "nope.zip"))

    def test_page_lookup_uses_same_filter_decode_and_limit(self):
        _make_zip(self._tmp / "nodes.zip", {
            "nodes/sop/public.txt": "= Public =\n\n" + "é" * 20,
            "nodes/sop/_internal.txt": "secret",
        })

        page = get_page(self._tmp, "nodes\\sop\\public.txt", max_bytes=20)

        self.assertEqual(page[0], "nodes.zip")
        self.assertLessEqual(len(page[1].encode("utf-8")), 20)
        self.assertIsNone(get_page(self._tmp, "nodes/sop/_internal.txt"))


class HelpChainTest(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self._cache = self._tmp / "cache"
        _make_zip(self._tmp / "nodes.zip", {
            "nodes/sop/attribwrangle.txt": WIKI_SAMPLE,
            "nodes/sop/_internal.txt": "= Internal =\nsecret keyword",
        })

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_same_temp_source_drives_search_page_and_index(self):
        original_resolve = search_houdini_help._resolve
        search_houdini_help._resolve = lambda: (self._tmp, parse_wiki)
        try:
            search = search_houdini_help.run(mode="search", query="Attribute Wrangle")
            page = search_houdini_help.run(
                mode="page", path="nodes/sop/attribwrangle.txt"
            )
            hidden = search_houdini_help.run(
                mode="page", path="nodes/sop/_internal.txt"
            )
        finally:
            search_houdini_help._resolve = original_resolve

        index = HoudiniDocIndex(
            str(self._tmp), cache_dir=str(self._cache),
            doc_dir=str(self._tmp / "missing-docs"), load_knowledge=False,
        )

        self.assertEqual(search["hit_count"], 1)
        self.assertEqual(page["title"], "Attribute Wrangle")
        self.assertIn("not found", hidden["error"])
        self.assertIn("attribwrangle", index.node_index)
        self.assertTrue((self._cache / "houdini_doc_index.json").exists())


# ---------------------------------------------------------------
# find_help_dir
# ---------------------------------------------------------------

class FindHelpDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_explicit_valid(self):
        (self._tmp / "nodes.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
        self.assertEqual(find_help_dir(str(self._tmp)), self._tmp)

    def test_explicit_invalid_falls_through(self):
        """Explicit dir without zips is skipped."""
        os.environ.pop("HFS", None)
        result = find_help_dir(str(self._tmp))
        # Must not return the invalid explicit dir (bundled Doc/ may match
        # instead, which is fine).
        if result is not None:
            self.assertNotEqual(result, self._tmp)


if __name__ == "__main__":
    unittest.main()
