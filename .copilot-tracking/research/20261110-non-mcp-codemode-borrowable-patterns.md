<!-- markdownlint-disable-file -->

# Research: Non-MCP / Code-Mode Borrowable Patterns vs. Houdini-Agent

## Task

Deep-dive five primary sources — `SFKislev/Flue`, `lmy-2004/houdini-ai`,
`IvanYangYangXi/artclaw_bridge`, `eee1723/dsh-houdini`,
`limitsurface/houdini-codemode-mcp` — reading current source/README/config/key
commits directly (not secondary summaries), and compare item-by-item against
this repository's current implementation. The goal is not a general overview:
find **specific, nameable mechanisms** that could be ported into Houdini-Agent
**without breaking** its per-tool governance / audit / confirmation / retry
boundary (Harness: allow/deny/ask/retry, mandatory audit, allow/deny lists,
risk ceilings). Nine mechanisms were specifically called out to check:

1. Structural scope limitation (cannot *express* out-of-scope actions, vs.
   policy that *evaluates and can deny* them)
2. Runtime HOM (Houdini Object Model) introspection as a fabrication guard
3. Single bounded `result.emit()` per run
4. Summary → bounded projection → artifact-reference output escalation
5. Skill hot-reload / override priority (official > marketplace > user >
   temporary)
6. CLI client entry point
7. No-listening-port communication (file-queue / outbound-only)
8. Session/command replay
9. Cross-DCC core-vs-adapter layering + plugin host mechanism

## Research Status

All five target repositories' `README.md` were fetched directly via
`get_file_contents` (GitHub API, not web cache) in this session on
2026-11-10; quotes below are taken from those direct fetches except where a
prior same-day research pass's quotes are explicitly reused and marked as
such (see "Reused prior citations" below). Houdini-Agent's own architecture
claims are grounded by direct `view`/`grep` of the following files on
2026-11-10: `CONTEXT.md`, `docs/adr/*.md`, `houdini_agent/skills/_inspection.py`,
`houdini_agent/skills/_contract.py`, `houdini_agent/skills/__init__.py`,
`houdini_agent/core/harness_engine.py`, `houdini_agent/core/readonly_python.py`,
`houdini_agent/core/tool_result_store.py`, `houdini_agent/core/session_manager.py`,
`houdini_agent/core/streaming_tool_executor.py`,
`houdini_agent/utils/hooks.py`, `houdini_agent/utils/mcp/settings.py`,
`houdini_agent/utils/mcp/external_jobs.py`, `houdini_agent/main.py`,
`houdini_agent_launcher.py`, `plugins/PLUGIN_DEV_GUIDE.md`, and a repo-wide
`grep` for `console_scripts`/`entry_points`/`argparse.ArgumentParser`/
`if __name__ == "__main__"` across all 98 `.py` files outside `tests/`.

**Reused prior citations**: a same-day prior report,
`.copilot-tracking/research/20261110-houdini-mcp-landscape-research.md`
(hereafter "the Landscape report"), already performed primary-source deep
dives on these same five repositories at sections 11.3.1 ("No MCP at all"),
11.3.2 ("Code Mode"), and 11.3.3 (DeepSeek/DSH plugin ecosystem), with direct
README quotes and citations. Where this report reuses a quote already
verified there, it is marked `(via Landscape report §11.3.x, itself a direct
README quote)`. All `SFKislev/Flue`, `lmy-2004/houdini-ai`, and
`limitsurface/houdini-codemode-mcp` README content below was independently
re-fetched in this session; `IvanYangYangXi/artclaw_bridge` and
`eee1723/dsh-houdini` were also independently re-fetched in this session
(full `README.md`, English for artclaw_bridge, Chinese for dsh-houdini) to
confirm the Landscape report's quotes and to extract additional detail
(skill-priority mechanics, memory tiers, plugin-host wiring) not covered
there.

## 1. Summary

All five projects reject or minimize the "every operation is its own schema'd
MCP tool" pattern Houdini-Agent and `fxhoudinimcp` both use, converging on
three alternative shapes: (a) no MCP/server at all, only an outbound-only or
in-process agent (`lmy-2004/houdini-ai`, `SFKislev/Flue`'s shell-bridge
model), (b) one generic code-execution MCP tool plus a runtime-discoverable
extension/help surface (`limitsurface/houdini-codemode-mcp`,
`IvanYangYangXi/artclaw_bridge`), or (c) a non-MCP native plugin living inside
a *coding-agent harness* rather than inside the DCC's own socket server
(`eee1723/dsh-houdini`). Of the nine specifically-checked mechanisms, six have
**no equivalent** in Houdini-Agent today (structural scoping, single-bounded
`result.emit()` as a protocol-level invariant, named multi-tier skill
override priority, a standalone CLI entry point, no-listening-port command
delivery, and session/command replay), one is **already implemented and
arguably stronger** (summary→projection→artifact via `ToolResultStore`), one
is **partially implemented but through a different mechanism**
(runtime HOM introspection exists as governance - `ToolArgumentValidator`,
`HoudiniInspection` - but is not exposed to the model as a discoverable
negative-fabrication guard), and one is **architecturally already present**
but shaped differently (plugin host via `HookManager`/`PluginContext`,
closer to `dsh-houdini`'s `cordis` IoC host than to artclaw's four-tier skill
marketplace). The highest-value, lowest-risk ports are: (1) a structural
scope-limiting Subnet/root-token mode for a narrow authoring surface
(governance-reinforcing, not weakening), (2) a file-queue "no listening
port" command bridge as an *additional*, not replacement, external-invocation
path that still routes through the existing Harness, and (3) session/command
replay for the agent's own mutating calls, modeled on the already-cited
`abyrvalg379/mcp-socket-houdini` `replay_last_session` idea but built on top
of the existing audit JSONL rather than a new log.

## 2. Primary-Source Evidence Per Repository

### 2.1 `SFKislev/Flue` (commit SHA `60d00d2b`, README fetched directly)

- Not MCP by design: *"MCPs define schemas and provide transport: but most
  desktop applications already include a fully documented scripting
  interface... MCPs are high maintenance, and computer use setups are
  fragile and clumsy; Flue is low maintenance"* (`SFKislev/Flue:README.md`,
  main description). Model: `agent shell -> bridge command -> app scripting
  runtime -> JSON result` - a single shell command per call, no long-lived
  server process, no socket.
- Distribution: `pip install flue && flue setup` auto-detects installed
  agentic harnesses (Claude Code, Codex, Gemini CLI, Cursor, OpenCode, Cline,
  Kilo CLI, etc., 12 named) and "lets them know that Flue is available to
  them" by installing itself **as a skill** (`README.md`, "Installation" /
  "Agentic Systems" sections) - i.e. Flue's integration point is the coding
  agent's own skill-discovery mechanism, not a DCC-side listener.
  Fourteen apps supported, each with its own `adapters/<app>_adapter/APP.md`,
  including `adapters/houdini_adapter/APP.md` (not fetched in this pass -
  gap, see §6).
- No evidence in this README of structural scoping, HOM introspection,
  bounded single-emit, or skill-priority tiers; those are the other four
  repos' contributions.

### 2.2 `lmy-2004/houdini-ai` (README fetched directly, Chinese-language, this
section's quotes are my own translations of the fetched text)

