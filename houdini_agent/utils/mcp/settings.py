# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Tuple
import os, tempfile

try:
	from shared.common_utils import load_config as _load_config, get_cache_dir as _get_cache_dir
except Exception:
	def _get_cache_dir() -> str:
		try:
			here = os.path.dirname(os.path.abspath(__file__))
			cur = here
			while True:
				if os.path.exists(os.path.join(cur, "README.md")):
					break
				parent = os.path.dirname(cur)
				if parent == cur:
					break
				cur = parent
			cache_dir = os.path.join(cur, "cache")
			os.makedirs(cache_dir, exist_ok=True)
			return cache_dir
		except Exception:
			return tempfile.gettempdir()

	def _load_config(config_name: str, dcc_type: Optional[str] = None):
		cfg_dir = os.path.join(os.path.dirname(_get_cache_dir()), "config")
		os.makedirs(cfg_dir, exist_ok=True)
		fname = f"{dcc_type + '_' if dcc_type else ''}{config_name}.ini"
		path = os.path.join(cfg_dir, fname)
		cfg: Dict[str, str] = {}
		if os.path.exists(path):
			try:
				with open(path, "r", encoding="utf-8") as f:
					for line in f:
						if ":" in line:
							k, v = line.strip().split(":", 1)
							cfg[k] = v
			except Exception:
				pass
		return cfg, path


@dataclass
class MCPSettings:
	enabled: bool = False
	host: str = "127.0.0.1"
	port: int = 9000
	transport: str = "streamable-http"
	request_timeout: float = 12.0
	request_retries: int = 2
	request_backoff: float = 0.5
	enable_flipbook: bool = False
	help_server_port: int = 48626  # Houdini 本地帮助服务器端口
	allowed_tools: Tuple[str, ...] = (
		"health", "get_network_structure", "get_geometry_points",
		"get_geometry_primitives", "get_usd_prim_info", "get_usd_layer_stack",
		"get_top_network_status", "list_top_work_items", "get_top_errors", "read_selection",
	)
	denied_tools: Tuple[str, ...] = (
		"execute_python", "execute_python_code", "execute_shell", "load_hip",
		"delete_node", "install_hda", "uninstall_hda",
	)
	max_risk_level: str = "low"
	max_calls_per_session: int = 100
	max_concurrent_calls: int = 2
	max_long_running_calls: int = 1
	write_node_roots: Tuple[str, ...] = ()


def read_settings() -> MCPSettings:
	cfg_dict, _ = _load_config("ai", dcc_type="houdini")

	def _bool(val: Optional[str], default: bool) -> bool:
		if val is None:
			return default
		normalized = str(val).strip().lower()
		if normalized in {"1", "true", "yes", "on"}:
			return True
		if normalized in {"0", "false", "no", "off"}:
			return False
		raise ValueError(f"Invalid boolean MCP setting: {val}")

	def _int(val: Optional[str], default: int, minimum: Optional[int] = None) -> int:
		try:
			parsed = int(val) if val is not None else default
		except (TypeError, ValueError) as exc:
			raise ValueError(f"Invalid integer MCP setting: {val}") from exc
		if minimum is not None and parsed < minimum:
			raise ValueError(f"MCP integer setting must be >= {minimum}: {parsed}")
		return parsed

	def _float(val: Optional[str], default: float) -> float:
		try:
			return float(val) if val is not None else default
		except Exception:
			return default

	host = str(cfg_dict.get("mcp_host", "127.0.0.1")).strip().lower()
	if host not in {"127.0.0.1", "localhost", "::1"}:
		raise ValueError("External MCP only supports loopback hosts")
	allowed_tools = tuple(
		name.strip() for name in str(cfg_dict.get(
			"mcp_allowed_tools",
			"health,get_network_structure,get_geometry_points,get_geometry_primitives,get_usd_prim_info,get_usd_layer_stack,get_top_network_status,list_top_work_items,get_top_errors,read_selection"
		)).split(",")
		if name.strip()
	)
	if not allowed_tools:
		raise ValueError("External MCP allowlist cannot be empty")
	denied_tools = tuple(
		name.strip() for name in str(cfg_dict.get(
			"mcp_denied_tools",
			"execute_python,execute_python_code,execute_shell,load_hip,delete_node,install_hda,uninstall_hda",
		)).split(",") if name.strip()
	)
	max_risk_level = str(cfg_dict.get("mcp_max_risk_level", "low")).strip().lower()
	if max_risk_level not in {"low", "normal", "high"}:
		raise ValueError(f"Invalid external MCP risk level: {max_risk_level}")
	write_node_roots = tuple(
		root.strip().replace("\\", "/").rstrip("/")
		for root in str(cfg_dict.get("mcp_write_node_roots", "")).split(",")
		if root.strip()
	)
	if any(not root.startswith("/") or ".." in root.split("/") for root in write_node_roots):
		raise ValueError("External MCP write node roots must be absolute Houdini paths")

	return MCPSettings(
		enabled=_bool(cfg_dict.get("mcp_enabled"), False),
		host=host,
		port=_int(cfg_dict.get("mcp_port"), 9000),
		transport=cfg_dict.get("mcp_transport", "streamable-http"),
		request_timeout=_float(cfg_dict.get("mcp_request_timeout"), 12.0),
		request_retries=_int(cfg_dict.get("mcp_request_retries"), 2),
		request_backoff=_float(cfg_dict.get("mcp_request_backoff"), 0.5),
		enable_flipbook=_bool(cfg_dict.get("mcp_enable_flipbook"), False),
		help_server_port=_int(cfg_dict.get("mcp_help_server_port"), 48626),
		allowed_tools=allowed_tools,
		denied_tools=denied_tools,
		max_risk_level=max_risk_level,
		max_calls_per_session=_int(cfg_dict.get("mcp_max_calls_per_session"), 100, minimum=1),
		max_concurrent_calls=_int(cfg_dict.get("mcp_max_concurrent_calls"), 2, minimum=1),
		max_long_running_calls=_int(cfg_dict.get("mcp_max_long_running_calls"), 1, minimum=1),
		write_node_roots=write_node_roots,
	)
