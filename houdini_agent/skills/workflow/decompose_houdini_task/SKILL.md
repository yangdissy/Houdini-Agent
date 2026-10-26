---
{"name":"decompose_houdini_task","description":"Guide complex Houdini work into independently editable, observable modules with explicit dependencies and integration checks.","category":"workflow","risk_level":"low","parameters":{}}
---
# Decompose Houdini Task

Use this method when a Houdini task contains multiple parts, subsystems, stages, or deliverables whose dependencies affect how work should proceed. A single parameter edit, isolated query, or short linear node chain does not need decomposition.

## Define modules around change and feedback

Group work that changes together. Separate work that users can replace, refine, diagnose, or validate independently. Node count, code length, and network context do not determine module boundaries.

For each module, identify:

- its purpose and user-visible result;
- required inputs and external dependencies;
- produced outputs and downstream consumers;
- the node, network, or control where users continue editing;
- a local check that can fail before downstream work begins;
- an integration check for every affected consumer.

Build and inspect one useful dependency unit before expanding work that depends on unresolved shape, data, timing, or interface decisions. Preserve the overall goal while using observed output to choose the next step.

When the overall shape or connection is still unclear, use a simple proxy to settle the interface, then replace it with the formal module. Keep the proxy recognizable and the output interface stable, and do not treat observations of the proxy as covering the formal module.

For repeated structures, treat the complete source and its layout as two editing responsibilities. Derive shared continuous boundaries from the same curve, surface, or interface output instead of duplicating formulas, and re-check every consumer after the source changes.

## Delegate domain decisions

Use the matching executable workflow Skill for SOP, COP, materials, USD, simulation, export, PDG, or KineFX construction. This Skill does not prescribe node recipes. Use `design_houdini_parameter_ui` when a stable artist-facing control interface is required, and `handoff_houdini_network` after module boundaries and outputs are proven.

Do not convert every task into a fixed checklist. Keep tightly coupled feedback processes together, and do not split simple work merely to create more stages.