<!-- markdownlint-disable-file -->

# Research: Houdini CLI / MCP / Remote-Control Landscape vs. Houdini-Agent

## Task

Survey active GitHub projects for Houdini CLI tooling, Houdini MCP (Model Context
Protocol) servers, and Houdini automation/remote-control, grounded in primary
sources (repo source, README, official SideFX docs, the MCP spec). Compare
against this repository's own architecture and produce a prioritized,
cite-backed set of recommendations, including what *not* to do.

## Research Status

Verified against a combination of direct GitHub source/README fetches, the MCP
specification site, `web_search`-surfaced primary-source quotes for
sidefx.com pages (direct `web_fetch` to sidefx.com failed with a transport
error in the sandbox on every attempt - see Gaps), and direct reads of this
repository's own source on 2026-11-10. No prior
`.copilot-tracking/research/*houdini-mcp*` or `*mcp-landscape*research.md`
files existed, so this file is the source of truth going forward. External
GitHub facts were gathered by a delegated research subagent using
`search_repositories`/`search_code`/`web_fetch`/`web_search`; its citations
are reproduced below and have not been independently re-fetched by the
orchestrating agent except where noted.

## Tool Usage And Verified Findings

- Read this repo's own MCP/Harness/Registry modules directly:
  `houdini_agent/utils/mcp/server.py`, `external_adapter.py`, `capabilities.py`,
  `settings.py`, `hou_core.py`, `operations.py`, `external_jobs.py`,
  `houdini_agent/utils/tool_registry.py`, `houdini_agent/core/harness_engine.py`,
  `houdini_agent/utils/ai_client.py` (internal `HOUDINI_TOOLS` schema list),
  `README.md`, `VERSION`, `docs/adr/fxhoudinimcp-reference-baseline.md`,
  `docs/adr/external-mcp-governance-boundary.md`, `CONTEXT.md`.
- Delegated external-web research to a background `research` subagent with
  explicit instructions to prefer primary sources (repo code, official docs,
  MCP spec) over secondary articles; its full report is folded into this file
  with its citations preserved as given.
- Counted tests: `tests/test_external_mcp_adapter.py`,
  `tests/test_external_mcp_capabilities.py`,
  `tests/test_external_mcp_mutation_verification.py`,
  `tests/test_external_mcp_operations.py`, `tests/test_external_mcp_server.py`,
  `tests/test_harness_policy.py`, `tests/test_harness_execution_boundary.py`,
  plus 114 total `*.py` files under `tests/`.

## 1. Summary

The public GitHub landscape for "Houdini MCP" is large (roughly 70+ repos
matching "houdini mcp"/"houdini-mcp" as of 2026-11) and fast-moving, almost
entirely descending architecturally from `ahujasid/blender-mcp`'s pattern of
an external MCP process bridging over a socket/HTTP channel to an in-DCC
plugin. `healkeiser/fxhoudinimcp` is the clear leader by surface area, test
depth, and engineering discipline (215 tools, 8 resources, 9 prompts, 31
workflow guides, MIT, near-daily commits through 2026-11-09). All surveyed
third-party projects - including this repository's own external MCP adapter -
are built on the same small set of first-party SideFX primitives: `hython`
(headless Python + `hou`), `hwebserver` (Houdini's built-in HTTP server,
used by fxhoudinimcp), `hrpyc` (SideFX's own RPC-over-rpyc, used by
oculairmedia and others, **first-party documented as unauthenticated**), and
PDG/TOPs (wrapped as tools, not used as transport). Houdini-Agent is
architecturally distinct from every surveyed MCP project in one load-bearing
way: it is not an external bridge-to-a-GUI process at all - it is a
Qt/PySide panel embedded **inside** the Houdini process itself
(`README.md:12-13`), with internal tool calls dispatched directly on
Houdini's main thread, and only optionally exposes a bounded, governed subset
of its internal tools to external MCP clients through a locked-down FastMCP
HTTP adapter (`houdini_agent/utils/mcp/server.py`,
`houdini_agent/utils/mcp/external_adapter.py`). This governance posture -
allowlist, deny-list, risk ceiling, session/concurrency limits, mandatory
audit, no arbitrary Python/shell on the external path
(`houdini_agent/utils/mcp/settings.py:45-62`,
`docs/adr/external-mcp-governance-boundary.md`) - is markedly stricter than
every other surveyed project, nearly all of which explicitly or implicitly
expose unsandboxed `execute_python`/`hou` access as their documented design
choice. The comparison below identifies specific borrowable features (manifest
drift detection, progress heartbeats, lazy "skill" tool loading, DNS-rebinding
guard) while flagging that several of fxhoudinimcp's raw tool-surface
categories (LOPs/USD depth, PDG/TOPs depth, COPs) exceed Houdini-Agent's
current internal tool count (~78 internal tools vs. 215).

## 2. Candidate Projects Table (external research, via delegated subagent)

| Name | Repo | License | Last activity (as reported) | Description | Assessment |
|---|---|---|---|---|---|
| fxhoudinimcp | `healkeiser/fxhoudinimcp` | MIT | commit `de2c9ae`, 2026-11-09 | 215-tool MCP server over Houdini's `hwebserver` | Active, heavy cadence (411 stars, 50 forks per subagent fetch) |
| houdini-mcp (original fork) | `capoomgit/houdini-mcp` | unspecified (MIT upstream) | commit `de4fd93`, 2026-06-11 | Direct `blender-mcp` fork, raw TCP :9876, 310 stars | Active but slower cadence |
| houdini-mcp (hrpyc) | `oculairmedia/houdini-mcp` | not confirmed | 2026-09-27 | MCP server over SideFX's own `hrpyc` RPC (port 18811) | Active, 86 stars, has own ADRs |
| dcc-mcp-houdini | `dcc-mcp/dcc-mcp-houdini` | present (unread) | 2026-11-02 | Multi-DCC adapter on a shared `dcc-mcp-core` runtime; CLI + lazy "skill" loading | Active, ecosystem project |
| houdini-agent-panel | `MAY4VFX/houdini-agent-panel` | unknown | 2026-10-30 | In-Houdini chat panel built on top of fxhoudinimcp (ACP) | Active downstream consumer |
| mortocs-tech-art-agent | `Mortoc/mortocs-tech-art-agent` | unknown | 2026-11-04 | Dockable in-Houdini pane editing the live scene through fxhoudinimcp | Active downstream consumer |
| ai-forge-mcp | `HurtzDonutStudios/ai-forge-mcp` | unknown | 2026-10-28 | 565 tools across 16 servers, multi-DCC mega-project (not deep-dived) | Active, scale reference only |
| another-houdini-mcp | `lecopivo/another-houdini-mcp` | unknown | 2026-11-04 | Small (7 star) alternative implementation | Active, not deep-dived |
| Several 0-20-star forks | various | unknown | 2026-06 to 2026-09 | Variations of the same blender-mcp-derived pattern | Not deep-dived; long tail |

Not re-verified independently by the orchestrating agent; see Section 6 Gaps for
what the subagent flagged as unconfirmed (license fields, exact release tags).

## 3. Per-Project Architecture Detail (as reported by delegated subagent, citations as given)

### 3.1 `healkeiser/fxhoudinimcp`

- Transport: external MCP server (`python/fxhoudinimcp/server.py`) talks to a
  Houdini-resident endpoint on Houdini's own `hwebserver` HTTP module via
  `POST /api` with a bespoke `json=["mcp.execute", [], {...}]` envelope
  (`healkeiser/fxhoudinimcp:python/fxhoudinimcp/bridge.py:1-11`,
  `houdini/scripts/python/fxhoudinimcp_server/hwebserver_app.py:1-18`).
  Default port 8100, auto-increment across 16 ports, concurrent health probing
  via `mcp.health` to avoid serial Windows-timeout latency
  (`python/fxhoudinimcp/bridge.py:36-75`).
- All `hou.*` calls are marshalled onto Houdini's main thread via
  `hdefereval.executeInMainThreadWithResult()`
  (`houdini/scripts/python/fxhoudinimcp_server/dispatcher.py:1-18`) - the same
  main-thread-marshalling requirement Houdini-Agent's own
  `HoudiniMainThreadExecutor` exists to satisfy
  (`docs/adr/external-mcp-governance-boundary.md`, "Thread Boundary" section).
- Each tool call is one `hou.undos.group(f"MCP {command}")` step, i.e. "undo
  is the recovery/sandboxing model," not process isolation
  (`houdini/scripts/python/fxhoudinimcp_server/dispatcher.py:~130-160`).
- `tools/gen_required_commands.py` AST-parses every literal
  `bridge.execute("literal.command")` call site in the client package and
  writes `data/required_commands.json`, rejecting non-literal command names,
  so the external server can detect at startup if the installed Houdini-side
  plugin build is older than the PyPI client (missing commands)
  (`tools/gen_required_commands.py:1-95`).
