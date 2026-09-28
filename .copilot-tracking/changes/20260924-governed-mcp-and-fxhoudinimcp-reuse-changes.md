<!-- markdownlint-disable-file -->
# Release Changes: Governed MCP and fxhoudinimcp Reuse

**Related Plan**: 20260924-governed-mcp-and-fxhoudinimcp-reuse-plan.md
**Implementation Date**: 2026-09-24

## Summary

Implementation is in progress, beginning with the external MCP baseline and governance bypass characterization.

## Changes

### Added

- `docs/adr/fxhoudinimcp-reference-baseline.md` - Pins the upstream release, commit, license, advertised surface, and selectively studied components.
- `docs/adr/external-mcp-governance-boundary.md` - Records the legacy bypass surface and the accepted trusted-context, HITL, thread, error, audit, and shutdown contracts.
- `tests/test_external_mcp_server.py` - Characterizes arbitrary Python schema exposure and direct `hou_core` dispatch in the legacy external MCP server.
- `houdini_agent/utils/mcp/external_adapter.py` - Adds a narrow fail-closed external execution boundary over Registry authorization and the shared GovernedToolExecutor.
- `tests/test_external_mcp_adapter.py` - Covers trusted context, allowlist, Registry denial, Harness confirmation failure, patched retries, sanitization, and metadata-only audit.
- `tests/test_geometry_pagination.py` - Covers bounded point/primitive pagination, attribute and group filters, output selection, missing attributes, next cursors, and payload-size truncation.
- `tests/test_usd_inspection.py` - Covers bounded USD prim attributes, metadata, prim stack, resolved material binding, missing prim/pxr degradation, and the LOP stage handler.
- `tests/test_pdg_inspection.py` - Covers TOP graph summaries, scheduler facts, state counts, paginated work items, bounded attributes/output files, failed-item metadata, and missing-PDG degradation.
- `tests/houdini_external_mcp_mutations_smoke.py` - Adds a real-Houdini conditional smoke for create/set/connect verification, Manual cook guard, and actual connection undo.
- `houdini_agent/utils/mcp/operations.py` - Adds a bounded session-owned async operation registry for future TOP cook lifecycle handling.
- `tests/test_external_mcp_operations.py` - Covers operation ownership, valid state transitions, timeout-not-cancelled semantics, and bounded terminal eviction.

### Modified

