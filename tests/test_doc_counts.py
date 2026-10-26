"""Guard public docs against hand-maintained capability counts drifting."""

import re
import sys
from pathlib import Path
from unittest import mock

if "requests" not in sys.modules:
    sys.modules["requests"] = mock.MagicMock(name="requests")

from houdini_agent import skills
from houdini_agent.utils.ai_client import HOUDINI_TOOLS

_GUIDE = Path(__file__).resolve().parents[1] / "plugins" / "PLUGIN_DEV_GUIDE.md"


def test_plugin_guide_counts_match_runtime():
    text = _GUIDE.read_text(encoding="utf-8")
    tools = re.search(r"Core Tools \((\d+)\)", text)
    skill_line = re.search(r"Skills \((\d+) across (\d+) categories\)", text)
    assert tools and skill_line, "count lines missing from PLUGIN_DEV_GUIDE.md"

    skills.reload_skills()
    listed = skills.list_skills()

    assert int(tools.group(1)) == len({t["function"]["name"] for t in HOUDINI_TOOLS})
    assert int(skill_line.group(1)) == len(listed)
    assert int(skill_line.group(2)) == len({item["category"] for item in listed})
