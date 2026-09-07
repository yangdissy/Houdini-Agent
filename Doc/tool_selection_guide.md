# Houdini Agent Tool Selection Guide

This guide helps the AI choose the smallest useful tool set for each Houdini task. It is a routing reference for agent behavior, not an end-user tutorial.

## Core Rules

1. Read before mutating. Inspect the scene, node, parameter schema, or connection state before changing it.
2. Prefer the most specific read-only tool. Do not call broad scene snapshots when a node-level query is enough.
3. Preview risky node operations. Use `preview_node_operation` before connection replacement, disconnection, deletion, flag changes, cooking, or named null creation when the impact is unclear.
4. Keep layout explicit. Do not rely on connection tools to arrange nodes; use `layout_nodes` only when the user asks for layout or the workflow has created a new batch of nodes.
5. Keep high-risk tools explicit. `execute_shell`, `execute_python`, `delete_node`, `save_hip`, `undo_redo`, and `cook_node` require a clear user intent and remain governed by harness policy. Never call `cook_node` to "verify" your own changes; cooking runs on the Houdini main thread and can freeze the UI on heavy nodes. A successful ordinary `cook_node` does not rule out Manual update stale/empty geometry; follow `recommended_next_action` from `get_geometry_summary` or `verify_network`.
6. Validate after writes with read-only tools. After creating, connecting, changing parameters, or flags, use the smallest sufficient verification tool: `inspect_node` for one node, `check_errors` for error details, `get_node_connections` for a wire change, `verify_network` for an entire parent network (preferred after `create_nodes_batch`), `validate_node_network` for structural issues (orphans, missing required inputs). These read Houdini's existing cook state and do not trigger a recook. In Manual update mode, `get_geometry_summary` / `verify_network` may return `recommended_next_action=temporary_auto_validate`; in Direct Execute mode use that signal before blaming generator nodes.
7. Review visual work only after technical validation. For modeling, material, lighting, camera, composition, or USD lookdev tasks, call `visual_review` after freshness, health, display state, and relevant bindings are established. Report technical evidence separately from image observations. Without an explicit visual goal, limit the review to general readability and obvious defects.

## Mode Boundaries

| Mode | Tool policy |
| --- | --- |
| Ask | Read-only and task tools only. Use it for inspection, explanation, search, and diagnosis. |
| Plan planning | Read-only, search, plan, and question tools. Do not mutate the scene. |
| Agent | Select tools by current request intent. Include read-only helpers and the requested mutation tools. |
| Plan executing | Select tools by the current plan step intent, then include `update_plan_step`. |

## Task Routing Matrix

| User intent | First tools | Action tools | Verification tools |
| --- | --- | --- | --- |
| Understand network structure | `get_network_structure`, `find_nodes` | None | `verify_network` |
| Inspect one node | `inspect_node` | None | `verify_network` if upstream errors suspected |
| Inspect parameters | `get_parameter_schema` | None | None |
| Set parameters | `get_parameter_schema` | `set_node_parameter`, `batch_set_parameters` | `inspect_node`, `check_errors` |
| Create a node (1 isolated, no connection) | `run_skill('get_node_card')`, `search_node_types` | `create_node` | `verify_network`, `validate_node_network` |
| Create multiple nodes (2+ or any with connections) — DEFAULT for new graphs | `run_skill('get_node_card')` (for unfamiliar types), `search_node_types` | `create_nodes_batch` (try `dry_run=True` first for unfamiliar types). Never substitute with `create_node` + `connect_nodes`. | `verify_network`, `validate_node_network` |
| Connect nodes | `get_node_connections`, `run_skill('get_node_inputs')`, `suggest_connection` | `preview_node_operation`, `connect_nodes` | `get_node_connections`, `verify_network` |
| Disconnect nodes | `get_node_connections` | `preview_node_operation`, `disconnect_nodes` | `get_node_connections` |
| Create OUT/IN/CTRL/CACHE null | `get_node_connections`, `suggest_connection` | `preview_node_operation`, `create_named_null` | `verify_network`, `inspect_node` |
| Set flags | `inspect_node` | `preview_node_operation`, `set_node_flags` | `inspect_node`, `verify_network` |
| Cook / force-recompute a node (only when the user explicitly asks) | `inspect_node`, `check_errors` | `cook_node` (high risk; may block the UI) | `inspect_node`, `verify_network` |
| Validate network health | `verify_network`, `validate_node_network` | None | None |
| Review a visual result | `verify_network`, `get_geometry_summary`, relevant material/USD skills | None | `visual_review` when the current model supports vision |
| Layout nodes | `run_skill('get_node_positions')`, `get_network_structure` | `layout_nodes` | `run_skill('get_node_positions')` |
| Make a network box | `run_skill('get_node_positions')`, `run_skill('list_network_boxes')` | `create_network_box` | `run_skill('list_network_boxes')` |
| Find documentation | `run_skill('get_node_card')`, `search_local_doc`, `get_houdini_node_doc`, `web_search` when enabled | None | None |
| Use skills | `list_skills` | `run_skill` | Tool-specific read-only checks |
| Execute code or shell | Ask whether code/shell is truly needed | `execute_python`, `execute_shell` | Inspect output, do not call unrelated scene checks |
| Save or undo | Confirm explicit file intent | `save_hip`, `undo_redo` | Use scene summary only if relevant |

## Node Operation Details

### Connections

Use `get_node_connections` to see occupied input slots and existing output consumers. Use `suggest_connection` when the destination has multiple inputs or unknown labels. Use `preview_node_operation` before replacing an occupied input or disconnecting an input. Then call `connect_nodes` or `disconnect_nodes`.

### Parameters

Use `get_parameter_schema` before setting a parameter by name. It captures labels, tuple size, default values, and menu token/label mapping. Use `set_node_parameter` after schema inspection. Use `batch_set_parameters` only when multiple parameters on the same node need to change together.

### Named Nulls

Use `create_named_null` for semantic output/input/control/cache nulls. Prefer names with `OUT_`, `IN_`, `CTRL_`, or `CACHE_`. If the upstream node is known, include `connect_from`; otherwise create the null without wiring and validate the network afterwards.

### Flags

Use `set_node_flags` for display, render, bypass, template, lock, select, or current flags. Preview flag changes when the current display/render state is not known.

### Layout

Use `layout_nodes` only for explicit layout requests or new nodes created by the current operation. Connection tools should not rearrange existing hand-laid networks.

## Search Scope

Use `find_nodes` when the user gives a name, type, or broad root path. Use `get_scene_snapshot` only for planning across a scene region. Use `get_geometry_summary` for SOP geometry counts, bbox, attributes, and groups. Use `capture_viewport` only when visual state matters.

## Safety Notes

- Do not expose high-risk tools for ordinary query, create, parameter, connection, layout, or validation requests.
- Do not escalate from read-only tools to write tools unless the user requested a scene change.
- Do not infer destructive actions from vague wording. Ask for confirmation or use `preview_node_operation` when impact is ambiguous.
- Harness policy remains the final guard for required arguments, path safety, confirmation, and sensitive data filtering.
