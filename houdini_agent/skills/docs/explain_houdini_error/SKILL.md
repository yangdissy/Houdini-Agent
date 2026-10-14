---
{"name":"explain_houdini_error","category":"docs","description":"Look up Houdini, VEX, USD, Karma, or Python error text in shipped documentation. Returns evidence and search terms without claiming an unsupported diagnosis. Read-only.","risk_level":"low","parameters":{"error_text":{"type":"string","description":"Error or warning text copied from Houdini.","required":true},"top_k":{"type":"integer","description":"Maximum documentation matches. Defaults to 8.","required":false,"default":8}},"entrypoint":"scripts/main.py:run"}
---
# Explain Houdini Error

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