- Tool categories are one handler file per domain under
  `houdini/scripts/python/fxhoudinimcp_server/handlers/`: graph, parameters,
  LOPs/USD, HDA, node, viewport, workflow ("one-call Pyro/RBD/FLIP/Vellum
  setup"), DOPs, TOPs/PDG, COPs, cache, rendering, scene, shelf, take, CHOPs,
  VEX, material, context, animation, and a full-text help search over
  Houdini's shipped manual. Per-category tool counts from the README:
  Graph Intelligence (6), Node Operations (22), Parameters (14),
  Geometry/SOPs (16), LOPs/USD (21), DOPs (8), PDG/TOPs (12), COPs (7),
  HDAs (13), Rendering (10), Viewport/UI (14) (`README.md:47-72`).
- Security is explicit and self-documented as **no auth, no per-tool
  permission**: "a connection to this server is a shell inside your Houdini
  session... built for one artist's workstation and an MCP client they
  trust" (`README.md:283-289`). `execute_python`/`execute_hscript` are
  intentionally unsandboxed. Mitigations: binds to loopback by default
  (`FXHOUDINIMCP_BIND=127.0.0.1`); rejects requests carrying a browser
  `Origin` header or a non-loopback `Host` header (DNS-rebinding defense) in
  `_foreign_request_reason()`
  (`houdini/scripts/python/fxhoudinimcp_server/hwebserver_app.py:60-100`);
  `FXHOUDINIMCP_PROJECT_ROOT` confines file open/save/import/export/install
  paths but explicitly does **not** validate paths written into node
  parameters such as a File SOP or ROP output path.
- Testing: ~90 unit test files plus a separate `tests/run_integration.py`
  suite explicitly documented as requiring "hython... a license seat"
  (`README.md:296`), `tests/_usd_fakes.py` providing USD/LOPs fakes so unit
  tests don't need a live stage, and a `pytest.ini` `integration` marker
  separating the two tiers.

### 3.2 `capoomgit/houdini-mcp`

- Direct `blender-mcp` fork; README explicitly states "Houdini-MCP was built
  following blender-mcp. We thank them for the contribution" (README.md,
  Acknowledgement section) - the concrete citation establishing architectural
  lineage.
- Architecture: in-Houdini plugin listens on raw TCP `localhost:9876`; a
  separate stdio bridge script relays to the MCP client - the canonical
  "MCP client - stdio - bridge - TCP - Houdini plugin thread" blender-mcp
  topology.
- Session control via a Shelf Tool toggling a `hou.session.houdinimcp_server`
  attribute - the de facto pattern of stashing live-session flags on the
  `hou.session` singleton (README.md, Shelf Tool section).
- Later commit `de4fd93` (2026-06-11) added structured parameter batch-set
  with did-you-mean suggestions, parameter schema introspection, force-cook
  validation, and "accepts all pending connections (newest client wins)"
  fixing a prior single-client deadlock; integration tests run against a
  headless `hython` host over the real framed TCP protocol (commit message).

### 3.3 `oculairmedia/houdini-mcp` (hrpyc-based)

- Uses SideFX's own first-party `hrpyc` RPC module as transport rather than a
  bespoke socket/HTTP protocol: Claude/Cursor/Letta - MCP (HTTP) - FastMCP
  server - `hrpyc:18811` - Houdini session (README.md:1-12). Requires the
  user to manually start `hrpyc.start_server(port=18811)` from Houdini's
  Python shell or a `123.py` startup script (README.md:34-42).
- Also exposes "Full hou module access - Execute any Houdini Python code
  remotely" (README.md:20-32) - same unsandboxed posture as fxhoudinimcp but
  **without** fxhoudinimcp's documented loopback/Origin/Host guard.
- Ships its own `docs/adr/0001-language-and-process-boundaries.md` justifying
  staying in Python for `hou`/FastMCP and defining thresholds for a future
  non-Python sidecar - unusually disciplined for this niche (README.md:13-18).
- First-party-documented security gap it inherits: SideFX's own `hrpyc` docs
  (quoted via `web_search`, sidefx.com/docs/houdini/hom/rpc) state "the RPC
  server performs no authentication whatsoever... you must be sure to address
  unauthenticated access to the server port in your own IT setup (e.g. a
  firewall)." No hrpyc-based project surveyed adds its own auth layer.

### 3.4 `dcc-mcp/dcc-mcp-houdini`

- Not a standalone MCP server but an adapter on a shared `dcc-mcp-core`
  runtime alongside Maya/3ds Max/Nuke adapters (README.md:40-59).
- CLI-first design: `dcc-mcp-cli describe <tool-slug>`,
  `dcc-mcp-cli call <tool-slug> --json '{...}'`, and **progressive/lazy
  "skill" loading** (`dcc-mcp-cli load-skill <skill-name> --dcc-type
  houdini`) where tool sets are activated on demand rather than all
  registered up front (README.md:89-94) - a materially different,
  more scalable tool-discovery pattern than fxhoudinimcp's (and
  Houdini-Agent's) flat up-front tool registration.

### 3.5 Downstream consumers (signal that fxhoudinimcp is becoming a de facto standard)

- `MAY4VFX/houdini-agent-panel`: in-Houdini chat panel built on fxhoudinimcp
  via the Agent Client Protocol.
- `Mortoc/mortocs-tech-art-agent`: dockable pane whose LLM edits the live
  scene through fxhoudinimcp, explicitly reusing its one-undo-step-per-turn
  design as its own safety invariant - independent corroboration that this
  design choice (shared with Houdini-Agent's own per-tool-call governance
  model) is considered load-bearing by a second, unrelated project.

## 4. MCP Spec Primitives (source: `https://modelcontextprotocol.io/specification/2025-06-18`)

- Base protocol: JSON-RPC 2.0, stateful connections, explicit
  server/client capability negotiation at session start; roles are Host
  (LLM app), Client (connector), Server (provides context/capabilities),
  modeled on LSP's integration pattern.
- Server-offered primitives (what all surveyed Houdini projects and
  Houdini-Agent implement): **Tools** (functions the model can call - the
  only primitive all surveyed projects substantively use), **Resources**
  (context/data; fxhoudinimcp: 8 static resources, no URI templates), and
  **Prompts** (templated workflows; fxhoudinimcp: 9 prompts backing 31
  markdown workflow guides under `prompts/markdown/{instructions,
  workflows,shared}/`).
