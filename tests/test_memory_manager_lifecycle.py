from houdini_agent.ui.memory_lifecycle import (
    lifecycle_ui_state,
    memory_status_prefix_key,
)


def test_lifecycle_ui_state_matrix():
    assert lifecycle_ui_state(None) == (False, False, False, False)
    assert lifecycle_ui_state("new") == (False, False, True, True)
    assert lifecycle_ui_state("trial") == (True, True, True, True)
    assert lifecycle_ui_state("active") == (False, False, True, True)
    assert lifecycle_ui_state("deprecated") == (False, False, False, True)
    assert lifecycle_ui_state("unknown") == (False, False, False, False)


def test_memory_status_prefix_key():
    assert memory_status_prefix_key("trial") == "memory_mgr.trial_prefix"
    assert memory_status_prefix_key("deprecated") == "memory_mgr.deprecated_prefix"
    assert memory_status_prefix_key("active") is None
    assert memory_status_prefix_key("unknown") is None