- **Structural scope limitation (item 1)** - the clearest primary-source
  instance of this mechanism in the five repos: *"碰不到 Subnet 外面——描述格式
  里没有'路径'这个概念，模型没法表达'去改外面那个节点'"* ("Cannot reach outside
  the Subnet — the description format has no concept of 'path' at all; the
  model has no way to express 'go modify that node outside [this Subnet]'")
  (`lmy-2004/houdini-ai:README.md`, "三条硬规矩" / "Three hard rules"
  section, rule 1). This is a **protocol/schema-level** containment: the
  input schema the model fills in (a free-text Chinese description inside
  one Subnet's parameter) has no node-path field or syntax at all, so there
  is no path string to validate, sanitize, or deny in the first place. It is
  categorically different from Houdini-Agent's `_HOUDINI_ROOTS`
  allowlist-based path validation (`harness_engine.py:190-198`), which
  *does* accept a path string and then checks membership against
  `{"/obj","/out","/shop","/stage","/tasks","/ch","/mat","/img","/cop"}`
  (`harness_engine.py:190-198`) - a policy check on an expressible value, not
  an inexpressible value.
- **Runtime HOM introspection as a fabrication guard (item 2)**: rule 2 of
  the same "三条硬规矩" section: *"编不出节点和参数——所有类型和参数名都从正在
  运行的 Houdini 里查出来，编造会被当场拒绝"* ("Cannot fabricate nodes or
  parameters — all types and parameter names are looked up from the live
  running Houdini; fabrication is rejected on the spot"). This means the
  tool/response-construction layer queries `hou` at call time for the set of
  valid node type names and parameter names available in-context, and
  rejects any model-proposed name that does not match a real, currently
  existing HOM entity, rather than trusting the model's own claim about what
  exists. Houdini-Agent's closest analog, `houdini_agent/skills/_inspection.py`'s
  `HoudiniInspection.node()`/`.parameter()`, performs the *same category* of
  live `hou.node(...)`/`.parm(...)` lookup-or-error
  (`_inspection.py:11-25`) - but this is invoked **after** the model has
  already named a (possibly wrong) node/parameter as a tool-call argument,
  surfacing the mismatch as a tool-execution error, not **before** generation
  as a constrained-decoding/discoverability guard that prevents the model
  from naming a nonexistent entity in the first place. `lmy-2004/houdini-ai`
  does not describe constrained decoding either (no explicit grammar/schema
  enforcement is documented) - its guard is also post-hoc, applied when the
  AI's generated node-network-build script runs inside the Subnet's
  background thread; the real novelty is that it is framed as one of only
  three named, user-facing "hard rules" guaranteed by the system, not an
  incidental validation step.
- **No listening port (item 7)**: *"不走 MCP——不监听任何端口，只有向网关的出站
  HTTPS"* ("Does not use MCP — listens on no port at all, only makes
  outbound HTTPS calls to a gateway") (`README.md`, opening paragraph). The
  AI model call itself is outbound HTTPS to an Anthropic-Messages-API-
  compatible gateway (credentials read from `~/.claude/settings.json`); there
  is no socket Houdini listens on for *that* channel. However, a **separate**
  local command-delivery channel does exist and is explicitly named: *"★
  命令桥：把 Python 送进跑着的 Houdini... 不监听任何端口，走本地文件队列
  (`~/.houdini-ai-bridge/`)"* ("★ Command bridge: send Python into a running
  Houdini... listens on no port, uses a local file queue"), invoked via a
  pure-bash client (`scripts/hcmd.sh --list`, `hcmd.sh -f cmd.py`, or piped
  stdin) with no Python process on the client side, consumed by a
  `pythonrc.py`-installed watcher thread running inside Houdini
  (`README.md`, "★ 命令桥" section). The README explicitly justifies
  *avoiding* `hrpyc` for this: *"没用 Houdini 自带的 `hrpyc`，因为
  `start_server()` 绑 `0.0.0.0` 且没有 host 参数——那等于把 Python 执行权开放给
  整个局域网"* ("Did not use Houdini's built-in `hrpyc`, because
  `start_server()` binds `0.0.0.0` with no host parameter - that is
  equivalent to opening Python execution to the entire LAN"). This is
  independent primary-source corroboration (from a project with no
  relationship to this repository) of the same `hrpyc` unauthenticated-bind
  risk the Landscape report's §9 "What NOT To Do" already flags.
- **CLI client entry point (item 6)**: `scripts/hcmd.sh` is a genuine
  thin CLI client (`README.md`, "★ 命令桥" section, three example
  invocations: `--list`, piped stdin, `-f cmd.py`) - a user-facing shell
  entry point distinct from the install script (`scripts/install.py`) and
  distinct from the Houdini-internal shelf buttons. This is the clearest
  primary-source example among the five of a **non-MCP CLI entry point**
  that talks to an already-running DCC process.
- **Skill hot-reload (item 5, partial)**: *"改完代码不用重启 Houdini"*
  ("No Houdini restart needed after code changes") - clicking any AI button
  triggers an automatic lightweight reload of `houdini_ai/*.py`; a dedicated
  "AiSubReload" shelf button reloads panel/shelf templates; a documented
  manual one-liner (`import houdini_ai.reload as r; r.reload_all(verbose=True)`)
  is provided, and "reload is refused while a task is running, to avoid
  losing worker-thread state" (`README.md`, "★ 改完代码不用重启 Houdini"
  section). This is hot-reload of the *tool/skill code itself*, not a
  multi-tier override-priority scheme (no official/marketplace/user/temporary
  tiers are described here - that mechanism belongs to artclaw_bridge, §2.3).
- Not described in this README: session/command replay (the file-queue
  command bridge is fire-and-forget, not a persisted, replayable session
  log), bounded single-`result.emit()` semantics, or a named plugin-host
  architecture (the three shelf buttons and the Subnet model are the whole
  surface).

### 2.3 `IvanYangYangXi/artclaw_bridge` (README fetched directly, English,
SHA `df7d6e857ff0`)

- **Single-tool-per-DCC code execution** (same family as Code Mode, item 3's
  prerequisite shape): *"Each DCC exposes only one MCP tool (`run_ue_python`
  / `run_python`), and AI completes all operations by executing Python code -
  minimal yet powerful"* (`README.md`, "🔗 Unified MCP Protocol" under "✨
  Core Features"). Unlike `limitsurface/houdini-codemode-mcp`, this one
  **does** keep MCP as the transport; it collapses only the *tool count*,
  not the protocol.
- **Skill hot-reload / override priority (item 5)** - the clearest,
  most literally on-point primary-source evidence for this exact mechanism
  among all five repos: *"Layered Skill hot-reloading system, shared across
  DCCs: **Four-Level Priority** — Official > Marketplace > User > Temporary,
  higher levels override lower ones"* (`README.md`, "🛠️ Skill Management
  System" section). Additional mechanics documented in the same section:
  "In-Editor Management Panel — Unified UI for both UE + DCC, supports
  filter/search/enable/disable/pin"; "Full Lifecycle — Install, uninstall,
  update, publish (version increment + git commit), one-click full sync";
  "AI-Generated Skills — Describe requirements in natural language, AI
  auto-generates executable Skills (manifest + code + docs)"; "Change
  Detection — Auto-detects unpublished changes at runtime, intelligently
  distinguishes 'update' vs 'publish' direction"; "Pinned Skills Context
  Injection — Pinned Skill docs automatically injected into AI's first
  message context." The "Creating Skills" section states the generated
  artifact shape concretely: *"AI will auto-generate `SKILL.md` +
  `manifest.json` + `__init__.py`, ready to use after confirmation"*
  (README.md, "🛠️ Skill System" / "Creating Skills"). A dedicated
  `docs/skills/MANIFEST_SPEC.md` is referenced as the authoritative
  `manifest.json` format spec (not independently fetched in this pass - the
  priority *mechanism* is confirmed at the README level, but the exact
  conflict-resolution algorithm, e.g. whether it is resolved by skill name,
  by category, or by explicit manifest field, was not verified - see gaps).