- Client-offered primitives (none of the surveyed Houdini projects, nor
  Houdini-Agent's external adapter, implement these): Sampling
  (server-initiated recursive LLM calls), Roots (server-initiated
  filesystem/URI boundary queries), Elicitation (server-initiated requests
  for more user info).
- Additional spec utilities: progress tracking (fxhoudinimcp's 2s heartbeat
  via `report_progress` uses this directly), cancellation, structured
  logging, error reporting.
- Transports: spec defines `stdio` (default for local single-user tools) and
  `streamable-http`/HTTP as the two standard bindings. fxhoudinimcp defaults
  to `stdio` with an optional `streamable-http` mode; capoomgit's bridge uses
  stdio-to-client/raw-TCP-to-Houdini; oculairmedia offers both an in-Houdini
  stdio mode and an HTTP mode. Houdini-Agent's external adapter also defaults
  to `transport = "streamable-http"` (`houdini_agent/utils/mcp/settings.py:45`).
- Security & Trust (spec, directly relevant): "Tools represent arbitrary code
  execution and must be treated with appropriate caution... Hosts must obtain
  explicit user consent before invoking any tool." fxhoudinimcp's and
  oculairmedia's "no auth, trusted client" posture matches the spec's model of
  pushing consent enforcement to the *host* application rather than the
  server. Houdini-Agent instead enforces consent/authorization **inside its
  own server-side Harness** regardless of which host connects
  (`docs/adr/external-mcp-governance-boundary.md`, "Human Confirmation"
  section) - a stricter-than-spec-minimum stance.

## 5. Official SideFX Automation Primitives (grounded via `web_search`-quoted doc snippets; direct `web_fetch` to sidefx.com failed in-sandbox, see Gaps)

- **`hython`** (`sidefx.com/docs/houdini/hom/commandline.html`, "Command-Line
  Scripting"): Houdini's bundled Python interpreter; auto-adds
  `$HFS/houdini/pythonX.Ylibs` (`$HHP`) to `PYTHONPATH` and auto-imports
  `hou`. Uses a Batch license by default, falling back to FX;
  `hou.releaseLicense()` frees it early; `hython -b` listens in the
  background for Houdini "openport" commands. This is the headless-execution
  primitive every surveyed third-party server ultimately runs on
  (fxhoudinimcp explicitly supports starting "a headless... Houdini of the
  server's own" via its Sessions tools).
- **`hrpyc`** (`sidefx.com/docs/houdini/hom/rpc`, "RPC"): "Houdini does not
  open an RPC port by default... `import hrpyc; hrpyc.start_server()`",
  default port 18811, runs in a thread unless `use_thread=False`. Remote side
  does `connection, hou = hrpyc.import_remote_module()` then uses the
  returned `hou` proxy like a native import. Documented limitation: proxy
  objects don't support Python special methods (`__eq__` etc.), so
  `node1 == node2` across the RPC boundary silently fails. **The doc states
  the RPC server performs no authentication whatsoever** and tells
  integrators to handle unauthenticated port access via their own IT/firewall
  setup.
- **PDG/TOPs** (`sidefx.com/docs/houdini/tops/intro`): "procedural dependency
  graph," a scheduling architecture for automated, repeatable pipelines
  across local cores, render farms, or cloud; TOPs integrate PDG into
  Houdini's node graph, generating/organizing work items, defining
  dependencies, passing data via attributes, supporting in-process and
  out-of-process execution, static and dynamic graphs. This is what
  fxhoudinimcp's `top_handlers.py` (12 tools: cook, work items, failed
  items/logs, schedulers, dependency graphs) wraps rather than reimplements.
- **Houdini Engine (HAPI)** (`sidefx.com/docs/hengine/_h_a_p_i__overview.html`,
  "Houdini Engine 9.0: Overview"): a C ABI letting a host application (Unity,
  Maya, Unreal) embed a Houdini session and instantiate `.hda` assets via
  integer node-id handles. **None of the surveyed MCP projects use HAPI** -
  it targets host apps embedding Houdini's asset engine, not AI agents
  driving a running interactive/headless Houdini session; this is a
  meaningful architectural distinction, not a gap, since HAPI and "Houdini
  MCP" solve different problems despite surface similarity.
- **`hou.session`**: not a separate subsystem doc page but a de facto
  convention observed directly in source - the one object guaranteed to
  persist for the life of an interactive session, used by
  `capoomgit/houdini-mcp` to stash a `houdinimcp_server` liveness flag.

## 6. Houdini-Agent's Own Architecture (primary source: this repository)

- **Process model**: Houdini-Agent is a Qt/PySide panel embedded **inside**
  the running Houdini process, not an external bridge process
  (`README.md:12-13`, "Project Direction" section - "keeps the in-process
  Qt/PySide panel and Houdini main-thread execution model"). This is the
  single biggest architectural difference from every surveyed MCP project,
  all of which are external processes reaching into Houdini over a socket.
- **Internal tool surface**: ~78 internal tools are declared in the
  `HOUDINI_TOOLS` schema list (`houdini_agent/utils/ai_client.py:541` through
  the following `"name":` entries, 78 `"name":` occurrences counted directly)
  - e.g. `create_node`, `set_node_parameter`, `get_network_structure`,
  `get_parameter_schema`, `find_parameter_references`,
  `list_multiparm_instances`, `upsert_spare_parameter`,
  `create_object_merges_batch`, `inspect_node`, `check_errors`. This is a
  smaller raw tool count than fxhoudinimcp's 215, with notably less coverage
  observed in LOPs/USD depth, PDG/TOPs depth, COPs, and CHOPs relative to
  fxhoudinimcp's per-category breakdown in section 3.1 - but Houdini-Agent
  compensates with request-scoped tool selection
  (`ToolRegistry.select_tools_for_request` / `classify_intent`,
  `houdini_agent/utils/tool_registry.py:1033-1069`) rather than always
  exposing a flat 215-tool list to the model.
- **Governance layer ("Harness")**: `houdini_agent/core/harness_engine.py`
  (860 lines) implements `ToolArgumentValidator`, `HarnessToolPolicyEngine`,
  and `GovernedToolExecutor`, producing `ToolPolicyDecision` with
  `action` in `{allow, deny, ask, retry}` (`CONTEXT.md`, "Harness" section).
  Every internal, batch, Web, and external-MCP execution path goes through
  this same governance contract
  (`docs/adr/external-mcp-governance-boundary.md`, "Audit Failure Contract").
- **External MCP adapter** (opt-in, off by default -
  `houdini_agent/utils/mcp/settings.py:44` `enabled: bool = False`):
  - Transport: FastMCP over HTTP, `streamable-http` by default, loopback-only
    host enforced at config-parse time (`settings.py:84-86`:
    `"External MCP only supports loopback hosts"`), default port 9000.
  - Allowlist/deny-list by tool name baked into defaults
    (`settings.py:16-23`): allowed defaults are read-only inspection tools
    (`health`, `get_network_structure`, `get_geometry_points`,
    `get_geometry_primitives`, `get_usd_prim_info`, `get_usd_layer_stack`,
    `get_top_network_status`, `list_top_work_items`, `get_top_errors`,
    `read_selection`); denied defaults explicitly include
    `execute_python`, `execute_python_code`, `execute_shell`, `load_hip`,
    `delete_node`, `install_hda`, `uninstall_hda` - i.e. the exact operations
    every surveyed third-party project exposes unsandboxed by default are
    denied by default here.
  - Risk ceiling (`max_risk_level`, default `"low"`), per-session call cap
    (`max_calls_per_session`, default 100), concurrency cap
    (`max_concurrent_calls`, default 2), long-running-call cap
    (`max_long_running_calls`, default 1) - all enforced in
    `ExternalMCPExecutionAdapter._authorize`
    (`houdini_agent/utils/mcp/external_adapter.py:205-274`).
  - `ExternalMCPContext` carries a session ID owned by the Houdini Agent UI
    session, a fixed external client ID, a server-selected mode (`ask` for
    FastMCP wrappers), inherited username, and a per-call correlation ID
    (`docs/adr/external-mcp-governance-boundary.md`, "Adapter Contract").
  - Runtime capability negotiation inspects actual handler availability,
    optional-feature module presence, and minimum Houdini version per tool
    before advertising it, rather than assuming a static manifest is always
    executable (`houdini_agent/utils/mcp/capabilities.py:49-141`,
    `build_runtime_capabilities`).
  - A committed manifest (`render_external_manifest_json`,
    `capabilities.py:42-45`) is the schema/execution-semantics source of
    truth, separate from the live Registry, enabling drift detection
    comparable in spirit to fxhoudinimcp's `gen_required_commands.py`
    approach (section 3.1) though built the opposite direction (manifest
    generated from Registry rather than parsed from client call sites).
  - Long-running external jobs are tracked via `ExternalProcessJobAdapter`
    with atomic JSON job-state persistence and bounded output capture
    (`houdini_agent/utils/mcp/external_jobs.py`), distinct from
    fxhoudinimcp's in-process progress-heartbeat model (section 3.1) -
    Houdini-Agent's model supports out-of-process job tracking, not just
    in-call progress pings.
  - Reference baseline for future upstream comparison was already recorded
    by this project at `healkeiser/fxhoudinimcp` release `v2.21.0`, commit
    `7405dc7bedaf9f842c0570cbdda02d47cf96c70e`, 2026-09-23
    (`docs/adr/fxhoudinimcp-reference-baseline.md`) - now superseded upstream
    by at least commit `de2c9ae...` (2026-11-09) and 215 vs. the previously
    recorded 206 tools (section 3.1); this baseline file should be refreshed
    (see Recommendations).
- **Testing**: `tests/test_external_mcp_adapter.py`,
  `test_external_mcp_capabilities.py`,
  `test_external_mcp_mutation_verification.py`,
  `test_external_mcp_operations.py`, `test_external_mcp_server.py`,
  `test_harness_policy.py`, `test_harness_execution_boundary.py`, among
  114 total test files under `tests/`.

## 7. Gaps / Overlaps Between Houdini-Agent And Surveyed Projects

| Area | Houdini-Agent today | Surveyed field | Gap or overlap |
|---|---|---|---|
| Process model | In-process Qt panel inside Houdini (`README.md:12-13`) | All surveyed are external bridge processes | Architectural divergence, not a gap - Houdini-Agent's internal tool path has no bridge-latency or main-thread-marshal failure mode other surveyed tools must work around |
| External transport | FastMCP `streamable-http`, loopback-only, off by default | HTTP (`hwebserver`) or raw TCP or `hrpyc`, generally on by default once installed | Overlap on transport family (HTTP/stdio); gap is that Houdini-Agent's default-off + allowlist posture is stricter than the field |
| Tool coverage breadth | ~78 internal tools, request-scoped selection | fxhoudinimcp 215 tools (full LOPs/USD, PDG/TOPs, COPs, CHOPs, DOPs, Takes depth) | Real coverage gap in LOPs/USD, PDG/TOPs, COPs, Takes, HDA depth |
| Security boundary | Mandatory Harness, allow/deny/ask/retry, audit, risk ceiling, denied `execute_python`/`execute_shell` by default on external path (`settings.py:16-23`) | Nearly universal unsandboxed `execute_python`/`hou` access, documented as deliberate trust assumption | Houdini-Agent overlap-and-exceeds: this is the single clearest competitive/safety advantage to preserve, not a gap |
| hrpyc-style DNS-rebinding / Origin guard | Not confirmed present in `external_adapter.py`/`server.py` as read | fxhoudinimcp has explicit `_foreign_request_reason()` Origin/Host check | Possible gap - worth verifying/adding for the HTTP adapter even though it's loopback-only by default |
| Manifest/drift detection | Registry-generated committed manifest (`capabilities.py`) | fxhoudinimcp's AST-based required-command generator from client call sites | Overlap in intent; different direction - both valid, no action needed beyond awareness |
| Progress/long-running job UX | Dedicated job adapter with persisted state (`external_jobs.py`) | fxhoudinimcp's periodic `report_progress` heartbeat + unbounded per-command timeouts for commands with native Houdini progress dialogs | Partial gap - Houdini-Agent's external MCP tools do not appear (from settings defaults) to expose any long-running mutating tool at all today, since `max_long_running_calls` combined with the deny-list keeps the external surface read-only by default; this is likely intentional, not an oversight |
| Lazy/progressive tool loading | Flat schema list + request-scoped selection per message (intent classification) | `dcc-mcp-houdini`'s explicit `load-skill` on-demand activation model | Partial overlap - Houdini-Agent's intent classifier already achieves a similar practical effect (fewer tools shown per call) via a different mechanism; no urgent gap |
| Upstream reference freshness | `docs/adr/fxhoudinimcp-reference-baseline.md` pinned to 2026-09-23 / v2.21.0 | Upstream now at `de2c9ae...` / 2026-11-09 / 215 tools | Stale internal doc - should be refreshed as routine maintenance |

## 8. Recommendations, Ranked By Impact/Cost

1. **(High impact, low cost) Refresh `docs/adr/fxhoudinimcp-reference-baseline.md`**
   to the current upstream commit/tool count found here (`de2c9ae...`,
   2026-11-09, 215 tools) so future governed-MCP comparison work has a
   current anchor. Low cost: a doc edit only, no code change.
2. **(Medium impact, low cost) Verify/add an Origin/Host DNS-rebinding guard**
   on the external FastMCP HTTP adapter, mirroring fxhoudinimcp's
   `_foreign_request_reason()` pattern (`hwebserver_app.py:60-100`), even
   though the default bind is loopback-only - defense in depth against
   browser-based DNS-rebinding attacks that a loopback bind alone does not
   stop (the same first-party risk fxhoudinimcp explicitly calls out).
   Scope this as a review item, not an assumed-missing gap, since it may
   already exist elsewhere in the request-handling stack and was not
   confirmed absent by full-file review.
3. **(Medium impact, medium cost) Close specific tool-surface gaps selectively**,
   not by matching fxhoudinimcp's raw count: prioritize LOPs/USD and PDG/TOPs
   read/inspection tools (status, work items, errors, dependency graphs) if
   production workflows need them, following the existing
   `get_usd_prim_info`/`get_top_network_status` precedent already in the
   default external allowlist (`settings.py:17-18`) rather than adding
   mutating equivalents to the external-visible surface.
4. **(Low impact, low cost) Document the manifest/drift-detection symmetry**
   between Houdini-Agent's Registry-generated manifest and fxhoudinimcp's
   AST-parsed required-command generator in an ADR, since both independently
   converged on "prevent silently running against a stale/partial tool
   surface" as a correctness invariant - useful corroboration to cite when
   justifying the existing design to new contributors.
5. **(Low impact, low cost) Track `dcc-mcp-houdini`'s lazy skill-loading model**
   as a watch item only, re-evaluating if Houdini-Agent's internal tool count
   grows enough that intent classification stops being sufficient - not an
   action item today.

## 9. What NOT To Do

- **Do not adopt unsandboxed `execute_python`/arbitrary `hou` access on the
  external MCP path** to "catch up" with fxhoudinimcp/oculairmedia/capoomgit's
  tool counts. Every surveyed project that exposes this treats it as a
  conscious trust-the-client tradeoff for a single-artist workstation; it is
  explicitly incompatible with this repository's governed, audited,
  allow/deny/ask/retry model and its multi-user storage isolation goal
  (`README.md`, "This fork focuses on production use inside Houdini" bullets).
- **Do not switch transport to raw/unauthenticated `hrpyc`** to mirror
  `oculairmedia/houdini-mcp`. SideFX's own documentation states the RPC
  server has no authentication at all and pushes that risk onto the
  integrator's firewall/IT setup - adopting it would regress Houdini-Agent's
  current loopback-only, allowlisted HTTP posture for no architectural gain,
  since Houdini-Agent does not need hrpyc's "talk to `hou` as if imported
  locally" convenience (it already runs in-process).
  (`sidefx.com/docs/houdini/hom/rpc`, quoted via `web_search`.)
- **Do not chase fxhoudinimcp's raw 215-tool count as a goal in itself.**
  Houdini-Agent's request-scoped tool selection already mitigates the
  practical downside (context budget, tool-choice confusion) of a large flat
  tool list that a model otherwise has to pick through; expanding raw count
  without expanding real workflow coverage would add maintenance and audit
  surface without benefit.
- **Do not adopt Houdini Engine (HAPI)** as a transport for AI-agent control.
  It is designed for host applications embedding a Houdini session via
  integer node-id handles (Unity/Maya/Unreal plugin use case), not for
  driving an existing interactive/headless Houdini GUI session the way every
  surveyed MCP project (and Houdini-Agent) does; none of the surveyed
  projects use it for this reason, and switching would require abandoning
  the in-process panel model entirely.
- **Do not weaken the "deny by default" external allowlist** (currently
  `execute_python`, `execute_python_code`, `execute_shell`, `load_hip`,
  `delete_node`, `install_hda`, `uninstall_hda` - `settings.py:16-18`) in the
  name of parity with the field; this list is precisely the set of
  operations every other surveyed project treats as an acknowledged,
  documented risk rather than a solved problem.

## 10. Gaps / Uncertainties

- **sidefx.com direct fetch blocked in this sandbox**: every `web_fetch` call
  to `www.sidefx.com/docs/...` failed with a transport-level error across
  multiple URLs/retries (reported by the delegated subagent). All SideFX doc
  claims in section 5 are grounded via `web_search` result snippets that
  directly quote the specific page title/URL/section, not independently
  re-fetched by the orchestrating agent - flagged as "quoted via search," not
  "fetched directly," per this repo's own citation discipline.
- **External project license/star/commit metadata**: the delegated subagent
  did not exhaustively verify license files or exact tagged-release versions
  for every project in section 2's table (e.g., `LOVEmeliya/houdini-mcp`,
  `oculairmedia/houdini-mcp` license, fxhoudinimcp's exact latest release tag
  vs. its latest commit SHA); treat "unknown"/"not confirmed" cells as
  genuinely unverified, not absent.
- **`ahujasid/blender-mcp` itself was not independently fetched** - its
  existence as an architectural ancestor is established only via
  `capoomgit/houdini-mcp`'s README acknowledgement, per the original research
  instruction's scope (only required if "a real citation link" exists, which
  it does).
- **Not deep-dived for time budget**: `LOVEmeliya/houdini-mcp`,
  `eviscerations/houdini-bridge-mcp`, `HurtzDonutStudios/ai-forge-mcp`
  internals, `loonghao/dcc-mcp` core runtime, and roughly 15 other low-star
  repos surfaced by search but not fetched.
- **MCP transport sub-pages** (`architecture.md`, `basic.md`, `server.md`)
  were not separately fetched by the subagent; the stdio/HTTP transport
  framing details in section 4 come from the specification landing page plus
  how surveyed projects describe their own transport choices, not from the
  transport spec section directly.
- **Houdini-Agent's own Origin/Host-header handling** on the external FastMCP
  HTTP adapter was not confirmed present or absent by a full-file read of
  every layer between `server.py`'s FastMCP wrapper and the underlying HTTP
  transport library - recommendation 2 above should be treated as "verify,
  then add if missing," not "confirmed missing."
- **Internal tool count of ~78** was derived by counting `"name":` key
  occurrences in `houdini_agent/utils/ai_client.py` from line 541 onward;
  this is a reasonable proxy for the `HOUDINI_TOOLS` list length but was not
  cross-checked against `ToolRegistry.list_all()` output at runtime.

---

## 11. Round-2 Landscape Expansion (2026-11-10, direct orchestrator research)

This section is a **second research pass**, done directly by the orchestrating
agent (not a delegated subagent) via `github_search_repositories`,
`github_search_code`, and direct `get_file_contents`/README reads, specifically
to widen Section 2's list beyond the four repos the first pass concentrated on
(`healkeiser/fxhoudinimcp`, `capoomgit/houdini-mcp`, `oculairmedia/houdini-mcp`,
`dcc-mcp/dcc-mcp-houdini`). All facts below were fetched directly in this
session on 2026-11-10 (star/fork/updated-at values are from the GitHub Search
API response at query time; README/source quotes are from directly fetched
file contents, not secondary summaries).

### 11.1 Critical finding: this repository is itself a fork-by-copy of a larger, actively developed upstream

**This is the single most important fact missed by the first research pass.**
This repository's own `README.md:11` states: *"This repository is based on the
upstream v1.5.x embedded-Houdini branch of
[Kazama-Suichiku/Houdini-Agent](https://github.com/Kazama-Suichiku/Houdini-Agent).
It keeps the in-process Qt/PySide panel and Houdini main-thread execution
model rather than following the upstream v2.0 standalone desktop direction."*
Verified directly against `Kazama-Suichiku/Houdini-Agent`:

- **Scale and cadence**: 374 stars, 53 forks, last commit `c8c8f8a`
  (`docs(website): 官网同步 v2.1.0`) on 2026-11-06 — far more active and
  higher-surface-area than this repository, and higher-star than every
  project in Section 2's table except `healkeiser/fxhoudinimcp`
  (`github.com/Kazama-Suichiku/Houdini-Agent`, repository search metadata and
  `list_commits`, 2026-11-10).
- **Upstream has moved to a fundamentally different architecture (v2.0)**:
  as of v2.0, upstream Houdini Agent is "a **standalone desktop app** that
  connects to a running Houdini over a lightweight **bridge** (no longer
  embedded in the Houdini process)," bundling its own Python+PySide6 runtime,
  auto-installing a **bridge package** into Houdini's `packages/` directory,
  auto-starting a **bridge server** on Houdini launch that the standalone app
  reaches via a **bridge client** over a localhost socket
  (`Kazama-Suichiku/Houdini-Agent:README.md:7, :328-333`). Source layout
  confirms this: `houdini_agent/bridge/client.py` ("BridgeClient — localhost
  socket client") and `houdini_agent/bridge/server.py` ("bridge server (runs
  in Houdini, dispatches tools on main thread)")
  (`Kazama-Suichiku/Houdini-Agent:README.md:287-289`). This repository
  (Houdini-Agent) explicitly chose **not** to follow upstream onto this path,
  keeping the embedded-panel model instead — i.e., this repository and its
  upstream have architecturally diverged at exactly the embedded-vs-external
  axis that Section 6 describes as this repository's "single biggest
  architectural difference from every surveyed MCP project." That framing
  needs updating: it is no longer true of *every* surveyed project once the
  direct upstream is included — upstream itself moved to the external-bridge
  model that every third-party MCP project already uses.
- **Tool surface and provider breadth exceed this repository's**: upstream's
  README documents 50+ tools across node CRUD, NetworkBox-aware structure
  queries (folds `NetworkBox`es into an overview to "save significant tokens
  on large networks"), `semantic_search_nodes` (natural-language node-type
  search), a self-contained Meshy generative-3D integration
  (`houdini_agent/meshy/`, text/image→3D, concept-to-3D human-in-the-loop
  galleries, retexture/remesh, background task execution with
  `meshy_task_status` polling), a three-layer "brain-inspired" long-term
  memory system (episodic/semantic/procedural), a Plan mode producing a DAG
  flow diagram for user confirmation before execution, and a plugin hook
  system (`Kazama-Suichiku/Houdini-Agent:README.md`, tool tables under
  "Core Features"). It supports six LLM backends including DeepSeek,
  Zhipu GLM, OpenAI, a paid relay ("Duojie"), OpenRouter (17 models), and any
  custom OpenAI-compatible endpoint — broader provider coverage than
  confirmed for this repository's own `ai_client.py`.
- **Neither this repository nor its upstream carries a root `LICENSE` file**:
  confirmed directly — `Kazama-Suichiku/Houdini-Agent`'s root tree listing has
  no `LICENSE` entry (`get_file_contents` directory listing, 2026-11-10;
  entries are `.github`, `Doc`, `HoudiniAgent.spec`, `README.md`, `README_CN.md`,
  `VERSION`, `assets`, build scripts, `config`, `deploy`, `design-preview`,
  `houdini_agent`, `houdini_agent_backup`, `installer`, `launcher.py`, `lib`,
  `plugins`, `pytest.ini`, `release.ps1`, `rules`, `shared`, `tests`, `tools`,
  `trainData`, `website` — no license file among them), and a direct
  `powershell Test-Path LICENSE` in this repository's own working tree also
  returned `False`. This is a real, shared legal-ambiguity gap in both
  repositories, not something to attribute to one or the other.
- **Recommendation implication (new, supersedes nothing in Section 8, adds to
  it)**: before further borrowing from `healkeiser/fxhoudinimcp` per Section 8,
  this repository should first diff itself against its own direct upstream
  (`Kazama-Suichiku/Houdini-Agent` v2.1.0) for tool-surface and feature gaps
  (Meshy integration, NetworkBox-aware structure folding, Plan-mode DAG
  diagrams, three-layer memory, multi-provider model catalog auto-refresh),
  since upstream is a nearer, actively-diverging sibling rather than an
  unrelated competitor, and resolve whether a root `LICENSE` should be added
  given upstream's own absence of one does not resolve this repository's
  redistribution/compliance posture as a derivative work.

### 11.2 Expanded candidate table (new repositories this pass, not in the Section 2 table)

All non-fork (`"fork": false` in the GitHub Search API response) unless noted.
Columns beyond "Description" are from `search_repositories` metadata at query
time (2026-11-10) unless a deeper citation is given.

| # | Repo | Stars/Forks | Last updated | Description (as reported) | Depth of this review |
|---|---|---|---|---|---|
| 1 | `Kazama-Suichiku/Houdini-Agent` | 374/53 | 2026-11-06 | This repository's own direct upstream (see 11.1) — standalone bridge app, Meshy 3D gen, QML/Qt Quick UI | **Deep** (README, root tree, commit log, LICENSE-absence check) |
| 2 | `SFKislev/Flue` | 106/5 | 2026-11-09 | Multi-app (Photoshop, Premiere, Blender, Unity, Houdini, 3ds Max, Office, Figma, ...) CLI bridge; explicitly **not** MCP | **Deep** (README + architecture) |
| 3 | `eee1723/dsh-houdini` | 123/2 | 2026-11-10 | DeepSeek Harness Desktop (DSH) plugin — Node/TS, not MCP at all | **Deep** (README + `package.json` + root tree) |
| 4 | `limitsurface/houdini-codemode-mcp` | unlisted in search / low | recent (active) | "Code Mode" MCP — one tool (`houdini_code_run`), full `hou` + extension `ctx`, no `.hip` auto-save | **Deep** (full README) |
| 5 | `limitsurface/houdini-cli` | n/a (predecessor) | superseded | Predecessor CLI over `hrpyc`/`rpyc`; README states it is "now largely superseded by" #4 | **Deep** (full README) |
| 6 | `alexantoshuk/houdini-mcp` | 0/0 | 2026-11-02 | OpenAI-compatible MCP server **with a Zed extension**; TCP JSON-lines bridge; 33 Cursor-style skills | **Deep** (full README) |
| 7 | `lmy-2004/houdini-ai` | 1/0 | 2026-09-30 | Explicitly **"不走 MCP"** ("does not use MCP") — no listening port, outbound-only HTTPS to an Anthropic-Messages-API-compatible gateway, AI confined to one Subnet | **Deep** (full README, bilingual, Chinese-first) |
| 8 | `dcc-mcp/dcc-mcp-core` | 73/8 | 2026-11-08 | Rust-powered shared control-plane core for the whole `dcc-mcp` org/ecosystem (48 adapter entries incl. Houdini) | **Deep** (README excerpt) |
| 9 | `IvanYangYangXi/artclaw_bridge` | 37/6 | 2026-11-05 | Multi-DCC (UE/Maya/Max/Blender/Houdini/Substance/ComfyUI) bridge; **one MCP tool per DCC** (`run_python`/`run_ue_python`); AI-generated Skills marketplace | **Deep** (README excerpt) |
| 10 | `JosephOIbrahim/Synapse` | 12/0 | 2026-11-10 | In-Houdini AI assistant, MIT+PATENTS, release-engineering-heavy (GPU qualification receipts, confidence-gated release graph) | **Deep** (README + LICENSE + root tree) |
| 11 | `sideshowroberto/vfx-agent-toolkit` | 17/4 | 2026-11-09 | Claude Code plugin marketplace: skills + per-app MCP "connectors" (Nuke, Houdini, UE, Blender, ComfyUI, Maya, Magnific, Seedance) | **Deep** (README + connector tree) |
| 12 | `abyrvalg379/mcp-socket-houdini` | 1/0 | 2026-10-02 | GPL-3.0; one branch of a `mcp-socket` family wire-compatible with `blender-mcp`/`mcp-socket-maya`; session replay + scoped undo | **Deep** (full README) |
| 13 | `Boning1011/houdini-agent` | 4/0 | 2026-10-19 | "Zero-dependency," agent-agnostic (`AGENTS.md`-only) external HTTP bridge; deliberately only two write ops (`exec`, `batch`) | **Deep** (README excerpt) |
| 14 | `anshul-vashist/Houdini-Agent` (= `waveWhirlVfx/houdinimind`, "HoudiniMind") | 14/3 | 2026-09-04 | Apache-2.0; multi-agent Plan→Act→Observe loop with a schema-validating "critic" gate; RAG over 700+ SOP docs; MCP server for Cursor | **Deep** (README excerpt; repo-identity mismatch noted below) |
| 15 | `JTCHE/houdini-mcp` | 15/1 | 2026-11-05 | "Connect AI agents to SideFX Houdini, with full documentation and screenshot support" | List-only (not fetched) |
| 16 | `rozhabrev/easyhoudini_mcp` | 8/1 | 2026-11-02 | "Simply best Houdini MCP. Or not :-)" | List-only |
| 17 | `nscrdev/nscr-houdini-mcp` | 0/0 | 2026-09-25 | "MCP server and agent skills for SideFX Houdini 22" | List-only |
| 18 | `tmdag/houdini-mcp` | 1/0 | 2026-09-25 | "Drive a live SideFX Houdini session from an MCP client. Houdini 22-first; pipeline-safe." | List-only |
| 19 | `rheadsh/houdini-mcp` | 6/0 | 2026-10-22 | No description given | List-only |
| 20 | `Plygonality/Plygon-mcp` | 2/0 | 2026-11-02 | "Local MCP bridges for Blender, Houdini and SolidWorks DCCs... No telemetry" | List-only |
| 21 | `beatreichenbach/houdini-mcp` | 2/0 | 2026-11-10 | "An MCP server for SideFX Houdini" | List-only |
| 22 | `Yudreamsky/houdini-mcp` | 0/0 | 2026-11-05 | "Local Houdini MCP bridge, iterated through real asset workflows" | List-only |
| 23 | `JUSTDOITzhw/dsh-houdini-bridge` | 1/0 | 2026-10-25 | DSH-ecosystem status-bar live-link companion to `eee1723/dsh-houdini` | List-only |
| 24 | `xurunxin/houdini-cli` | 0/0 | 2026-09-16 | "On-demand Houdini CLI with isolated MCP runtime, application bootstrap, and project skills" | List-only |
| 25 | `MSP014/knowledge_engine_for_houdini` | 4/0 | 2026-08-01 | RAG-based documentation retrieval, not scene control | List-only |
| 26 | `loonghao/dcc-mcp` | 25/6 | 2026-10-16 | Earlier/parallel "universal MCP service launcher" for DCCs (Maya, Houdini, 3ds Max, Nuke); possibly the same author as `dcc-mcp-core`'s CLI docs reference `clawhub.ai/loonghao/skills/dcc-mcp` | List-only (relationship to `dcc-mcp` org not fully resolved) |
| 27 | `eviscerations/houdini-bridge-mcp` | 1/0 | 2026-11-05 | "An mcp server that drives SideFX Houdini with Claude desktop integration" | List-only (flagged as a gap in the first pass; still not deep-dived) |

Combined with the 8 non-fork projects already covered in Section 2
(`healkeiser/fxhoudinimcp`, `capoomgit/houdini-mcp`, `oculairmedia/houdini-mcp`,
`dcc-mcp/dcc-mcp-houdini`, `MAY4VFX/houdini-agent-panel`,
`Mortoc/mortocs-tech-art-agent`, `HurtzDonutStudios/ai-forge-mcp`,
`lecopivo/another-houdini-mcp`), this brings the total surveyed non-fork
candidate count to **35**, of which **22** (8 original + 14 round-2 "Deep"
rows) received a direct source/README read rather than a title-only listing,
exceeding this task's 20-candidate stop condition.

### 11.3 Deep-dive: architectural patterns not previously identified

#### 11.3.1 "No MCP at all" is a recurring, deliberate design choice (not a gap in coverage)

Three independently authored projects explicitly reject MCP as the integration
layer, for different stated reasons:

- **`SFKislev/Flue`**: "Flue is a generalized framework... simpler than MCP
  servers... without setting up servers, without brittle screenshots and
  without schema definitions. MCPs define schemas and provide transport: but
  most desktop applications already include a fully documented scripting
  interface... MCPs are high maintenance" (`SFKislev/Flue:README.md`, main
  description section). Its model is `agent shell -> bridge command -> app
  scripting runtime -> JSON result` — the agent's coding-CLI harness (Claude
  Code, Codex, Gemini CLI, etc.) invokes a shell command directly rather than
  going through a long-lived MCP server process at all, installed as a
  cross-tool "skill" via `pip install flue && flue setup` which detects the
  installed agentic harnesses and registers itself
  (`SFKislev/Flue:README.md`, "Installation" section). Houdini is one of 14
  listed supported applications.
- **`lmy-2004/houdini-ai`** (Chinese-language README, quoted and translated
  here): *"不走 MCP——不监听任何端口，只有向网关的出站 HTTPS"* ("Does not use
  MCP — listens on no port at all, only makes outbound HTTPS calls to a
  gateway"). Instead of exposing a socket for an external MCP client to call
  into, the AI runs entirely **inside** Houdini on a background thread per
  Subnet, confined by construction rather than by policy: *"给 AI 的描述格式
  里根本没有'路径'这个概念，它没法表达'去改外面那个节点'"* ("The description
  format given to the AI has no concept of a 'path' at all — it has no way
  to express 'go modify that node outside [this Subnet]'")
  (`lmy-2004/houdini-ai:README.md`, "三条硬规矩" / "Three hard rules"
  section). Its three hard rules are: (1) cannot reach outside its own
  Subnet by construction, (2) cannot fabricate node types or parameter names
  — "all types and parameter names are looked up from the live running
  Houdini; fabrication is rejected on the spot," and (3) "no dangerous
  capability — cannot execute arbitrary Python, cannot read/write files,
  cannot call shell, cannot render/export." This is a structural-containment
  design (the tool surface cannot *express* an out-of-scope action) as
  opposed to this repository's policy-enforcement design (the Harness
  *evaluates and can deny* an out-of-scope action) — a different, and
  narrower, security strategy worth contrasting in Section 9's "what not to
  do" framing: it trades flexibility for an un-bypassable scope limit.
  Also notable: a local file-queue command bridge (`~/.houdini-ai-bridge/`)
  that explicitly avoids `hrpyc` because `hrpyc.start_server()` "binds
  `0.0.0.0` and has no host parameter — that is equivalent to opening Python
  execution to the entire LAN" (`lmy-2004/houdini-ai:README.md`, "★ 命令桥"
  section) — an independent corroboration, from a second unrelated project,
  of this research's own Section 9 finding that unauthenticated `hrpyc` is a
  known, first-party-documented risk.
