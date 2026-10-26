import pytest

from houdini_agent.core.tool_result_store import ToolResultStore


def test_large_result_is_archived_and_read_by_pointer(tmp_path):
    store = ToolResultStore(tmp_path, "session-a", threshold=20)

    compact = store.archive_if_large("inspect", {"success": True, "result": {"items": ["x" * 40, "second"]}})
    page = store.read(compact["result_ref"], pointer="/result/items/0", offset=0, limit=12)

    assert compact["stored"] is True
    assert compact["result_ref"].startswith("res_")
    assert page["content"] == '"xxxxxxxxxxx'
    assert page["next_offset"] == 12


def test_result_ref_is_scoped_to_session(tmp_path):
    first = ToolResultStore(tmp_path, "session-a", threshold=1)
    second = ToolResultStore(tmp_path, "session-b", threshold=1)
    result_ref = first.archive_if_large("inspect", {"success": True, "result": "large"})["result_ref"]

    with pytest.raises(FileNotFoundError):
        second.read(result_ref)


def test_small_result_is_unchanged(tmp_path):
    store = ToolResultStore(tmp_path, "session-a", threshold=1000)
    result = {"success": True, "result": "small"}

    assert store.archive_if_large("inspect", result) is result


def test_archival_preserves_audit_and_replay_controls(tmp_path):
    store = ToolResultStore(tmp_path, "session-a", threshold=20)
    result = store.archive_if_large("execute_python", {
        "success": True, "result": "x" * 100, "audit_status": "degraded",
        "audit_warning": "audit unavailable", "replay_safe": False,
        "operation_id": "op-1", "scene_consistency": "unknown",
    })

    assert result["audit_status"] == "degraded"
    assert result["replay_safe"] is False
    assert result["operation_id"] == "op-1"
    assert result["scene_consistency"] == "unknown"