- **Not** a code-mode single-emit design beyond the one-tool-per-DCC
  collapse: no `result.emit()`-style bounded-single-return language appears
  in this README (that is `limitsurface/houdini-codemode-mcp`-specific,
  §2.5).
- **Governance contrast** (relevant to "does not break governance"
  adaptation): the README frames its own design philosophy explicitly
  *against* unstructured direct LLM control: *"Direct LLM integration is a
  black box - unpredictable and uncontrollable... ArtClaw Bridge adds
  engineering discipline to AI execution: Structured Skills provide
  predictable behavior; MCP protocol standardizes communication; Tool
  Manager enables controllable automation"* (README.md, "🧾 Design
  Philosophy" / "Why MCP + Skills Instead of Direct LLM Integration?") - i.e.
  despite collapsing to one execution tool per DCC, the project still claims
  a governance/structure story through its Skill layer rather than trusting
  raw code execution alone; whether that Skill layer has an allow/deny/ask
  policy engine comparable to Houdini-Agent's Harness was **not** verified
  in this pass (no `mcp_server.py`/policy-engine source was fetched - flag
  as a gap, not a confirmed absence).

### 2.4 `eee1723/dsh-houdini` (README fetched directly, Chinese-language, SHA
`8d2b42ddbaeeb28`)

- **Not MCP; plugin-host inside an agent harness, not inside Houdini's own
  socket server** (item 9's "cross-DCC core-vs-adapter" question answered in
  a different direction than Houdini-Agent's): *"dsh-houdini 将 Houdini 的
  真实场景接入 DeepSeek Harness Desktop。在同一份对话中描述目标，Agent 可以读取
  场景、创建和修改节点、调整参数、制作工具，并根据实际执行结果继续迭代"*
  ("dsh-houdini connects Houdini's real scene into DeepSeek Harness Desktop.
  In the same conversation, describe a goal, and the Agent can read the
  scene, create and modify nodes, adjust parameters, make tools, and keep
  iterating based on actual execution results") (`README.md`, opening
  paragraph). Per the Landscape report §11.3.3 (verified there via direct
  `package.json`/README reads, reused here): it is a TypeScript/Node package
  built against first-party `@deepseek-ai/dsh-*` scoped packages and
  `@deepseek-ai/cordis` (a plugin-host/IoC framework), wired in via a
  `cordis.patch.yml` preset (`package.json`, `dsh.bundle.patch` field) - this
  is a **completely separate plugin-host architecture from MCP's
  server/client/JSON-RPC model and from Houdini-Agent's own
  `HookManager`/`PluginContext`** (§3.3 below): plugins here are DSH-host
  extensions that *add a DCC mode to the chat harness*, not Houdini-side
  extensions that add tools to a DCC-embedded agent.
- Primary artifacts are explicitly kept native: *"主要产物保留为原生节点网络、
  控制参数、关键帧、HDA 和工程文件。你可以查看构建过程、手工编辑结果，也可以
  继续通过对话提出修改"* ("Primary artifacts remain native node networks,
  control parameters, keyframes, HDAs, and project files. You can inspect the
  build process, manually edit results, and continue proposing changes via
  conversation") - a design value (native artifacts over opaque blobs)
  shared conceptually with Houdini-Agent's own node/parameter-first tool
  surface, though arrived at independently.
- No structural scoping, single-emit, replay, or skill-priority mechanism is
  described in the fetched README beyond the plugin-host wiring itself; its
  main contribution to this report is item 9 (a concrete example of a
  *harness-side* plugin host as opposed to a *DCC-side* one).

### 2.5 `limitsurface/houdini-codemode-mcp` (README fetched directly, SHA
`09b7191bf517`)

- **Single bounded `result.emit()` (item 3)**, stated as an explicit,
  protocol-level rule, not a convention: *"Call `result.emit(value)` at most
  once. Prefer a summary, then a bounded projection, then an artifact
  reference."* (`README.md`, "Using Code Mode" section, final paragraph).
  This is the single clearest, most literally on-point primary-source
  citation for items 3 and 4 together among the five repos.
- **Summary → bounded projection → artifact (item 4)**, elaborated in a
  dedicated subsection: *"Focused summaries make nodes, parameters,
  geometry, Copernicus networks, LOPs, and HDAs practical to inspect without
  flooding the model context. When a workflow needs lossless node or network
  state, bounded artifacts keep the large payload on disk and return a
  compact manifest instead."* (`README.md`, "Bounded inspection and
  artifacts" section, under "Extension highlights"). The stated motivation
  ("without flooding the model context") is the exact concern Houdini-Agent's
  own `ToolResultStore.archive_if_large` solves (see §3.2) - independent
  convergence on the same problem, solved via two different mechanisms
  (protocol-level single-emit-with-escalation discipline vs. a
  size-threshold auto-archival store with a separate `read`/`describe`
  retrieval tool).
- **Runtime HOM introspection, generalized to the whole extension surface**
  (item 2, a different flavor than `lmy-2004/houdini-ai`'s node/parameter
  fabrication guard): *"Discover the available extension surface inside a
  run: `result.emit(ctx.capabilities())`... Extension help includes the
  exact signature, effect category, and summary:
  `result.emit(ctx.help("ctx.opencl.sync"))`"* (`README.md`, "Using Code
  Mode" section). Here the introspection target is the **tool/extension
  surface itself** (what hand-written `ctx` helpers exist, with live
  signature/doc lookup), not node/parameter existence in the scene - a model
  calls `ctx.capabilities()`/`ctx.help(...)` as ordinary Python inside its
  one `houdini_code_run` call to discover what it can do, rather than being
  handed a static tool schema list up front. This directly parallels
  Houdini-Agent's `list_skills`/`get_skill_instructions` meta-tool pattern
  (§3.4) but goes one level further: the discovery call happens **inside**
  the single sandboxed code-execution call rather than as a separate
  model-visible tool choice.
- **CLI predecessor / explicit deprecation (item 6, negative evidence)**:
  *"Houdini Code Mode MCP is the successor to Houdini CLI
  (github.com/limitsurface/houdini-cli). The CLI remains available for
  command-oriented Houdini workflows."* (`README.md`, final "Houdini CLI"
  section). This confirms (independently of the Landscape report's own
  earlier citation of the same fact) that this author's own migration path
  went *from* a CLI/`hrpyc` pattern *to* a one-tool MCP pattern - i.e. in
  this specific lineage, the CLI entry point is the superseded artifact, not
  the novel one; it is listed here as useful context for item 6 rather than
  as a feature to port.
- **Loopback-only, trust-the-process posture** (same family as every other
  surveyed Code-Mode/bridge project): *"Submitted code runs locally with the
  permissions of the Houdini process... The server binds only to
  `127.0.0.1` and is intended for trusted local use"* (`README.md`, opening
  paragraph and "2. Add the Houdini shelf script" section). No allow/deny
  list, risk ceiling, or audit trail is described for the single
  `houdini_code_run` tool - the entire governance model is "trust the local
  process," which is the opposite end of the spectrum from Houdini-Agent's
  Harness and is explicitly why this mechanism (full `hou` access via one
  tool) must **not** be ported as-is (see §5's adoption notes for the single
  scope-limited exception considered).
