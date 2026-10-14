---
{"name":"setup_pdg_batch_pipeline","category":"workflow","description":"Return a TOP network blueprint for wedges, ROP execution, output collection, and retries. Does not cook work items or write files.","risk_level":"normal","parameters":{"target_node_path":{"type":"string","description":"Existing ROP or cache node to batch.","required":true},"wedge_count":{"type":"integer","description":"Number of variations; default 4.","required":false,"default":4},"failure_policy":{"type":"string","description":"fail or continue; default fail.","required":false,"default":"fail"}},"entrypoint":"scripts/main.py:run"}
---
# Setup Pdg Batch Pipeline

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