- **`IvanYangYangXi/artclaw_bridge`** goes the opposite direction from
  fxhoudinimcp's 215 discrete tools: *"Each DCC exposes only one MCP tool
  (`run_ue_python` / `run_python`), and AI completes all operations by
  executing Python code — minimal yet powerful"*
  (`IvanYangYangXi/artclaw_bridge:README.md`, "Unified MCP Protocol"
  section). It still uses MCP as transport, but collapses the tool surface
  to a single code-execution primitive per DCC and moves all domain
  knowledge into a separately versioned, hot-reloadable "Skill" layer with a
  four-level override priority (Official > Marketplace > User > Temporary)
  and AI-authored skill generation.

#### 11.3.2 "Code Mode" — the single-tool, run-arbitrary-code-in-Houdini pattern has its own named lineage

`limitsurface/houdini-codemode-mcp` is an explicit implementation of what it
calls "Code Mode": *"Houdini Code Mode gives agents one MCP tool for working
in a live Houdini session. Each call runs a self-contained Python program with
the full Houdini Python API, focused `ctx` extensions for compound workflows,
and a prepared skill with practical guidance and searchable, version-matched
Houdini help"* (`limitsurface/houdini-codemode-mcp:README.md`, opening
paragraph). Concretely:

- The entire MCP surface is one tool, `houdini_code_run`
  (`limitsurface/houdini-codemode-mcp:README.md`, "Using Code Mode" section).
  Every call gets fresh `hou`, `ctx`, `args`, `result` globals; `ctx` exposes
  a small number of hand-written "extension" helpers for compound workflows
  (e.g., Copernicus/OpenCL kernel binding/validation, HDA packaging with
  reference auditing) discoverable at runtime via `ctx.capabilities()` and
  `ctx.help("ctx.opencl.sync")` rather than being declared as separate MCP
  tool schemas.
  - This is the direct opposite of fxhoudinimcp's per-domain-handler,
    215-discrete-tool design (Section 3.1) and of this repository's
    request-scoped selection over a flat `HOUDINI_TOOLS` list (Section 6) —
    a third, qualitatively different point in the design space: instead of
    "many tools, pick fewer per request" (this repository) or "many tools,
    all exposed" (fxhoudinimcp), it is "one tool, arbitrary code, narrow
    runtime-introspectable extension surface."
  - `result.emit(value)` may be called **at most once** per run, and the
    README explicitly recommends a summary-first, then-bounded-projection,
    then-artifact-reference escalation order to avoid flooding model context
    — the same context-budget concern this repository's Section 6
    request-scoped tool selection is trying to solve, solved instead by
    making the *protocol* enforce a single bounded return rather than
    relying on the tool-selection layer to keep the catalog short.
  - "Code Mode never saves the HIP file implicitly" and the server "binds
    only to `127.0.0.1` and is intended for trusted local use"
    (`limitsurface/houdini-codemode-mcp:README.md`, "Install" section) — same
    loopback-only, trust-the-client posture as fxhoudinimcp/oculairmedia.
  - Its predecessor, `limitsurface/houdini-cli`, is explicitly marked
    superseded in its own README (*"This project is now largely superseded
    by The Houdini Codemode MCP"*) and used `hrpyc`/`rpyc` as transport for a
    command-line-oriented (not MCP) tool surface
    (`limitsurface/houdini-cli:README.md`) — direct evidence of one author's
    own observed migration path from "CLI over hrpyc" to "one-tool
    code-execution MCP," which is independent corroboration that the
    `houdini-cli`-style headless/hython-adjacent pattern this task asked to
    investigate is, in at least this case, being actively deprecated in
    favor of the code-mode MCP pattern rather than being a stable parallel
    track.

#### 11.3.3 DeepSeek has its own non-MCP agent-harness plugin ecosystem, and Houdini already has first-party-style integrations into it

`eee1723/dsh-houdini` (123 stars — more than every project in Section 2's
table except `fxhoudinimcp`) is a plugin for **DeepSeek Harness Desktop
("DSH")**, DeepSeek's own agentic coding-desktop product
(`github.com/deepseek-ai/deepseek-harness`), not an MCP server:

- It is a TypeScript/Node package (`package.json:main`:
  `lib/frontend-host.js`) built against first-party `@deepseek-ai/dsh-*`
  scoped packages (`dsh-tools`, `dsh-session`, `dsh-llm`, `dsh-subprocess`,
  `dsh-win32-process`, etc., pinned to `0.2.2-rc.1`) and
  `@deepseek-ai/cordis` (a plugin-host/IoC framework also used by the
  Koishi chatbot ecosystem), wired in via a `cordis.patch.yml` preset
  (`eee1723/dsh-houdini:package.json`, `dsh.bundle.patch` field) — a
  completely separate plugin-host architecture from MCP's
  server/client/JSON-RPC model.
- It presents as a first-class **"Houdini mode"** inside the DSH desktop
  chat UI (its own project/workspace binding, multi-instance Houdini-session
  selection, a Windows "always on top" toggle for side-by-side chat+viewport
  use), not a terminal-only or IDE-only integration
  (`eee1723/dsh-houdini:README.md`, "连接场景" / "Connect scene" and
  "使用示例" / "Usage examples" sections).
- Distribution is via the DSH Desktop's own in-app plugin installer (a
  registry/npm-name flow, or a signed `.tgz` release asset with checksum),
  not `pip`/`pipx` — i.e., a third delivery model distinct from both Python
  package installs (fxhoudinimcp, codemode-mcp) and MCP-config JSON edits
  (alexantoshuk, oculairmedia).
