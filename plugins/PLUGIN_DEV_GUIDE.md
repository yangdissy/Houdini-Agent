# Houdini Agent Plugin Development Guide

## Quick Start

1. Create a `.py` file in this `plugins/` directory (files starting with `_` are ignored)
2. Define a `PLUGIN_INFO` dict and a `register(ctx)` function
3. Restart Houdini Agent or click "Reload All" in Plugin Manager

## Architecture Overview

The plugin system integrates with the unified ToolRegistry which manages all tools:

- Core Tools (77): Built-in Houdini operations
- Skills (68 across 10 categories): Pre-optimized Python analysis scripts
- Plugin Tools: Tools registered by plugins via ctx.register_tool()
- User Skills: User-defined skills in a custom directory

The counts above are checked by `tests/test_doc_counts.py`; update them when that test fails.

Plugin Manager UI has 3 tabs: Plugins, Tools, Skills.

## Plugin File Structure

```python
PLUGIN_INFO = {
    "name": "My Plugin",
    "version": "1.0.0",
    "author": "Your Name",
    "description": "What it does",
    "settings": [
        {"key": "my_option", "type": "bool", "label": "Enable Feature", "default": True},
    ],
}

def register(ctx):
    ctx.log("My Plugin loaded!")
```

## PluginContext API

### Event Hooks

`ctx.on(event_name, callback, priority=0)`

Events: on_before_request, on_after_response, on_before_tool, on_after_tool, on_content_chunk, on_session_start, on_session_end.

Always include `**kwargs` in callbacks for forward compatibility.

### Custom Tools

```python
ctx.register_tool(name="my_tool", description="desc", schema={...}, handler=fn)
```

Tools auto-register to ToolRegistry, available in Agent/Ask/Plan modes.

### UI Buttons

`ctx.register_button(icon="icon", tooltip="tip", callback=fn)`

### Settings

`ctx.get_setting(key, default=None)` and `ctx.set_setting(key, value)`

### Logging

`ctx.log(msg)` - Prefixed with [Plugin:Name]

## Decorator API

```python
from houdini_agent.utils.hooks import hook, tool, ui_button

@hook("on_after_tool")
def my_hook(tool_name, args, result, **kwargs):
    pass

@tool(name="my_tool", description="desc")
def handler(args):
    return {"success": True}
```

## User Skills

Set path in config/houdini_ai.ini under [skills] user_skill_dir, or use Plugin Manager Skills tab.

## External MCP Write Enablement Checklist

By default an external MCP client (Claude Desktop, Cursor, ...) cannot change the Houdini scene. Every write request must pass three checks **in sequence**, and each check is closed by default. Each check is controlled by one setting in `config/houdini_ai.ini` (one `key:value` per line):

| Check | Setting | Default | Why the default blocks writes (error) |
|---|---|---|---|
| 1. Tool allowlist | `mcp_allowed_tools` | 10 read-only tools | Write tools such as `create_node` are not listed ("not allowlisted") |
| 2. Risk ceiling | `mcp_max_risk_level` | `low` | All write tools are `normal`, above `low` ("risk limit blocked") |
| 3. Writable node roots | `mcp_write_node_roots` | empty | No path is writable ("write node roots are not configured") |

Opening only one or two settings does nothing: e.g. adding `create_node` to the allowlist still fails at check 2. Writes go through only when all three are opened, and even then each write needs confirmation in the panel.

Externally writable tools (all `risk_level=normal`): `create_node`, `set_node_parameter`, `connect_nodes`, `rename_node`, `layout_nodes`, `set_node_flags`. No other mutating tool can be exposed through configuration.

Minimal configuration — append these lines to `config/houdini_ai.ini`:

```
mcp_allowed_tools:health,get_network_structure,read_selection,create_node,set_node_parameter,connect_nodes
mcp_max_risk_level:normal
mcp_write_node_roots:/obj/mcp_sandbox
```

| Line | What it does | Risk / pitfall |
|---|---|---|
| `mcp_allowed_tools` | Lists the tools external clients may call. | The value **replaces** the default list rather than appending to it, so re-list the read tools you still need (`health`, `get_network_structure`, ...). Each added write tool lets any local MCP client request that mutation; add only what the workflow needs. |
| `mcp_max_risk_level` | Raises the ceiling to `normal`. | Applies to every allowlisted tool, not just the new ones. Do not use `high` for scene writes. |
| `mcp_write_node_roots` | Limits writes to nodes at or under these absolute paths (comma-separated). | Every node path in a write must be inside a root. Use a dedicated sandbox subnet; `/obj` or `/` opens the whole scene. |

- Every write still needs confirmation in the Houdini Agent panel; without a confirmation path it is denied.
- `mcp_denied_tools` (default includes `execute_python`, `execute_shell`, `delete_node`, `load_hip`, HDA install/uninstall) always wins over the allowlist.
- Extra argument rules apply: `create_node` needs an explicit `parent_path`, `layout_nodes` needs `network_path` plus 1–50 `node_paths`, and `set_node_flags` only allows bypass/template/lock.
- Session call limits (`mcp_max_calls_per_session`, concurrency limits) and the loopback-only host restriction still apply.

Restart the MCP server after editing the file. Invalid values (unknown risk level, relative or `..` roots, empty allowlist) make settings loading fail instead of falling back to a permissive default.

## Notes

- Files starting with _ are not auto-loaded
- Avoid blocking operations
- Use ctx.log() for logging
- Tool handlers return {"success": True/False, "result": "..."}
- See _example_plugin.py for complete example