- `.copilot-tracking/plans/20260924-governed-mcp-and-fxhoudinimcp-reuse-plan.md` - Reassesses Phase 4 as a tiered write-capability rollout, prioritizing three reversible atomic scene edits and requiring per-tool confirmation binding, path scope, post-write verification, and explicit default-off exposure.
- `.copilot-tracking/plans/20260924-governed-mcp-and-fxhoudinimcp-reuse-plan.md` - Removes Takes from scope and narrows P4D to governed USD/LOP graph editing before any direct layer authoring.
- `houdini_agent/core/agent_runner.py` - Replaces shared pending-confirmation attributes with per-request queues so concurrent internal and external confirmations cannot overwrite each other.
- `houdini_agent/ui/ai_tab.py` - Connects governed external MCP mutations to the existing Houdini inline confirmation panel.
- `houdini_agent/utils/mcp/external_adapter.py` - Forces every externally initiated mutating tool through confirmation even if the base policy returns allow.
- `houdini_agent/utils/tool_registry.py` - Marks only `create_node`, `set_node_parameter`, and `connect_nodes` as external MCP write candidates while leaving the default allowlist read-only.
- `houdini_agent/utils/mcp/server.py` - Registers readonly tools in Ask mode and mutating tools in Agent mode with per-wrapper mode capture.
- `config/external_mcp_manifest.json` - Adds the three normal-risk mutating candidates to the deterministic capability baseline without enabling them by default.
- `tests/test_external_mcp_adapter.py`, `tests/test_external_mcp_server.py`, and `tests/test_tool_registry.py` - Cover mandatory mutation confirmation, read/write mode isolation, and governed write-candidate metadata.
- `houdini_agent/utils/mcp/settings.py` - Adds default-empty `mcp_write_node_roots`; invalid relative or traversing roots fail closed.
- `houdini_agent/utils/mcp/external_adapter.py` - Restricts mutating node paths to configured roots and requires external `create_node` calls to provide an explicit parent path.
- `houdini_agent/utils/mcp/client.py` - Returns bounded structured verification for created nodes, applied parameter values, and actual connection endpoints, using `applied_unknown` when readback is inconclusive.
- `tests/test_external_mcp_mutation_verification.py` - Covers verified create/set/connect results and inconclusive connection readback without parsing localized messages.
- `houdini_agent/utils/mcp/client.py` - Adds hard limits and bounded post-write verification to `create_nodes_batch` without making it externally visible.
- `tests/test_external_mcp_mutation_verification.py` - Covers batch node/connection/parameter limits before mutation and bounded batch verification.
- `houdini_agent/utils/tool_registry.py`, `houdini_agent/utils/mcp/external_adapter.py`, and `houdini_agent/utils/mcp/client.py` - Expose rename, explicit-subset layout, and restricted bypass/template/lock flag mutations with per-tool argument boundaries and bounded post-write verification while keeping copy and display/render/select/current changes unavailable.
- `houdini_agent/utils/mcp/__init__.py` - Loads lazy `server` and `hou_core` submodules through `importlib.import_module` so package attribute resolution cannot recursively re-enter `__getattr__`.
- `tests/test_external_mcp_adapter.py` and `tests/test_import_smoke.py` - Cover node-modification admission boundaries and the public lazy `hou_core` import regression.
- `houdini_agent/core/harness_engine.py` - Audits `applied_unknown` writes as `verification_inconclusive` while preserving the fact that the mutation handler completed, without logging verification values or paths.
- `tests/test_harness_execution_boundary.py` - Covers privacy-safe audit classification for inconclusive post-write verification.
- `tests/test_external_mcp_adapter.py` - Proves shutdown allows an already-started call to reach a truthful terminal result while rejecting all follow-up calls.
- `houdini_agent/utils/mcp/settings.py` - Adds disabled-by-default loopback-only governance settings with an explicit health-only allowlist and strict call/concurrency limits.
- `houdini_agent/utils/mcp/server.py` - Refuses startup and reports a structured stopped state when governance configuration is invalid.
- `houdini_agent/utils/mcp/server.py` - Registers only the governed health surface by default and refuses executable allowlists when no governed adapter is configured.
- `houdini_agent/utils/mcp/server.py` - Derives dynamic FastMCP call signatures from explicitly visible Registry JSON schemas and removes the legacy direct `hou`/`hou_core` tool source.
- `houdini_agent/utils/tool_registry.py` - Adds default-off `external_mcp_visible` metadata so configuration alone cannot expose a tool.
- `houdini_agent/utils/tool_registry.py` - Explicitly exposes only `get_network_structure` and `read_selection` as the first governed read-only external tools.
- `houdini_agent/utils/mcp/settings.py` - Adds the first two governed read-only tools to the default allowlist while retaining explicit high-risk denials.
- `houdini_agent/utils/mcp/external_adapter.py` - Enforces per-session call totals and non-blocking concurrency limits before execution.
- `houdini_agent/utils/mcp/capabilities.py` - Generates a stable metadata-only external tool manifest from Registry visibility and dispatcher facts.
- `houdini_agent/utils/mcp/external_adapter.py` - Uses manifest long-running classification to enforce a separate long-task concurrency limit.
- `houdini_agent/ui/ai_tab.py` - Builds one production manifest shared by FastMCP schema registration and adapter resource governance.
- `tests/test_external_mcp_capabilities.py` - Verifies manifest filtering, stable ordering, required fields, and exclusion of arguments and user data.
- `scripts/generate_external_mcp_manifest.py` - Generates or checks the committed manifest using AST extraction without importing Houdini runtime modules.
- `config/external_mcp_manifest.json` - Commits the deterministic external tool capability baseline for drift detection.
- `houdini_agent/utils/mcp/__init__.py` - Lazily exports runtime client and server APIs so pure settings and capability tooling do not load the network stack.
- `houdini_agent/utils/mcp/capabilities.py` - Reports bounded runtime health from Houdini, SDK, executor, handler, optional feature, and minimum-version facts without executing tools.
- `houdini_agent/utils/mcp/external_adapter.py` - Exposes structured session information and runtime capabilities from trusted server-owned context.
- `houdini_agent/utils/mcp/server.py` - Registers read-only `session_info` and `capabilities` diagnostics and makes health accurately report degraded state.
- `houdini_agent/utils/mcp/server.py` - Compares manifest and runtime capabilities before registration, hiding tools with missing handlers, features, or host versions.
- `houdini_agent/utils/mcp/capabilities.py` - Classifies connection state as not started, SDK missing, Houdini unavailable, executor blocked/shutdown, capability missing, or connected.
- `houdini_agent/ui/ai_tab.py` - Injects the existing Registry, Harness policy, main-thread executor path, trusted owner identity, and append-only session audit into the external MCP adapter.
- `houdini_agent/core/main_window.py` - Stops the external server, clears its adapter, and shuts down the main-thread executor when the owning window closes.
- `tests/test_harness_execution_boundary.py` - Verifies external MCP Houdini calls reuse the existing main-thread execution path.
- `houdini_agent/utils/mcp/client.py` - Adds a shared read-only geometry pagination implementation with point and primitive handlers, a 500-element page cap, and a 256 KiB payload budget.
- `houdini_agent/utils/ai_client.py` - Adds `get_geometry_points` and `get_geometry_primitives` schemas for precise bounded SOP inspection.
- `houdini_agent/utils/tool_registry.py` - Marks both pagination tools Ask-safe, readonly, low-risk, non-mutating, and explicitly external-MCP-visible.
- `houdini_agent/utils/mcp/settings.py` - Adds the bounded geometry readers to the explicit default external MCP allowlist.
- `config/external_mcp_manifest.json` - Updates the deterministic capability baseline for the two geometry readers.
- `tests/test_tool_registry.py` and `tests/test_external_mcp_server.py` - Lock the new tools' governance metadata and default allowlist contract.
- `houdini_agent/utils/usd_inspection.py` - Adds a Houdini-independent, read-only USD prim inspector with delayed `pxr` loading, entry caps, and a 256 KiB payload budget.
- `houdini_agent/utils/mcp/client.py` - Adds the `get_usd_prim_info` LOP stage adapter and core dispatcher entry.
- `houdini_agent/utils/ai_client.py` - Adds the bounded `get_usd_prim_info` schema for attributes, metadata, prim stack, and resolved material binding.
- `houdini_agent/utils/tool_registry.py` - Marks USD prim inspection readonly, Ask-safe, external-visible, and dependent on the `pxr` runtime feature.
- `houdini_agent/utils/mcp/settings.py` and `config/external_mcp_manifest.json` - Add the USD reader to the explicit allowlist and capability baseline so hosts without `pxr` hide it automatically.
- `houdini_agent/utils/usd_inspection.py` - Adds bounded stage layer-stack inspection and bounded `Usd.PrimCompositionQuery` arc summaries alongside prim-stack data.
- `houdini_agent/utils/ai_client.py` and `houdini_agent/utils/mcp/client.py` - Add the read-only `get_usd_layer_stack` schema, LOP adapter, and dispatcher entry.
- `houdini_agent/skills/inspect_lop_stage.py` - Reuses the shared layer inspector while preserving its existing root/session/sublayer result fields.
- `houdini_agent/utils/tool_registry.py`, `houdini_agent/utils/mcp/settings.py`, and `config/external_mcp_manifest.json` - Govern and capability-gate the layer-stack reader with the same explicit `pxr` boundary.
- `houdini_agent/utils/pdg_inspection.py` - Adds Houdini-independent, read-only TOP graph, work-item pagination, and failed-item metadata inspectors with delayed `pdg` loading and payload limits.
- `houdini_agent/utils/ai_client.py` and `houdini_agent/utils/mcp/client.py` - Add `get_top_network_status`, `list_top_work_items`, and `get_top_errors` schemas, Houdini node adapters, and dispatcher entries.
- `houdini_agent/utils/tool_registry.py`, `houdini_agent/utils/mcp/settings.py`, and `config/external_mcp_manifest.json` - Mark all TOP readers Ask-safe, readonly, external-visible, and gated by the optional `pdg` feature.
- `houdini_agent/utils/mcp/external_adapter.py` - Adds a permanent shutdown latch and rejects new calls before policy/handler dispatch when the adapter is stopped or the main-thread executor is blocked, shut down, or unreadable.
- `houdini_agent/utils/mcp/server.py` - Shuts down the adapter before waiting for the HTTP server thread and refuses to restart with a stopped adapter.
- `tests/test_external_mcp_adapter.py` and `tests/test_external_mcp_server.py` - Cover stopped adapter calls, blocked/shutdown executors, stop ordering, and stopped-adapter restart rejection.
- `tests/houdini_domain_readers_smoke.py` - Creates temporary SOP, LOP, and TOP fixtures under real hython and validates geometry pagination, USD layer/prim inspection, and PDG graph inspection with explicit skip results for unavailable domains.

