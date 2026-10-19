---
{"name":"simulation_workflow_guide","category":"workflow","description":"Return a read-only production workflow guide for FLIP liquids, Vellum cloth/soft bodies/grains, RBD destruction, or MPM materials. Use before building a simulation to choose the solver, split source/collision/solve/cache/output stages, estimate resolution cost, find SideFX help, and define verification. Smoke, fire, and explosions are handed to setup_pyro_sim.","risk_level":"low","parameters":{"task":{"type":"string","description":"Simulation goal or effect to plan.","required":true},"domain":{"type":"string","description":"Solver family. Use auto to infer only when the task contains an unambiguous domain term.","required":false,"default":"auto","enum":["auto","flip","vellum","rbd","mpm"]},"complexity":{"type":"string","description":"simple, medium, or complex. Controls planning detail.","required":false,"default":"medium","enum":["simple","medium","complex"]}},"entrypoint":"scripts/main.py:run"}
---
# Simulation Workflow Guide

按照参数合同执行此 Skill。它只返回规划和验证指南，不修改场景；执行建图时继续使用受治理的现有 Skill 与工具。