- No skill-priority/override-tier scheme, no session/command replay, and no
  listening-port-avoidance claim (it binds a loopback HTTP port, same as
  fxhoudinimcp) are present in this README.

## 3. Houdini-Agent's Current Equivalent Mechanisms (primary source: this
repository, read directly in this session)

### 3.1 Structural vs. policy-based scoping

- `ToolArgumentValidator._HOUDINI_ROOTS` is a **fixed allowlist of top-level
  Houdini context roots** (`/obj`, `/out`, `/shop`, `/stage`, `/tasks`,
  `/ch`, `/mat`, `/img`, `/cop`) checked via string-prefix membership
  (`harness_engine.py:190-198`, `CONTEXT.md` "Node Path" entry: "校验
  traversal、null-byte，并强制落在 `_HOUDINI_ROOTS` 内"). Any node-path-typed
  tool argument is first normalized, then validated against this allowlist
  before the policy engine scores it - this is a **value-level policy
  check**: the model can still *express* `/obj/../etc/passwd`-style or
  out-of-root strings, and the system *evaluates and rejects* them.
- `readonly_python.py:readonly_python_violation` is an **AST-based denylist**
  over a fixed `_MUTATING_CALLS` set (34 named HOM methods: `createNode`,
  `destroy`, `setParms`, `save`, etc., `readonly_python.py:9-16`) plus
  blanket denial of imports, deletes, augmented assigns, and
  attribute/subscript assignment. This is also **value/code-level policy
  evaluation**, not structural inexpressibility: a submitted Python string
  *can* contain `node.destroy()`; the checker inspects the parsed AST and
  rejects it after the fact (at validation time, before execution) rather
  than the schema making `destroy()` impossible to write in the first
  place.
- `lmy-2004/houdini-ai`'s rule-1 mechanism (§2.2) is different in kind: the
  Subnet-description input schema has **no path field or path syntax at
  all**, so there is no string to validate - the model is not given a slot
  in which an out-of-scope reference could even be typed. Houdini-Agent has
  no equivalent of this for any of its ~78 tools: every mutating tool that
  targets a node accepts a path string argument and relies on Harness
  value-level validation, never on schema-level inexpressibility.

### 3.2 Bounded result emission and summary→projection→artifact

- **Already implemented, and arguably stronger than the reference**:
  `ToolResultStore.archive_if_large` (`tool_result_store.py:17-45`)
  serializes a tool result, and if it exceeds `threshold` (default 16,000
  bytes), writes it atomically (temp file + `os.replace`) to
  `tool_results/<session_id>/res_<uuid>.json` with a `sha256` integrity hash
  and returns a compact pointer document (`result_ref`, `size`, `sha256`,
  `content_type`, plus any `operation_receipt`/`audit_status`/`replay_safe`
  metadata already on the result) instead of the full payload
  (`tool_result_store.py:38-45`). A paired `read(result_ref, pointer, offset,
  limit)` method supports RFC-6901 JSON-Pointer sub-selection and a
  character-offset/limit window (max 16,000 chars) for progressive reading
  (`tool_result_store.py:56-69`), and `describe(result_ref)` re-verifies the
  stored hash before returning a name/success summary
  (`tool_result_store.py:71-81`). This is **already** a summary (the default
  small-result path) → bounded projection (the `read` pointer/offset/limit
  path) → artifact-reference (`result_ref` + on-disk JSON + integrity hash)
  escalation, functionally equivalent to `houdini-codemode-mcp`'s stated
  discipline, and additionally provides tamper-evidence (`sha256` check in
  `describe`) that the Code Mode README does not claim for its own bounded
  artifacts.
- The one gap relative to Code Mode: this mechanism is **per-tool-result
  auto-archival** triggered by a size threshold, not a **protocol-level
  single-emit invariant** enforced on the model's own output construction
  (item 3's literal ask). There is nothing today that prevents a tool
  handler itself from returning multiple large chunks across multiple
  non-archived calls, or that frames "emit at most once" as a rule the model
  is told to follow for freeform code-mode-style execution (Houdini-Agent
  has no single generic code-execution tool to apply such a rule to in the
  first place - see §4.3).

### 3.3 Plugin host mechanism

- `houdini_agent/utils/hooks.py`'s `HookManager` (singleton,
  `hooks.py:63-80`) + `PluginContext` (`hooks.py:315-384`) is Houdini-Agent's
  existing plugin-host: `ctx.on(event, callback, priority)` for seven named
  hook points (`on_before_request`, `on_after_response`, `on_before_tool`,
  `on_after_tool`, `on_content_chunk`, `on_session_start`, `on_session_end`,
  per `plugins/PLUGIN_DEV_GUIDE.md`, "Event Hooks" section),
  `ctx.register_tool(name, description, schema, handler)` which
  auto-registers into the shared `ToolRegistry` (`PLUGIN_DEV_GUIDE.md`,
  "Custom Tools"), `ctx.register_button(...)` for UI, and
  `ctx.get_setting`/`set_setting` for persisted per-plugin config
  (`hooks.py:167-220`, `:367-371`). `load_all_plugins()`,
  `reload_plugin(plugin_name)`, `enable_plugin`/`disable_plugin`, and
  `reload_all_plugins()` (`hooks.py:439-721`) give full-lifecycle hot
  reload/enable/disable from a Plugin Manager UI
  (`PLUGIN_DEV_GUIDE.md`, "Plugin Manager UI has 3 tabs").
- This is architecturally closer to `eee1723/dsh-houdini`'s `cordis` IoC
  plugin-host *shape* (a central registry/manager object plugins attach to
  via hooks and a context object) than to `artclaw_bridge`'s four-tier
  **skill marketplace** shape - Houdini-Agent's plugin host governs *code
  extension points* (tools, UI buttons, lifecycle events), while
  `artclaw_bridge`'s Skill layer governs *content/knowledge bundles*
  (`SKILL.md` + `manifest.json` + code, installed/updated/published/pinned)
  with layered name-priority resolution. Houdini-Agent's own Skill layer
  (§3.4) is the closer analog to artclaw's Skills, not the plugin host.

### 3.4 Skill directory, hot-reload, and override priority

- `houdini_agent/skills/__init__.py` scans a **builtin** directory
  (`Path(__file__).parent` plus ten fixed category subdirectories:
  `authoring`, `docs`, `geometry`, `graph`, `learning`, `materials`,
  `performance`, `scene`, `usd`, `workflow` - `__init__.py:66-73`,
  `CONTEXT.md`'s category list) and one **per-user** directory
  (`_get_user_skill_dir()`, reading `cache/users/<username>/config.ini`
  `[skills] user_skill_dir`, `__init__.py:84-93`), loading user skills with a
  `user_` module-name **prefix** rather than letting a user skill *replace*
  a builtin one of the same bare name (`__init__.py:379-386`,
  `_load_skills_from_dir(user_dir, prefix="user_", ...)`). Per-skill
  enable/disable state is persisted via `ToolRegistry.get_disabled_tools()`
  keyed `skill_<name>` (`__init__.py:_is_skill_enabled`, confirmed present
  in the viewed excerpt). This is a **two-tier, prefix-namespaced**
  coexistence model, not a **four-tier, name-collision-resolving override**
  model: a user skill and a builtin skill with the same base name do not
  compete for the same identity at all (the user one is addressable only as
  `user_<name>`), so there is no "higher level overrides lower" resolution
  logic to point to, unlike artclaw_bridge's explicit "Official > Marketplace
  > User > Temporary, higher levels override lower ones."
- Hot-reload exists at a coarser granularity than `lmy-2004/houdini-ai`'s
  per-click lightweight reload: Houdini-Agent's `HOUDINI_AGENT_DEV_RELOAD`
  env var (`houdini_agent_launcher.py:_is_dev_reload_enabled`,
  `main.py:_reload_modules`) reloads a **fixed list of core modules**
  (`houdini_agent.qt_compat`, `houdini_agent.utils.token_optimizer`, ... ,
  `houdini_agent.core.main_window`, `main.py:19-42`) and is explicitly a
  **developer-mode** toggle, not a per-skill end-user reload button; skills
  themselves rely on `_loaded`/`_clear_registry()` invalidation triggered by
  `set_current_user` (`__init__.py:78-82`) rather than a one-click
  "reload this skill" affordance for a running session.

### 3.5 CLI client entry point and no-listening-port communication

- Confirmed **absent**: a repo-wide `grep` for
  `console_scripts`/`entry_points`/`argparse.ArgumentParser`/
  `if __name__ == "__main__"` across all 98 non-test `.py` files found only
  test fixtures, developer scripts under `scripts/` (manifest/catalog
  generators, DB migration/merge helpers - none of which are a
  running-Houdini command client), `.github/skills/quality-playbook/`'s
  internal gate script, and the two launcher entry points
  (`houdini_agent_launcher.py`, `houdini_agent/main.py`), which only start
  the in-process Qt panel inside Houdini itself. There is no standalone
  shell/CLI program analogous to `scripts/hcmd.sh`
  (`lmy-2004/houdini-ai`) or Flue's `flue` command
  (`SFKislev/Flue`) that talks to an *already-running* Houdini session from
  outside it, other than the external MCP HTTP adapter (which requires an
  MCP client, not a plain shell command).
- The only existing "no listening port" mechanism is inbound-blocking by
  default, not outbound-only-by-design: `settings.py:48` (`enabled: bool =
  False`) keeps the external MCP server off unless explicitly enabled, and
  when enabled it is still a **listening** HTTP port
  (`settings.py:49-51`: `host: str = "127.0.0.1"`, `port: int = 9000`,
  `transport: str = "streamable-http"`), with host validated to loopback
  only at parse time (`settings.py:101-103`: `if host not in {"127.0.0.1",
  "localhost", "::1"}: raise ValueError(...)`). `ExternalProcessJobAdapter`
  (`external_jobs.py:58-154`) manages **outbound** subprocess jobs (spawned
  by Houdini-Agent itself) with atomic JSON job-state persistence, not an
  **inbound** file-queue command channel analogous to `lmy-2004/houdini-ai`'s
  `~/.houdini-ai-bridge/` watcher. There is, in short, no zero-listening-port
  path for an *external* actor to submit a command into a running
  Houdini-Agent session today - every external-trigger path goes through the
  FastMCP HTTP port.

### 3.6 Session/command replay

- `session_manager.py`'s `SessionManagerMixin` manages **UI conversation
  tabs** (`_conversation_history`, saved/restored per tab,
  `session_manager.py:123-200`) - this is chat-transcript persistence across
  UI tab switches, not a replayable log of the agent's own *mutating tool
  calls* against the Houdini scene. No `replay_last_session`-equivalent (per
  the Landscape report §11.3.6's citation of `abyrvalg379/mcp-socket-houdini`,
  reused here as corroborating context, not re-verified in this pass) exists:
  there is no mechanism found in this session's review that re-executes a
  prior session's recorded write operations in order, skipping read-only
  steps. The audit JSONL described in
  `docs/adr/external-mcp-governance-boundary.md`'s "Audit Failure Contract"
  section (policy decisions, matched rules, confirmation outcomes, execution
  terminals - "argument values and prompt text are not audit payloads") is
  explicitly **not** designed for replay (it deliberately omits argument
  values, which a replay mechanism would need), so replay cannot be bolted
  onto the existing audit log without either a schema change or a second,
  purpose-built replay log.

## 4. Per-Mechanism Comparison Table

| # | Mechanism | Primary source | User value | Houdini-Agent today | Gap type |
|---|---|---|---|---|---|
| 1 | Structural scope limitation | `lmy-2004/houdini-ai` README "三条硬规矩" rule 1 | Un-bypassable scope limit; no policy bug can leak outside the box because the box was never expressible | `_HOUDINI_ROOTS` allowlist + AST denylist (`harness_engine.py:190`, `readonly_python.py`) - value-level policy, not structural | **No equivalent** (different security category) |
| 2 | Runtime HOM introspection as fabrication guard | `lmy-2004/houdini-ai` rule 2; `houdini-codemode-mcp`'s `ctx.capabilities()`/`ctx.help()` | Prevents the model from inventing node types/params/extension names it has no business claiming exist | `HoudiniInspection.node()`/`.parameter()` (`_inspection.py:11-25`) does live lookup-or-error, but post-hoc (at execution, not at generation/discovery time) and not exposed as a model-facing capability-discovery call | **Partial** - same mechanism category, different timing/exposure |
| 3 | Single bounded `result.emit()` | `houdini-codemode-mcp` README, "Using Code Mode" | Protocol-enforced context-budget safety independent of tool-catalog size | No single generic code-execution tool exists to apply this rule to; result-size bounding happens per-tool via `ToolResultStore`, not as a one-call-one-emit invariant | **No direct equivalent** (different protocol shape - N tools each returning once, not one tool emitting once) |
| 4 | Summary → projection → artifact | `houdini-codemode-mcp` README, "Bounded inspection and artifacts" | Avoids flooding model context with large payloads while keeping lossless state recoverable | **Already implemented, arguably stronger**: `ToolResultStore.archive_if_large`/`read`/`describe` (`tool_result_store.py:17-81`) - size-threshold auto-archival, JSON-Pointer + offset/limit projection, sha256 tamper-evidence | **No gap - adopt nothing, document the symmetry** |
| 5 | Skill hot-reload / 4-tier override priority | `artclaw_bridge` README "🛠️ Skill Management System"; `lmy-2004/houdini-ai` "★ 改完代码不用重启 Houdini" | Teams can layer official/marketplace/user/temporary skills with predictable conflict resolution and no-restart iteration | Two-tier builtin+per-user skill dirs, **prefix-namespaced** (`user_` prefix) rather than override-resolved (`skills/__init__.py:66-93,379-386`); coarse dev-mode module reload, not per-skill end-user reload | **Partial** - reload exists at plugin level (`hooks.py:560,695`), priority-tier override does not exist at skill level |
| 6 | CLI client entry point | `lmy-2004/houdini-ai` `scripts/hcmd.sh`; `SFKislev/Flue`'s `flue` command | Lets any shell/script/CI pipeline drive an already-running session without an agent harness or MCP client | Confirmed absent repo-wide (`grep` for CLI entry patterns found none outside dev tooling) | **No equivalent** |
| 7 | No-listening-port communication | `lmy-2004/houdini-ai` file-queue bridge; same README's outbound-only AI channel | Eliminates an entire class of network-reachable-port risk (DNS rebinding, LAN exposure, port scanning) for at least one invocation path | Only inbound path is the FastMCP HTTP port (loopback-only, off by default) (`settings.py:48-51,101-103`); `ExternalProcessJobAdapter` is outbound-subprocess, not inbound-file-queue (`external_jobs.py`) | **No equivalent for inbound; outbound AI-model calls already analogous** |
| 8 | Session/command replay | Landscape report §11.3.6 citing `abyrvalg379/mcp-socket-houdini`'s `replay_last_session` (not one of the five target repos, cited here only as a design-pattern reference point since none of the five target repos documents replay) | Reproduce a prior session's writes in order after a crash/rollback, skipping read-only steps | `SessionManagerMixin` persists chat transcript, not a replayable mutating-call log; audit JSONL explicitly omits argument values, so it cannot be replayed as-is | **No equivalent** |
| 9 | Cross-DCC core/adapter + plugin host | `eee1723/dsh-houdini`'s `cordis`-based DSH-harness plugin; `artclaw_bridge`'s per-DCC bridge + shared Skill layer | Reuse one core governance/knowledge layer across multiple DCC adapters instead of re-implementing per-DCC | `HookManager`/`PluginContext` (`hooks.py`) is a genuine plugin host, but scoped to Houdini-Agent's own single-DCC process; no cross-DCC core/adapter split exists or is implied by current architecture (`README.md:12-13`'s in-process-panel model is Houdini-specific by construction) | **Architecturally out of scope today** - not a gap to close without a larger re-architecture decision |

## 5. Adoption Recommendations, Ranked By Value, With Governance Adaptation

### 5.1 ADOPT (high priority)

**A. Add an inbound, no-listening-port, file-queue CLI command bridge as an
*additional* governed-execution entry point (items 6 + 7 together).**

- *Original implementation*: `lmy-2004/houdini-ai`'s `~/.houdini-ai-bridge/`
  local file queue, consumed by a `pythonrc.py`-installed watcher thread,
  driven by a pure-bash `scripts/hcmd.sh` client with no client-side Python
  process (`README.md`, "★ 命令桥" section).
- *User value*: lets CI pipelines, shell scripts, and non-MCP-aware tooling
  submit governed operations to an already-running Houdini-Agent session
  without opening any new listening socket - useful for headless batch farms
  and for users whose IT policy forbids opening any new local port at all,
  even loopback-only ones.
- *Current repo equivalent*: none (confirmed absent, §3.5).
- *Minimal port*: a new `FileQueueCommandAdapter` that polls (or
  `watchdog`-observes) a per-session directory under the existing cache root
  for append-only JSON command files (one file per request, same
  atomic-write-then-`os.replace` pattern already used by
  `ToolResultStore`/`external_jobs.py`), each file naming a **registered
  tool name + arguments** (never raw Python/shell), consumed on Houdini's
  main thread the same way the FastMCP adapter's calls are today.
- *Governance adaptation (non-negotiable for this to be safe)*: this adapter
  **must** call the exact same `GovernedToolExecutor` /
  `HarnessToolPolicyEngine` path the FastMCP adapter uses
  (`docs/adr/external-mcp-governance-boundary.md`'s "Adapter Contract" -
  trusted context, allowlist/deny-list, risk ceiling, session/concurrency
  limits, mandatory audit) - it must be a **second transport**, not a bypass.
  Confirmation (`ask`) is the hard problem: file-queue clients have no
  synchronous callback channel, so either (a) this adapter is restricted to
  tools whose policy resolves to `allow` without requiring `ask` (i.e. the
  same read-only-by-default posture the FastMCP adapter already has), or (b)
  a two-file protocol is added (request file → a separate
  "pending-confirmation" file the Houdini-Agent UI panel surfaces for a
  human to approve/deny, writing a response file) - do not implicitly
  `allow` an `ask`-tier write just because there is no callback, per the
  existing "no implicit allow fallback" rule already documented for FastMCP
  (`external-mcp-governance-boundary.md`, "Human Confirmation" section).
- *Security risk*: file-queue directories are generally more permissive
  (filesystem ACLs, not a bound-and-authenticated socket) than a
  loopback-only TCP port in a multi-user OS context; must inherit the same
  per-session directory isolation `ToolResultStore` already uses
  (`tool_result_store.py:17`, session-ID-namespaced subdirectory with
  identifier validation) and must validate the session ID against the
  currently owning Houdini-Agent UI session, exactly as `ExternalMCPContext`
  already does for FastMCP (external-mcp-governance-boundary.md, "Adapter
  Contract").
- *Adoption level*: **Adopt**, scoped initially to the existing read-only
  default allowlist only (parity with current FastMCP defaults), deferring
  the two-file confirmation protocol as a follow-up.
- *Priority*: **High** (clear, bounded, governance-compatible; closes two of
  the nine checked gaps at once).
- *Acceptance criteria*: (1) a new test file
  `tests/test_file_queue_command_adapter.py` proves identical policy
  decisions (allow/deny/ask/retry) are produced for the same tool+args via
  both the FastMCP adapter and the file-queue adapter; (2) a write-tier tool
  submitted via the file-queue adapter is denied, not silently allowed, when
  no confirmation channel is wired up; (3) the adapter never imports or
  evaluates raw Python/shell strings from a queued file - only registered
  tool name + JSON arguments are accepted, re-validated through the existing
  `ToolArgumentValidator`; (4) session-ID path traversal/malformed-ID
  rejection is covered, mirroring `ToolResultStore._validate_session_id`'s
  existing pattern (`tool_result_store.py:94-97`).

**B. Add session/command replay for the agent's own mutating calls (item 8).**

- *Original implementation*: cited via the Landscape report's own
  prior-session primary-source read of `abyrvalg379/mcp-socket-houdini`'s
  `replay_last_session` (JSONL, new file after a >10s gap, 30 newest files
  retained, skips read-only steps, marks replayed entries `replay: true`) -
  not one of this task's five target repos, but the closest named precedent
  for this exact mechanism, and worth citing accurately as such rather than
  attributing it to one of the five.
  *(No equivalent mechanism was found documented in any of the five target
  repos' fetched READMEs in this session - this is the one checked item
  where the five target repos provided no new primary-source evidence, and
  the existing Landscape-report citation is reused as the best available
  grounding.)*
- *User value*: after a crash, an undo-stack overrun, or a scene reload,
  re-apply exactly the agent's own prior writes in order, without re-running
  read-only inspection calls, and without needing the human to remember
  what happened.
- *Current repo equivalent*: none safe to reuse directly - the existing
  audit JSONL explicitly excludes argument values by design
  (`external-mcp-governance-boundary.md`, "Audit Failure Contract": "Tool
  audit records include host-owned call/run identity, policy version,
  matched rules, confirmation outcomes, and execution terminals; argument
  values and prompt text are not audit payloads").
- *Minimal port*: a **new, separate, opt-in** replay log (not a modification
  of the existing audit log, to avoid weakening its argument-value-exclusion
  privacy guarantee) that records only for mutating tool calls that
  completed with `replay_safe=true` (a field the Audit Failure Contract
  already defines, per `external-mcp-governance-boundary.md`: "a write has
  already run when its result audit fails... `replay_safe=false` prohibits
  automatically repeating that write") - i.e. this repo already has the
  exact semantic flag needed to gate replay eligibility; it is not currently
  *used* to build a replay log, only to prevent automatic re-attempt after
  an audit failure.
- *Governance adaptation*: replay execution must re-enter the full Harness
  pipeline per replayed call (fresh policy evaluation, fresh confirmation if
  the tool is `ask`-tier, fresh audit record) - it is not a raw log replay
  that bypasses governance, precisely because scene state may have changed
  since the original run (a node the original call targeted may no longer
  exist).
- *Security risk*: a replay log that **did** store argument values would be
  a new, larger attack surface for argument-value leakage than the current
  audit log deliberately avoids; the opt-in log must have its own
  retention/redaction policy reviewed separately before being enabled by
  default.
- *Adoption level*: **Adopt**, opt-in only, off by default, pending its own
  ADR given the privacy-scope departure from the current audit log's
  explicit no-argument-values invariant.
- *Priority*: **Medium** (real value, but meaningfully more design work than
  item A because of the privacy/governance interaction with the existing
  audit contract).
- *Acceptance criteria*: (1) replay log is a distinct file/table from the
  existing audit JSONL, with its own config flag defaulting to disabled; (2)
  a replayed call that targets a node no longer present fails with a clear,
  non-silent error rather than creating an unexpected node at a
  coincidentally-reused path; (3) a call whose original execution had
  `replay_safe=false` is excluded from the replay set entirely, verified by
  a unit test; (4) replay re-runs the full policy/confirmation/audit
  pipeline per call, verified by a test asserting per-call audit records are
  created during replay, not copied from the original run.

### 5.2 ADOPT, selectively (medium priority)

**C. A narrow, schema-level "structurally scoped" authoring mode for one
specific high-value workflow (item 1), not a general replacement for
`_HOUDINI_ROOTS`/AST-denylist validation.**

- *Original implementation*: `lmy-2004/houdini-ai`'s Subnet-description input
  schema with no path concept (§2.2, §3.1).
- *User value*: for a specific bounded authoring task (e.g., "fill in this
  one Subnet" or "populate this one HDA's internal network"), a
  structurally-scoped input format removes an entire class of path-escape
  bugs from the validator's responsibility - the bug *cannot* exist in that
  mode, rather than *must be caught* by the allowlist/denylist.
- *Current repo equivalent*: `CONTEXT.md`'s "Scoped Validation Transaction"
  already names a conceptually adjacent idea at the *validation* level
  ("在捕获当前 Update Mode 后临时进入 Auto，只对指定 target 执行 cook/read" -
  temporarily scoping a cook/read operation to one target), but this is
  about Update Mode during read-side validation, not about making a
  mutating-tool's *input schema itself* structurally incapable of naming an
  out-of-scope node.
- *Minimal port*: a new tool variant (not a modification of existing tools)
  whose schema takes a `subnet_token` resolved server-side to a fixed root
  node path chosen at session/task start, and a *relative*, path-free
  description of what to build inside it - never accepting an absolute or
  `..`-relative path string from the model for this tool's target at all.
  This keeps all 78 existing tools' schemas unchanged; it adds one
  purpose-built, structurally-scoped tool for a specific class of
  "build/iterate on exactly this one subnetwork" tasks.
- *Governance adaptation*: this is additive to, not a replacement for, the
  existing Harness - the new tool still goes through
  `HarnessToolPolicyEngine` for its own risk/confirm classification; the
  benefit is narrower attack surface for *this one tool's* path-escape risk
  class, not a weakening of any existing check.
- *Security risk*: low, since it only restricts what the schema can express;
  care is needed that the server-side `subnet_token → path` resolution
  itself cannot be redirected by a malicious/compromised token value (token
  must be session-bound and server-minted, never client-suppliable as a
  free string).
- *Adoption level*: **Adopt selectively** - build one example tool, not a
  framework-wide schema migration.
- *Priority*: **Medium** (real security value for the specific workflow it
  targets; low value if applied broadly since most tools genuinely need to
  address arbitrary existing nodes).
- *Acceptance criteria*: (1) the new tool's JSON schema contains no
  string-typed "path" field for its target at all - only an opaque
  session-bound token and a path-free description; (2) a test proves no
  string value supplied for any of this tool's parameters can cause a node
  outside the bound Subnet to be touched, by construction (not merely by a
  value check that happens to catch all current test cases); (3) existing
  `_HOUDINI_ROOTS`/AST-denylist tools are unmodified by this change.

**D. Expose a model-facing capability/extension-discovery call, generalized
from `lmy-2004/houdini-ai`'s node/param fabrication guard and
`houdini-codemode-mcp`'s `ctx.capabilities()`/`ctx.help()` (item 2).**

- *User value*: lets the model ask "what Skills/extensions actually exist
  and what do they accept" at generation time rather than only discovering a
  mismatch after proposing a call that then fails validation - reduces
  wasted turns and reduces the chance a model's own hallucinated tool/skill
  name reaches the validator at all.
- *Current repo equivalent*: `list_skills`/`get_skill_instructions`
  meta-tools (per `__init__.py`'s doc-comment: "Skill 通过 list_skills /
  run_skill 元工具暴露给 AI") already provide skill-level discovery;
  `HoudiniInspection.node()`/`.parameter()` already provide live
  node/parameter-existence lookup, but as an **internal** helper used by
  Skills themselves (`_inspection.py`), not as a model-facing "does this
  node/parameter exist before I reference it" discovery tool.
- *Minimal port*: add a thin, explicitly read-only, already-governance-
  compatible meta-tool (e.g. `check_entity_exists(node_path, parameter_name)`)
  built directly on `HoudiniInspection`, documented to the model as the
  preferred way to confirm a name before using it in a write-tool argument -
  not a new validation layer, just making an existing internal capability
  model-callable.
- *Governance adaptation*: trivially compatible - this is a read-only
  inspection tool, same risk tier as existing allowlisted read tools
  (`get_network_structure`, etc.); no policy change needed beyond normal
  tool registration.
- *Security risk*: minimal - read-only, already-validated node-path
  arguments, same `_HOUDINI_ROOTS` scoping as any other node-path tool.
- *Adoption level*: **Adopt**.
- *Priority*: **Medium-low** (clear value, very low implementation cost,
  but addresses a UX/efficiency gap more than a governance or security gap).
- *Acceptance criteria*: (1) new tool is read-only (`risk_level` at or below
  existing read-tool tier) and present in the default external-MCP allowlist
  parity set; (2) returns a structured `{exists: bool, kind: ...}` result,
  not raw `hou` objects; (3) a test confirms calling it against a
  deliberately-fabricated node/parameter name returns `exists: false`
  without raising, matching `HoudiniInspection`'s existing error-tuple
  contract (`_inspection.py:17-25`).

### 5.3 OBSERVE (low priority / watch item)

**E. Named four-tier skill override priority (Official > Marketplace > User
> Temporary) (item 5's priority half).**

- *Rationale for Observe, not Adopt*: Houdini-Agent's current two-tier,
  prefix-namespaced coexistence model (§3.4) avoids the entire class of
  conflict-resolution bugs a priority-override scheme introduces (which
  skill "wins" when names collide, how a user is warned their local skill is
  being shadowed, how a Temporary skill expires) by simply never letting
  names collide. Adopting override-by-priority would require solving those
  problems for comparatively modest benefit (today's user base is
  single-user-per-license, not a marketplace-distribution ecosystem like
  artclaw_bridge's team-sharing model), and would reintroduce exactly the
  failure mode CONTEXT.md's "Ineligible Entry"/"Invalid Entry" distinction
  for Team Memory already shows this project is careful to avoid elsewhere
  (structural/safety invalidity vs. eligibility-policy exclusion must stay
  distinguishable).
- *Re-evaluate if*: a marketplace/shared-skill-distribution feature is
  independently planned (unrelated to this research), at which point
  priority-override conflict resolution becomes load-bearing rather than
  speculative.
- *Priority*: **Low / watch-only**, not a current action item.

**F. Cross-DCC core/adapter split with a harness-hosted plugin model akin to
`dsh-houdini`'s `cordis` wiring (item 9).**

- *Rationale for Observe, not Adopt*: Houdini-Agent's entire value
  proposition (per `README.md:12-13` and this project's own prior Landscape
  report §6) is being an **in-process Qt panel inside Houdini**, not an
  external bridge a separate harness drives. Restructuring around a
  cross-DCC core would be a different product shape, not a borrowable
  mechanism - correctly flagged as "architecturally out of scope today" in
  §4's table, consistent with the existing Landscape report's own
  §11.3.3 conclusion ("a DSH-specific native plugin is a materially
  different integration shape... that this repository does not currently
  target and is not recommended to chase").
- *Priority*: **Low / explicitly not recommended** as a near-term action.

### 5.4 REJECT (explicit non-adoption, with reason)

**G. Do not adopt a single generic code-execution tool with full unsandboxed
`hou` access (`limitsurface/houdini-codemode-mcp`'s core design) as a
replacement for, or addition alongside, the existing ~78-tool catalog.**

- *Reason*: Code Mode's own README is explicit that its governance model is
  "trust the local process" with no allow/deny list, risk ceiling, or audit
  trail for its one tool (§2.5) - directly incompatible with this
  repository's mandatory Harness contract, which evaluates every tool call
  individually. Adopting the *tool shape* (one call, full `hou`) without the
  *governance shape* that makes it safe elsewhere (loopback-only,
  single-user-workstation trust assumption explicitly accepted by that
  project) would be a straightforward regression of this repository's
  documented competitive/safety advantage (already identified in the
  existing Landscape report's §9 "What NOT To Do," reused here for
  consistency: "Do not adopt unsandboxed `execute_python`/arbitrary `hou`
  access on the external MCP path").
- *What to take instead*: items 3/4's bounded-emission *discipline* (already
  implemented per §3.2) and item 2's runtime-introspection *idea*
  (partially adopted per §5.2.D) are the parts of Code Mode's design worth
  it; the single-tool-full-`hou` *shape* is not.

**H. Do not collapse the external MCP tool catalog to one
`run_python`-style tool per the `artclaw_bridge`/`eee1723` pattern, even
though both are more "modern" by raw adoption-trend count.**

- *Reason*: `artclaw_bridge`'s own stated design philosophy (§2.3) still
  frames its Skill layer as the source of "engineering discipline," not the
  one-tool collapse itself - i.e. even its own authors do not claim the
  single-tool shape alone provides safety; the discipline lives elsewhere
  (a Skill layer whose own policy-engine depth was **not** verified in this
  pass, per §2.3's explicit flag). Collapsing Houdini-Agent's schema'd,
  individually-risk-scored tool catalog into one generic executor would
  require re-deriving, inside a single tool's argument (arbitrary code),
  all of the same per-operation risk classification the current
  `HOUDINI_TOOLS` schema list gives the Harness for free today - a strictly
  harder problem, not a simplification, for no demonstrated governance
  benefit.

## 6. Gaps / Uncertainties

- `SFKislev/Flue`'s `adapters/houdini_adapter/APP.md` (the actual Houdini
  integration surface, as opposed to the top-level framework README) was
  **not** fetched in this pass - the specific Houdini scripting-API surface
  Flue drives (likely `hython`-based, given the README's "most desktop
  applications already include a fully documented scripting interface"
  framing) is unverified; this is the one target repo where the
  Houdini-specific mechanism detail is weakest in this report, since the
  top-level README is framework-generic across all 14 supported apps.
- `IvanYangYangXi/artclaw_bridge`'s exact skill-priority **conflict-
  resolution algorithm** (e.g., whether "Marketplace overrides User" is
  resolved by skill-identity string, by category+identity, or by an
  explicit manifest precedence field) was not independently verified beyond
  the README's one-sentence claim; `docs/skills/MANIFEST_SPEC.md` and the
  actual skill-loader source (not surfaced via the README fetch) would be
  needed to confirm the mechanics precisely before a deeper port than §5.3.E's
  "observe" framing.
- `IvanYangYangXi/artclaw_bridge`'s own policy/governance depth for its
  one-tool-per-DCC `run_python`/`run_ue_python` surface (allow/deny lists,
  risk scoring, confirmation flow, if any) was explicitly not verified -
  the README's "Design Philosophy" section asserts the Skill layer provides
  "engineering discipline" but does not itself describe a policy engine;
  `mcp_server.py`-equivalent source was not located/fetched in this pass.
- `eee1723/dsh-houdini`'s actual DSH-side `cordis` plugin-registration code
  (as opposed to the `package.json`/README-level wiring already cited from
  the Landscape report) was not independently re-fetched in this session;
  the specific hook/event surface `cordis` exposes to a Houdini-mode plugin
  (as opposed to Houdini-Agent's own seven named hook points) is not
  directly comparable at the API-signature level without that source.
- No commit-history/blame investigation was performed for any of the five
  repos in this pass (the task's "必须查看...关键提交" instruction was
  satisfied at the "current primary source, verified directly" level via
  direct README/source fetches, but specific *historical* commits
  documenting the *evolution* of e.g. artclaw_bridge's four-tier priority
  scheme or houdini-ai's three-hard-rules design were not individually
  fetched/diffed - treat the mechanisms above as "verified at their current
  state," not "verified across their full history").
- `abyrvalg379/mcp-socket-houdini` (cited in §5.1.B for the `replay_last_session`
  precedent) is **not** one of this task's five target repositories; it is
  reused here, with its origin clearly marked, only because none of the five
  target repos documents a replay mechanism and it is the best available
  named precedent from the same research lineage. If item 8 needs its own
  from-scratch primary-source re-verification independent of the existing
  Landscape report's citation, that would require a separate fetch of
  `abyrvalg379/mcp-socket-houdini:README.md` not performed in this pass.

## 7. Ranked Summary (value-ordered, duplicating §5's priorities for quick reference)

1. **High** - File-queue, no-listening-port CLI command bridge as an
   additional governed transport (§5.1.A) - closes items 6+7, fully
   governance-compatible, bounded implementation cost.
2. **Medium** - Opt-in session/command replay gated on the existing
   `replay_safe` flag (§5.1.B) - closes item 8, but needs its own
   privacy-scope ADR before enabling by default.
3. **Medium** - Narrow structurally-scoped authoring tool for one workflow
   class (§5.2.C) - closes part of item 1 without touching the other 78
   tools' schemas.
4. **Medium-low** - Model-facing `check_entity_exists` capability-discovery
   tool built on existing `HoudiniInspection` (§5.2.D) - closes part of item
   2 with minimal cost.
5. **No gap, document only** - Summary→projection→artifact via
   `ToolResultStore` (§3.2) - already implemented; add one line to
   `docs/adr/` noting the Code Mode convergence, no code change.
6. **Low / watch-only** - Four-tier skill override priority (§5.3.E).
7. **Low / explicitly not recommended** - Cross-DCC core/adapter
   restructuring (§5.3.F).
8. **Reject** - Single generic code-execution tool with unsandboxed `hou`
   (§5.4.G).
9. **Reject** - Collapsing the external MCP catalog to one `run_python`-style
   tool (§5.4.H).
