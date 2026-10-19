# -*- coding: utf-8 -*-
"""Generate or verify a versioned Houdini node type catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from houdini_agent.utils.node_catalog import build_node_catalog, render_node_catalog_json


DEFAULT_OUTPUT_DIR = REPO_ROOT / "Doc" / "node_catalog"


def generate(hou_module=None) -> str:
    """Render the catalog for an injected or active Houdini module."""
    if hou_module is None:
        try:
            import hou as hou_module
        except ImportError as exc:
            raise RuntimeError(
                "Houdini's hou module is required; run this script with hython."
            ) from exc
    return render_node_catalog_json(build_node_catalog(hou_module))


def versioned_output(output_dir: Path, rendered_catalog: str) -> Path:
    """Return the stable per-version path encoded by a rendered catalog."""
    version = json.loads(rendered_catalog)["houdini_version_string"]
    return output_dir / f"houdini_node_catalog-{version}.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    try:
        expected = generate()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    output = (args.output or versioned_output(args.output_dir, expected)).resolve()
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != expected:
            print(f"Houdini node catalog drift detected: {output}")
            return 1
        print(f"Houdini node catalog is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
