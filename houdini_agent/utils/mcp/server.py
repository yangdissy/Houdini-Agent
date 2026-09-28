# -*- coding: utf-8 -*-
from __future__ import annotations

"""Governed FastMCP HTTP adapter for external clients."""

import asyncio
import logging
import os
import threading
import time
import inspect
from typing import Any, Optional, Callable

try:
	import hou  # type: ignore
except Exception:
	hou = None  # type: ignore

from .settings import read_settings
from .logger import get_logger
from .external_adapter import ExternalMCPExecutionAdapter

log: logging.Logger = get_logger()

# 运行时全局
mcp = None  # FastMCP 实例
mcp_thread_handle: Optional[threading.Thread] = None
stop_event = threading.Event()
_server_start_time: float | None = None
_external_adapter: Optional[ExternalMCPExecutionAdapter] = None

def _fastmcp_available() -> bool:
	return mcp is not None


def configure_external_mcp_adapter(adapter: ExternalMCPExecutionAdapter) -> None:
	"""Install the governed execution boundary required by external MCP."""
	global _external_adapter
	_external_adapter = adapter


def clear_external_mcp_adapter() -> None:
	"""Remove the execution boundary when its owning UI lifecycle ends."""
	global _external_adapter
	_external_adapter = None


def _json_schema_annotation(schema: dict):
	schema_type = schema.get("type") if isinstance(schema, dict) else None
	return {
		"string": str,
		"integer": int,
		"number": float,
		"boolean": bool,
		"array": list,
		"object": dict,
	}.get(schema_type, Any)


def _build_governed_tool_wrapper(tool_name: str, parameters_schema: dict, execute):
	properties = parameters_schema.get("properties", {}) if isinstance(parameters_schema, dict) else {}
	required = set(parameters_schema.get("required", [])) if isinstance(parameters_schema, dict) else set()
	ordered_names = [name for name in properties if name in required]
	ordered_names.extend(name for name in properties if name not in required)
	parameters = []
	for name in ordered_names:
		default = inspect.Parameter.empty if name in required else None
		parameters.append(inspect.Parameter(
			name,
			inspect.Parameter.POSITIONAL_OR_KEYWORD,
			default=default,
			annotation=_json_schema_annotation(properties[name]),
		))

	def governed_tool(*args, **kwargs):
		bound = governed_tool.__signature__.bind(*args, **kwargs)
		return execute(tool_name, dict(bound.arguments))

	governed_tool.__name__ = tool_name
	governed_tool.__signature__ = inspect.Signature(parameters=parameters, return_annotation=dict)
	return governed_tool


def _setup_governed_fastmcp_tools(settings):
	global mcp
	if mcp is None:
		return

	if "health" in settings.allowed_tools and "health" not in settings.denied_tools:
		@mcp.tool(name="health", description="MCP 健康检查")  # type: ignore[attr-defined]
		def health() -> dict:
			now = time.time()
			uptime = (now - _server_start_time) if _server_start_time else None
			capability_state = _external_adapter.capabilities() if _external_adapter else None
			return {
				"status": capability_state["status"] if capability_state else "degraded",
				"message": "OK" if capability_state and capability_state["status"] == "healthy" else "Degraded",
				"data": {
					"hou_available": bool(hou is not None),
					"uptime_sec": uptime,
					"config": {
						"host": settings.host,
						"port": settings.port,
						"transport": settings.transport,
					},
					"degradations": capability_state["degradations"] if capability_state else ["adapter_unavailable"],
				},
			}

	if _external_adapter is None:
		return
	adapter = _external_adapter

	@mcp.tool(name="session_info", description="External MCP session information")  # type: ignore[attr-defined]
	def session_info() -> dict:
		return adapter.session_info()

	@mcp.tool(name="capabilities", description="External MCP runtime capabilities")  # type: ignore[attr-defined]
	def capabilities() -> dict:
		return adapter.capabilities()
	runtime_capabilities = adapter.capabilities()
	available_tools = set(runtime_capabilities.get("available_tools") or [])
	try:
		from ..tool_registry import get_tool_registry
		registry = get_tool_registry()
	except Exception:
		return
	for manifest_entry in adapter.manifest:
		tool_name = manifest_entry.get("name")
		if not tool_name or tool_name not in available_tools:
			continue
		mode = "agent" if manifest_entry.get("mutating") else "ask"
		authorization = registry.authorize_dispatch(tool_name, mode, "houdini")
		if not authorization.get("allowed"):
			continue
		meta = authorization.get("meta")
		if meta is None:
			continue
		description = meta.schema.get("function", {}).get("description", "")

		def execute_external(name, arguments, execution_mode=mode):
			context = adapter.new_context(mode=execution_mode)
			return adapter.execute(context, name, arguments)

		parameters_schema = meta.schema.get("function", {}).get("parameters", {})
		governed_tool = _build_governed_tool_wrapper(tool_name, parameters_schema, execute_external)
		mcp.tool(name=tool_name, description=description)(governed_tool)  # type: ignore[attr-defined]