### Real Houdini Validation

- Host: Houdini `21.0.596` via bundled `hython.exe`.
- Geometry: passed against `/obj/mcp_smoke_geo/box1` with 8 points and bounded pagination.
- USD: passed against `/stage/mcp_smoke_stage` with a 13-layer composed stack.
- PDG: passed against `/obj/mcp_smoke_topnet/generator1` with a live graph context.
- External mutation candidates: passed on Houdini `21.0.596` for `create_node`, `set_node_parameter`, and `connect_nodes`; verified actual node path/type, parameter value, connection endpoint, default Manual guard, explicit Auto update preservation, and `hou.undos.performUndo()` restoration.
- Shutdown semantics: concurrent test proves an already-started call reaches its truthful result while calls arriving after the shutdown latch are rejected.
- Remaining interactive validation: Houdini panel confirmation and external MCP HTTP client transport. The configured Rez Python lacks `fastmcp`, so transport validation was not simulated with an untracked dependency install.
- Batch LOP finding: real Houdini testing proved one `performUndo()` removes the batch connection but leaves both created LOP nodes, so `create_nodes_batch` remains internal until transaction recovery is designed.
- Node modification candidates: Houdini `21.0.596` passed verified rename, two-node subset grid layout without moving an unlisted node, restricted bypass mutation, and unchanged display/render flags; the initial layout recursion was traced to the MCP package lazy-import implementation rather than HOM layout behavior.
- `.copilot-tracking/plans/20260924-governed-mcp-and-fxhoudinimcp-reuse-plan.md` - Marks the upstream baseline and external MCP policy configuration tasks complete.

### Removed

- `houdini_agent/utils/mcp/server.py` - Removes legacy arbitrary Python execution, direct Houdini operations, flipbook resources, and the independent decorator tool set.