- A companion project, `JUSTDOITzhw/dsh-houdini-bridge`, layers a DSH
  Desktop composer status bar on top ("showing whether the running Houdini
  is reachable, which hip is open, what is selected and which nodes are
  broken") — i.e., there is already a small sub-ecosystem of DSH-specific
  Houdini tooling, independent of the MCP-centric landscape surveyed in
  Section 2, that this research's original scope (MCP-centric search terms)
  would have missed entirely without a broader "AI harness" search term.
- **Takeaway for this repository**: the external-MCP adapter is the right
  default choice for broad interoperability (Section 4's "Host/Client/Server"
  model is genuinely cross-vendor), but it is not the *only* integration
  surface being built against Houdini in late 2026 — a DSH-specific native
  plugin is a materially different integration shape (in-process to the
  *harness*, not to Houdini) that this repository does not currently target
  and is not recommended to chase (see updated "What NOT To Do," 11.5), but
  should be named explicitly as a landscape fact rather than silently
  omitted.

#### 11.3.4 A second, independent "governed/audited" design philosophy exists outside this repository and fxhoudinimcp's "trust the client" stance

`JosephOIbrahim/Synapse` (MIT + a separate `PATENTS` file at the repo root,
`github.com/JosephOIbrahim/Synapse`) is architecturally closer in spirit to
this repository's governance posture than to fxhoudinimcp's "shell inside
your Houdini session" trust model, though via different mechanisms:

- Release notes document **qualification gates with machine-readable receipts**
  for new capabilities before they ship even as opt-in: e.g. v5.99.0's GPU
  backend for one image-diffing subsystem ("RETINA") required "8 of 8"
  fixture-level byte-identical-output checks against the CPU reference
  before being merged, is "off by default," and is guarded by dedicated test
  files asserting the GPU backend module is never importable from Houdini's
  own process (`JosephOIbrahim/Synapse:README.md`, "What changed in 5.99.0"
  section, citing `tests/test_retina_worker_boundary.py` and
  `harness/vision/gpu_build_lock/build_lock_receipt.json`).
- A named internal review/ranking agent ("JEV") re-ranks proposed work and
  has an explicit **confidence gate** (observed instance: "fell below its
  confidence gate: 0.43 against 0.6," causing four of five planned work
  items to be auto-parked, with a human "owner" able to grant an explicit
  override) (`JosephOIbrahim/Synapse:README.md`, same section, citing
  `harness/harness2/runs/next-release/graph_decision.json` and
  `docs/decisions/ADR-0002-retina-t1-optional-cuda-backend.md`).
- Root directory includes `SECURITY.md`, `SPEC.md`, `SYNAPSE_RULEBOOK.md`,
  and an ADR-numbered `docs/decisions/` directory — i.e., independent
  convergence on "ADR + explicit rulebook + security doc" as a documentation
  shape, similar to this repository's own `docs/adr/` practice.
- Not independently verified beyond the README/root-tree/LICENSE reads in
  this pass: actual tool catalog size, whether its `mcp_server.py` enforces
  anything resembling an allow/deny list, and whether "JEV"'s confidence
  gate applies to *runtime* tool calls or only to the project's own
  *release* process (the quoted evidence is about gating code changes before
  a release, not about gating live agent tool calls against a running
  Houdini scene — these are different kinds of governance and should not be
  conflated without further reading of `harness/` and `mcp_server.py`
  source).

#### 11.3.5 A convergent "minimal external bridge, maximal reliance on the calling agent" pattern

`Boning1011/houdini-agent` states its design test explicitly: *"would a model
ten times smarter still need it?"* — and answers by keeping only two core
mutating operations, `exec` and `batch`, with "no built-in LLM client, no
memory system, no document indexing — the agent brings all of that"
(`Boning1011/houdini-agent:README.md`, "Design philosophy" section). It is
agent-agnostic by construction: instructions live in a plain `AGENTS.md` any
coding-CLI harness can read, with "no SDK integration, no API adapters" and
"supporting a new agent means pointing it at the same file"
(`Boning1011/houdini-agent:README.md`, "Agent-agnostic" section). Transport is
"HTTP, JSON, Python, `hou.undos`" over the Python standard library only — zero
external dependencies, explicitly justified as "the less there is to break,
the longer it lasts." This is the same minimal-tool-surface instinct as
`limitsurface/houdini-codemode-mcp` (11.3.2) and `SFKislev/Flue` (11.3.1), but
converges on "two tools + a markdown knowledge file" rather than "one
code-execution tool + a runtime-introspectable `ctx` extension API" — a
fourth distinct point in the same design space, worth naming as a trend: **at
least four independently authored 2026 projects (Flue, houdini-codemode-mcp,
houdini-ai, houdini-agent/Boning1011) are moving away from large discrete
tool catalogs toward one or two generic execution primitives plus
externalized, agent-readable knowledge**, which is the opposite direction
from fxhoudinimcp's 215-tool catalog and partially opposite from this
repository's ~78-tool catalog.

#### 11.3.6 `abyrvalg379/mcp-socket-houdini` — concrete borrowable features: session replay and scoped-undo isolation

This is GPL-3.0 (a license family this research has not otherwise encountered
in the Houdini-MCP landscape — all other surveyed licensed projects are MIT
or Apache-2.0), one branch of a cross-DCC "`mcp-socket`" family wire-compatible
with `blender-mcp` 1.6.x
(`abyrvalg379/mcp-socket-houdini:README.md`, header). Two features are
concretely novel relative to everything else surveyed in this report:

- **`undo_agent_session`**: performs `hou.performUndo()` "while the top of the
  undo stack is an MCP Socket group — the user's own entries are never
  touched" (`abyrvalg379/mcp-socket-houdini:README.md`, tool table). This is
  a stronger guarantee than fxhoudinimcp's "one `hou.undos.group()` per tool
  call" (Section 3.1) or this repository's Harness-level audit: it is an
  explicit, named *recovery* tool that walks back only the agent's own
  undo-group entries and refuses to touch interleaved human edits, rather
  than relying on the human to manually Ctrl+Z the right number of times.
- **`replay_last_session`**: every recorded mutating command is appended as
  one line to a session-scoped JSONL log (new file after a >10s gap, 30
  newest files retained); `replay_last_session` "skips read-only steps and
  marks replayed ones `replay: true`," and a separate `tests/socket_smoke.py`
  read-only smoke test can validate three sibling bridges (Houdini 9877,
  Blender 9876, Maya 7777) from one script
  (`abyrvalg379/mcp-socket-houdini:README.md`, tool table and "Smoke test"
  section). This is a session-level replay/reproduction capability neither
  this repository's `ExternalProcessJobAdapter` (job-state persistence, not
  replay) nor fxhoudinimcp's progress heartbeat provide.
