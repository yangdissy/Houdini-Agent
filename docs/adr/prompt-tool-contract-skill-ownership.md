# Prompt, Tool Contract, and Skill Ownership

## Status

Accepted

## Decision

- System prompt rules own stable agent behavior and safety guidance. Prompt sections are assembled explicitly and optional sections are omitted atomically when the budget is exceeded.
- Tool schemas own parameter names, types, required fields, defaults, and enums. Runtime authorization and execution semantics remain in `ToolRegistry`; MCP dispatch remains in `HoudiniMCP._TOOL_DISPATCH`.
- Error usage hints are rendered from the registered tool schema. Handwritten call signatures are not maintained separately.
- Dynamic directives report only current runtime state and the action needed to change it. They do not repeat stable guidance.
- Standard Skills use a directory containing `SKILL.md`. Discovery parses metadata and instructions without importing executable code. An optional relative `entrypoint` is imported only when `run_skill` executes that Skill.
- All 61 built-in executable Skills use the standard directory bundle. Four built-in instructions-only Skills provide read-only operation guidance and domain methods. Legacy single-file Python Skills are accepted only from user Skill directories for backward compatibility; new built-in and user Skills must use bundles.
- Instructions-only Skills may be discovered and read, but `run_skill` rejects them instead of treating Markdown as executable code.

## Domain Method Ownership

- `decompose_houdini_task` owns cross-domain module boundaries, dependencies, local feedback, and integration order. It does not prescribe SOP, COP, USD, material, or KineFX node recipes.
- `design_houdini_parameter_ui` owns artist-facing control semantics, layout choices, bindings, and compatibility guidance. Tool schemas and actual parameter mutation remain owned by ToolRegistry and MCP execution contracts.
- `handoff_houdini_network` owns edit entry points, outputs, Network Box responsibilities, comments, and scoped layout guidance. It presents validated boundaries without deciding domain correctness.
- Executable domain Skills retain ownership of business construction, version-specific blueprints, and result verification. They may recommend the method Skills without duplicating their instructions.

## Standard Skill Format

`SKILL.md` begins with JSON-compatible frontmatter between `---` markers. Required metadata is `name`, `description`, `category`, `risk_level`, and `parameters`. An executable Skill adds an entrypoint such as `scripts/main.py:run`.

The Skill name must match its directory. Entrypoints must resolve to a regular file inside that directory. Unknown metadata fields, invalid contracts, path escapes, and missing entrypoints fail closed.

Executable bundles use `scripts/main.py:run`. Shared implementation belongs in explicit private modules such as `_doc_support.py` or `_blueprint.py`; one Skill entrypoint must not import another Skill entrypoint. `draft_houdini_skill` and `install_houdini_skill` generate, validate, and atomically install this bundle format.

## Consequences

- Prompt text no longer acts as a second tool schema.
- Parameter changes propagate automatically to error usage hints.
- Skill discovery supports progressive disclosure without import-time side effects.
- Built-in category roots contain no legacy executable `.py` files. Tests enforce 61 executable descriptors plus four instructions-only descriptors.