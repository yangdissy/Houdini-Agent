---
{"name":"cache_node_report","category":"performance","description":"Scan cache and export nodes, report output paths, frame ranges, disk existence, and modified times. Read-only; does not cook or write caches.","risk_level":"low","parameters":{"root_path":{"type":"string","description":"Root network path to scan, for example /obj, /out, or /. Defaults to /.","required":false,"default":"/"},"recursive":{"type":"boolean","description":"Whether to scan all descendants. Defaults to true.","required":false,"default":true},"check_disk":{"type":"boolean","description":"Whether to check matching files on disk. Defaults to true.","required":false,"default":true},"max_nodes":{"type":"integer","description":"Maximum nodes to inspect before truncating. Defaults to 3000.","required":false,"default":3000}},"entrypoint":"scripts/main.py:run"}
---
# Cache Node Report

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
