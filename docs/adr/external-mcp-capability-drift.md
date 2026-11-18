# External MCP Capability Drift Controls

Date: 2026-11-10

## Status

Accepted and implemented.

## Decision

External MCP capability is represented by three deliberately separate sources:

1. The Tool Registry owns tool identity, schema, runtime, risk, mutability, and external visibility.
2. `HoudiniMCP._TOOL_DISPATCH` maps registered Houdini tools to callable runtime handlers.
3. `config/external_mcp_manifest.json` is the committed public capability snapshot filtered by the external allowlist and deny list.

These sets are not assumed equal. Internal-only tools and explicitly denied tools must remain absent from the public manifest. Any unmodelled difference fails closed.

## Drift Checks

After changing an externally visible tool, run:

```powershell
C:\rez\rez_2.112.0\Scripts\python.exe -S scripts\generate_external_mcp_manifest.py
C:\rez\rez_2.112.0\Scripts\python.exe -S scripts\generate_external_mcp_manifest.py --check
C:\rez\rez_2.112.0\Scripts\python.exe -S -m unittest tests.test_external_mcp_capabilities tests.test_tool_contracts
```

`test_committed_manifest_has_no_drift` compares the generated snapshot with the committed manifest. `test_schema_and_dispatch_contracts_model_internal_tools_explicitly` compares Registry and dispatch ownership and verifies that each mapped handler is callable.

## Consequences

- Adding a Registry entry cannot silently expose it externally.
- Adding a manifest entry without a valid Registry schema and callable dispatch handler fails validation.
- Runtime capability filtering may remove unavailable optional features, but cannot expand the committed external surface.
- Manifest generation is deterministic and must be included with any external capability change.
