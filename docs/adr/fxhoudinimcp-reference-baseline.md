# fxhoudinimcp Reference Baseline

The governed MCP work uses the following immutable upstream reference:

- Repository: `healkeiser/fxhoudinimcp`
- Release: `v2.28.3`
- Commit: `de2c9aeb01f075f5851e67a8d5a42283c1028dfa`
- Commit date: `2026-11-09`
- License: MIT, copyright 2026 FXHoudini-MCP Contributors
- Advertised surface at this revision: approximately 215 tools

The upstream v2.27.0 transport change introduced a Streamable HTTP session model.
Comparisons against this baseline must therefore distinguish tool-surface changes
from transport/session-lifecycle changes. Refreshes must pin a full commit SHA and
recount the tool surface from that revision rather than copying this approximate
count forward.

Files and areas to study selectively at this revision:

- `python/fxhoudinimcp/bridge.py`: HTTP bridge, connection errors, and timeouts.
- `python/fxhoudinimcp/`: FastMCP wrappers and SDK compatibility handling.
- `houdini/`: hwebserver dispatcher and main-thread `hou` handlers.
- `tools/gen_required_commands.py`: required-command manifest generation.
- Graph, geometry, LOP/USD, TOP/PDG, HDA, and Takes handlers and tests.

No upstream runtime code is vendored by this baseline. If substantial source is
copied later, the copied material must retain the upstream MIT notice and source
record required by the license.