def _mcp_thread_runner():
	if not _fastmcp_available():
		return
	try:
		if os.name == 'nt' and hasattr(asyncio, 'WindowsProactorEventLoopPolicy'):
			asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
	except Exception:
		pass
	loop = asyncio.new_event_loop()
	asyncio.set_event_loop(loop)

	async def run_server_until_stopped():
		global mcp, _server_start_time
		if mcp is None:
			return
		s = read_settings()
		host = s.host or "127.0.0.1"
		port = s.port or 9000
		transport = s.transport or "streamable-http"
		try:
			server_task = asyncio.create_task(mcp.run_async(transport=transport, host=host, port=port))
		except Exception as e:
			log.exception("Failed to start MCP server: %s", e)
			return
		_server_start_time = time.time()
		log.info("MCP server started at http://%s:%s/mcp/", host, port)
		try:
			while not stop_event.is_set():
				await asyncio.sleep(0.1)
		finally:
			log.info("🛑 Shutdown requested. Cancelling server...")
			server_task.cancel()
			try:
				await server_task
			except asyncio.CancelledError:
				pass
			log.info("Server shutdown completed.")

	loop.run_until_complete(run_server_until_stopped())
	loop.close()


def ensure_mcp_running(auto_start: bool = True) -> tuple[bool, str]:
	global mcp, mcp_thread_handle
	try:
		s = read_settings()
	except ValueError as exc:
		return False, f"MCP 治理配置无效，拒绝启动：{exc}"
	try:
		from fastmcp import FastMCP  # type: ignore
	except Exception:
		return False, "fastmcp 未安装，跳过 MCP 服务器启动。"
	if hou is None:
		return False, "未检测到 Houdini 环境（hou），跳过 MCP 服务器启动。"
	if not s.enabled:
		return False, "配置禁用了 MCP（mcp_enabled=false）。"
	executable_tools = set(s.allowed_tools) - {"health"} - set(s.denied_tools)
	if executable_tools and _external_adapter is None:
		return False, "外部 MCP 治理 adapter 未配置，拒绝暴露可执行工具。"
	if _external_adapter is not None and _external_adapter.is_shutdown():
		return False, "External MCP adapter is stopped; configure a new adapter before restart."
	if mcp_thread_handle and mcp_thread_handle.is_alive():
		return True, "MCP 服务器已在运行。"
	mcp = FastMCP("Houdini MCP Server")  # type: ignore
	_setup_governed_fastmcp_tools(s)
	if auto_start:
		stop_event.clear()
		mcp_thread_handle = threading.Thread(target=_mcp_thread_runner, daemon=True)
		mcp_thread_handle.start()
	return True, "MCP 服务器已启动。"


def stop_mcp_server(timeout: float = 3.0) -> tuple[bool, str]:
	global mcp_thread_handle, _server_start_time
	if _external_adapter is not None:
		_external_adapter.shutdown()
	if not (mcp_thread_handle and mcp_thread_handle.is_alive()):
		return True, "MCP 服务器未运行。"
	stop_event.set()
	mcp_thread_handle.join(timeout=timeout)
	if mcp_thread_handle.is_alive():
		return False, "MCP 服务器未在超时时间内停止。"
	mcp_thread_handle = None
	_server_start_time = None
	return True, "MCP 服务器已停止。"


def get_mcp_status() -> dict:
	from .capabilities import build_connection_status

	try:
		s = read_settings()
	except ValueError as exc:
		return {
			"running": False,
			"status": "configuration_error",
			"error": str(exc),
		}
	running = bool(mcp_thread_handle and mcp_thread_handle.is_alive())
	uptime = (time.time() - _server_start_time) if (_server_start_time) else None
	capability_state = _external_adapter.capabilities() if _external_adapter else None
	connection = build_connection_status(running, capability_state)
	return {
		"running": running,
		"state": connection["state"],
		"degradations": connection["degradations"],
		"host": s.host,
		"port": s.port,
		"transport": s.transport,
		"uptime_sec": uptime,
	}


# ⚠️ 模块级自动启动已移除
# 原因：import 不应产生副作用（启动线程、注册回调等）。
# 请改为由调用方显式调用 ensure_mcp_running()。
# 示例：
#   from utils.mcp.server import ensure_mcp_running
#   ensure_mcp_running(auto_start=True)