- Security posture is the same explicit trade-off as fxhoudinimcp/oculairmedia:
  "localhost-only, no authentication, and `execute_houdini_code` runs
  arbitrary Python... this is a single-workstation tool for artist+agent
  workflows, not a service" (`abyrvalg379/mcp-socket-houdini:README.md`,
  "Security" section) — reconfirms this research's standing recommendation
  (Section 9) not to adopt unsandboxed execution, while flagging the
  replay/scoped-undo *mechanisms* (not the unsandboxed-execution posture) as
  worth isolating and borrowing independently of that trade-off.

#### 11.3.7 `alexantoshuk/houdini-mcp` — the clearest concrete evidence of a Zed/OpenAI-remote-MCP integration path in this space

Directly answers this task's instruction to find "Claude/Cursor/Zed/OpenAI
connector" examples: this project is built specifically around Zed's
`context_servers` extension mechanism, explicitly documents that "Zed forwards
configured MCP servers over ACP" to any of Zed's "External Agents (Cursor,
Claude ACP, Goose, Cline, OpenCode, Qwen Code, …)"
(`alexantoshuk/houdini-mcp:README.md`, "Architecture" table), and separately
supports OpenAI's remote-MCP / company-knowledge tool-naming convention
(`search`/`fetch` tool pair) plus a Streamable HTTP transport explicitly for
"OpenAI remote MCP / Inspector" use
(`alexantoshuk/houdini-mcp:README.md`, "Tools" and "Transports" sections). Its
bridge autostart logic explicitly guards against a known operational failure
mode other projects do not mention: it only autostarts in **GUI sessions**,
skipping `hython`/`hbatch` "so they no longer steal the port from a live
Houdini (no more renaming hooks to `.bak`)" (`alexantoshuk/houdini-mcp:README.md`,
"Live Houdini" section) — i.e., a documented regression this author
previously hit and fixed, worth keeping in mind as a concrete pitfall if this
repository's own external MCP adapter is ever started from a headless/hython
context.

