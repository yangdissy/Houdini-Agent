---
{"name":"setup_pyro_sim","category":"workflow","description":"Return a node-building BLUEPRINT for a standard SOP-based Pyro (smoke/fire) simulation. Does NOT modify the scene — it returns a recipe (nodes + connections + parameters) that you then build by calling create_nodes_batch (pass the blueprint's 'nodes' and 'connections' directly). Use when the user asks to 'set up pyro', 'make smoke/fire sim', or similar one-click sim requests. After building, the source node's output should feed the first blueprint node.","risk_level":"normal","parameters":{"source_node_path":{"type":"string","description":"Path of the existing SOP node providing emission geometry (e.g. '/obj/geo1/sphere1'). Its output feeds the pyro source.","required":true},"sim_type":{"type":"string","description":"'smoke' or 'fire'. Fire enables temperature/flame emission. Default 'smoke'.","required":false,"default":"smoke"},"division_size":{"type":"number","description":"Voxel size for the sim volume. Smaller = higher res / slower. Default 0.1.","required":false,"default":0.1}},"entrypoint":"scripts/main.py:run"}
---
# Setup Pyro Sim

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
