# -*- coding: utf-8 -*-
"""Development-only runtime feature toggles."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


FALSE_VALUES = {"0", "false", "no", "off"}
TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DevFeatureToggle:
    env_name: str
    label: str
    default_enabled: bool = True
    description: str = ""


DEV_FEATURE_TOGGLES: List[DevFeatureToggle] = [
    DevFeatureToggle(
        env_name="HOUDINI_AGENT_SELECTION_WATCH",
        label="Selection Watch Auto Stop",
        default_enabled=False,
        description="Stop Agent when Houdini node selection changes during a run.",
    ),
    DevFeatureToggle(
        env_name="HOUDINI_AGENT_HARNESS_V2",
        label="Harness V2",
        default_enabled=True,
        description="Enable policy-governed tool execution harness.",
    ),
]


def parse_env_bool(value: str, default: bool = False) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return default
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return default


def is_dev_reload_enabled() -> bool:
    return parse_env_bool(os.getenv("HOUDINI_AGENT_DEV_RELOAD", ""), default=False)


def is_toggle_enabled(toggle: DevFeatureToggle) -> bool:
    return parse_env_bool(os.getenv(toggle.env_name, ""), default=toggle.default_enabled)


def set_toggle_enabled(toggle: DevFeatureToggle, enabled: bool):
    os.environ[toggle.env_name] = "1" if enabled else "0"