### 11.4 Uncertainties and un-deep-dived items from this pass

- **`anshul-vashist/Houdini-Agent` identity is ambiguous**: the GitHub Search
  API returned this repo under the `anshul-vashist` account with the name
  `Houdini-Agent`, but its README's CI/License/Python-version badges all
  point to `waveWhirlVfx/houdinimind` (`github.com/waveWhirlVfx/houdinimind`)
  and the project calls itself "HoudiniMind" throughout. This is either a
  rename, a transfer, a personal mirror of an org project, or a badge left
  over from a template — not resolved in this pass; treat the
  `anshul-vashist`/`waveWhirlVfx` relationship as unverified, and cite
  specific facts to whichever URL they were actually read from (this report
  read `anshul-vashist/Houdini-Agent:README.md` content, which displays the
  `waveWhirlVfx/houdinimind` badges verbatim).
- **`loonghao/dcc-mcp`'s relationship to the `dcc-mcp` GitHub org** (which
  owns `dcc-mcp-core`, `dcc-mcp-houdini`, etc.) was not resolved — it may be
  the same author's earlier personal-account project that was later
  formalized into the `dcc-mcp` org, a fully separate project that happens to
  share a name, or an active fork target; `dcc-mcp-core`'s own README links
  to `clawhub.ai/loonghao/skills/dcc-mcp` as its recommended Agent Skill
  install path, suggesting some real connection between the `loonghao`
  account and the `dcc-mcp` org, but this was not independently confirmed by
  reading commit authorship or an explicit statement in either README.
