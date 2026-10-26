"""Mock-based verification of _tool_set_node_flags getter coverage fix."""
from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs

_install_hou_stub()
_install_thirdparty_stubs()

# 构造一个 mock hou.Node，flag 全是 False
class MockNode:
    def __init__(self):
        self._display = False
        self._render = False
        self._bypass = False
        self._template = False
        self._locked = False
        self._selected = False
    def setDisplayFlag(self, v): self._display = bool(v)
    def isDisplayFlagSet(self): return self._display
    def setRenderFlag(self, v): self._render = bool(v)
    def isRenderFlagSet(self): return self._render
    def bypass(self, v): self._bypass = bool(v)
    def isBypassed(self): return self._bypass
    def setTemplateFlag(self, v): self._template = bool(v)
    def isTemplateFlagSet(self): return self._template
    def setHardLocked(self, v): self._locked = bool(v)
    def isHardLocked(self): return self._locked
    def setSelected(self, v, clear_all_selected=True): self._selected = bool(v)
    def isSelected(self): return self._selected
    class type:
        @staticmethod
        def name(): return "mock"

# 模拟 hou 模块（在 import client 之后替换 client 模块的 hou 引用）
class MockHou:
    _nodes = {}
    @staticmethod
    def node(path): return MockHou._nodes.get(path)

from houdini_agent.utils.mcp import client as mcp_client

# 准备一个节点
node = MockNode()
MockHou._nodes["/obj/geo1/box1"] = node

mcp = mcp_client.HoudiniMCP.__new__(mcp_client.HoudiniMCP)


def _reset_hou():
    """每个测试前重置 mcp_client.hou 引用，避免跨测试文件的模块级污染。

    其他测试文件（如 test_p0_p1_improvements.py）也会给 mcp_client.hou
    赋值它们自己的 mock 实例；pytest 收集顺序会让本文件的模块级
    `mcp_client.hou = MockHou` 被覆盖。在每个 test 前显式重置。
    """
    mcp_client.hou = MockHou
    # 重置节点状态，避免用例间共享污染
    node._display = False
    node._render = False
    node._bypass = False
    node._template = False
    node._locked = False
    node._selected = False

def test_case1_display_render_verified():
    """修复前：display+render 永远 applied_unknown（getters 不含这两项）。
    修复后：应该 verified 且 error 为空。"""
    _reset_hou()
    result = mcp._tool_set_node_flags({"node_path": "/obj/geo1/box1", "display": True, "render": True})
    assert result["success"] is True, result
    assert result["verification"]["status"] == "verified", (
        f"FIX NOT WORKING: expected 'verified', got {result['verification']['status']!r}; "
        f"verification={result['verification']}; error={result.get('error')!r}"
    )
    assert result["error"] == "", f"expected empty error on verified, got: {result['error']!r}"


def test_case2_display_bypass_verified():
    _reset_hou()
    result = mcp._tool_set_node_flags({"node_path": "/obj/geo1/box1", "display": True, "bypass": True})
    assert result["verification"]["status"] == "verified", result


def test_case3_applied_unknown_writes_diagnostic_error():
    """flag 设置静默失败时，error 字段应包含期望 vs 实际的诊断信息，
    供 receipt 层透传到 operation_receipt.error_detail。"""
    _reset_hou()

    class BrokenNode(MockNode):
        def isDisplayFlagSet(self):
            return False  # 假装设置没生效

    broken = BrokenNode()
    MockHou._nodes["/obj/geo1/broken"] = broken
    try:
        result = mcp._tool_set_node_flags({"node_path": "/obj/geo1/broken", "display": True})
        assert result["success"] is True  # set 本身没报错
        assert result["verification"]["status"] == "applied_unknown", result["verification"]
        # 关键：error 字段应包含诊断信息
        assert "display" in result["error"], f"error should mention 'display', got: {result['error']!r}"
        assert "expected" in result["error"], f"error should mention expected vs actual, got: {result['error']!r}"
    finally:
        MockHou._nodes.pop("/obj/geo1/broken", None)


def test_case4_node_not_found_fail_fast():
    _reset_hou()
    result = mcp._tool_set_node_flags({"node_path": "/obj/nonexistent", "display": True})
    assert result["success"] is False
    assert "未找到节点" in result["error"]


def test_case5_select_flag_now_verifiable():
    """select 之前完全不在 getters 里，永远不会 verified。修复后应该可读。"""
    _reset_hou()
    result = mcp._tool_set_node_flags({"node_path": "/obj/geo1/box1", "select": True})
    assert result["verification"]["status"] == "verified", (
        f"select flag should be verifiable now, got: {result['verification']}"
    )
