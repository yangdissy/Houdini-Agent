from __future__ import annotations

from typing import Optional, Tuple


def lifecycle_ui_state(status: Optional[str]) -> Tuple[bool, bool, bool, bool]:
    """Return approve, deprecate, edit/save, and delete availability."""
    if status == "new":
        return False, False, True, True
    if status == "trial":
        return True, True, True, True
    if status == "active":
        return False, False, True, True
    if status == "deprecated":
        return False, False, False, True
    return False, False, False, False


def memory_status_prefix_key(status: str) -> Optional[str]:
    if status == "trial":
        return "memory_mgr.trial_prefix"
    if status == "deprecated":
        return "memory_mgr.deprecated_prefix"
    return None