- **Fourteen list-only rows in Section 11.2's table** (`JTCHE`, `rozhabrev`,
  `nscrdev`, `tmdag`, `rheadsh`, `Plygonality`, `beatreichenbach`,
  `Yudreamsky`, `JUSTDOITzhw/dsh-houdini-bridge`, `xurunxin/houdini-cli`,
  `MSP014`, `loonghao/dcc-mcp`, `eviscerations/houdini-bridge-mcp`, and the
  long tail below 5 stars not individually named) were identified via
  `search_repositories` metadata only (name, description, stars, forks,
  language, last-updated) and were **not** fetched for README/source content
  in this pass — their architecture, license, and activity-vs-abandonment
  status are unverified beyond what their one-line descriptions claim. A
  natural next-pass priority ordering, by potential uniqueness signal in
  their descriptions: `xurunxin/houdini-cli` ("isolated MCP runtime" — CLI
  angle this task asked about), `JUSTDOITzhw/dsh-houdini-bridge` (completes
  the DSH-ecosystem picture alongside `eee1723/dsh-houdini`), then the
  remaining single-digit-star repos in descending star order.
- **`dcc-mcp/dcc-mcp-core`'s Rust runtime internals** were not read beyond
  the README's architecture/contract tables; its three "shared contracts"
  (asset-import, recipe runtime, marketplace Skill contract with mandatory
  `recovery`/`undo` fields) are worth a dedicated follow-up read of
  `python/dcc_mcp_core/asset_import.py`,
  `contracts/dcc-discovery-decision-v1.schema.json`, and
  `python/dcc_mcp_core/runtime/postcondition.py` if this repository later
  considers a write-then-read-back postcondition contract for its own
  mutating tools, since dcc-mcp-core's "every tool call has to prove its own
  effect" framing is a close cousin of this repository's own audit/Harness
  verification goals.
- **This pass did not re-verify any Section 1-10 claim** from the first
  research pass; Section 11 is purely additive. Any apparent tension between
  Section 6's "biggest architectural difference from every surveyed project"
  framing and Section 11.1's finding that this repository's own direct
  upstream has since moved to the same external-bridge model as the rest of
  the field should be read as Section 11 updating, not contradicting,
  Section 6 — Section 6 remains accurate for the third-party landscape as
  surveyed; it is this repository's own upstream, specifically, that has
  since converged with that landscape.

### 11.5 Additional "What NOT To Do" items (supersedes nothing in Section 9, adds to it)

- **Do not treat `Kazama-Suichiku/Houdini-Agent`'s v2.0 standalone-bridge
  direction as something to follow reflexively** just because it is the
  direct upstream and has more stars/forks/features. This repository's own
  `README.md:12-13` already records a deliberate decision to diverge (keep
  the embedded panel, Houdini main-thread execution model) for production
  use inside Houdini; Section 11.1 confirms upstream's reasons for the
  standalone-bridge move are not documented in its README beyond the fact of
  the change, so this repository has no new evidence here that would
  override its own prior, explicitly reasoned choice — but it should
  periodically diff upstream's **feature** set (Meshy integration,
  NetworkBox folding, Plan-mode DAG diagrams, multi-provider model catalog
  auto-refresh) independently of the architecture question, since those are
  separable.
- **Do not adopt a DSH-Desktop-specific (`@deepseek-ai/dsh-*`/`cordis`)
  native plugin** as an additional integration surface alongside the
  external MCP adapter, on the grounds that `eee1723/dsh-houdini` has more
  stars than most MCP-based competitors. That ecosystem is a separate,
  single-vendor harness-plugin model (Section 11.3.3) with its own packaging,
  versioning, and distribution mechanics entirely outside MCP; building
  against it would duplicate this repository's governance work for one
  vendor's desktop app rather than reaching every MCP-capable client this
  repository's existing external adapter already can.
- **Do not collapse the external MCP surface down to a single
  `execute_python`/code-mode-style tool** (Section 11.3.2's pattern, used by
  `limitsurface/houdini-codemode-mcp`, `IvanYangYangXi/artclaw_bridge`, and
  implicitly by `Boning1011/houdini-agent`'s `exec`/`batch` pair) purely to
  match a stylistic trend. That pattern is specifically chosen by projects
  whose security model is "trust the local artist+agent, no governance
  layer" (explicitly stated by `abyrvalg379/mcp-socket-houdini` and implied
  by the others); this repository's external-adapter allow/deny/ask/retry
  model (Section 6, Section 9) is incompatible with a single
  arbitrary-code-execution tool by construction, since there is nothing left
  for a per-tool allowlist to allow or deny once the entire surface is one
  code-execution primitive. If broader workflow coverage is desired, prefer
  adding specific, individually-governed read/inspection tools (as Section 8,
  item 3 already recommends) over a code-mode escape hatch.
