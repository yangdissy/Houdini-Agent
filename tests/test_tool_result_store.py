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