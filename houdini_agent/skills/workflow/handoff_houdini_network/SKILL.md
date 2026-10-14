---
{"name":"handoff_houdini_network","description":"Guide a Houdini network handoff with clear edit entry points, outputs, grouping, comments, and scoped layout without changing network behavior.","category":"workflow","risk_level":"low","parameters":{}}
---
# Handoff Houdini Network

Use this method when another artist must find, understand, and continue editing a completed or multi-branch Houdini network. Temporary diagnostics, a single parameter edit, and short obvious chains do not require presentation work.

## Expose the editing contract

Identify the authoritative input, artist control, replaceable processing modules, final output, and any cache or export boundary. Describe what each entry consumes, what it changes, and which downstream result it affects. Do not infer responsibilities from node names or types when connections and actual behavior provide better evidence.

Use Network Boxes for nodes that form one editing responsibility. Use box comments and clear node names for purpose, expected inputs, output role, and stable restrictions. Preserve existing user layout, comments, colors, and unrelated branches. A node should not be reorganized merely to make the graph look uniform.

## Apply layout narrowly

Inspect positions and existing boxes before changing presentation. Preview layout changes and pass the exact `node_paths` for the current module; never lay out an entire network for cosmetic reasons. Verify box membership, comments, node positions, connections, and final output after presentation changes.

Module boundaries come from `decompose_houdini_task` or the relevant domain workflow. Artist-facing controls come from `design_houdini_parameter_ui`. This Skill presents already validated responsibilities; it does not decide SOP, COP, USD, material, simulation, or rig correctness.