# -*- coding: utf-8 -*-
"""Shared read-only Houdini lookup boundary for inspection Skills."""


class HoudiniInspection:
    def __init__(self, hou_module=None):
        if hou_module is None:
            import hou as hou_module  # type: ignore
        self._hou = hou_module

    def node(self, node_path):
        node = self._hou.node(node_path)
        if node is None:
            return None, f"节点不存在: {node_path}"
        return node, None

    def parameter(self, node_path, parameter_name):
        node, error = self.node(node_path)
        if error:
            return None, error
        parameter = node.parm(parameter_name)
        if parameter is None:
            return None, f"节点 {node_path} 不存在标量参数: {parameter_name}"
        return parameter, None


def inspection():
    return HoudiniInspection()