# fxhoudinimcp Reference Baseline

The governed MCP work uses the following immutable upstream reference:

- Repository: `healkeiser/fxhoudinimcp`
- Release: `v2.21.0`
- Commit: `7405dc7bedaf9f842c0570cbdda02d47cf96c70e`
- Commit date: `2026-09-23T21:41:24Z`
- License: MIT, copyright 2026 FXHoudini-MCP Contributors
- Advertised surface: 206 tools, 8 resources, 9 prompts, and 31 workflow guides

Files and areas to study selectively at this revision:

- `python/fxhoudinimcp/bridge.py`: HTTP bridge, connection errors, and timeouts.
- `python/fxhoudinimcp/`: FastMCP wrappers and SDK compatibility handling.
- `houdini/`: hwebserver dispatcher and main-thread `hou` handlers.
- `tools/gen_required_commands.py`: required-command manifest generation.
- Graph, geometry, LOP/USD, TOP/PDG, HDA, and Takes handlers and tests.

No upstream runtime code is vendored by this baseline. If substantial source is
copied later, the copied material must retain the upstream MIT notice and source
record required by the license.