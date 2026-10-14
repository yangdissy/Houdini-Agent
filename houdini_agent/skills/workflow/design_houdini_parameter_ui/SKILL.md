---
{"name":"design_houdini_parameter_ui","description":"Guide stable artist-facing Houdini controls, parameter layout, bindings, and compatibility without automatically modifying parameter interfaces.","category":"workflow","risk_level":"low","parameters":{}}
---
# Design Houdini Parameter UI

Use this method when a procedural network needs a stable artist-facing control interface or an existing control surface needs review. Ordinary parameter assignment and internal implementation parameters do not require a separate UI design pass.

## Define controls before widgets

For each public control, record its stable internal name, user label, purpose, unit, value domain, default, dependencies, driven outputs, and validation method. Expose user decisions rather than mirroring internal node parameters. Keep a single parameter simple instead of adding unnecessary tabs, folders, or switches.

Inspect existing parameters, expressions, keyframes, menu tokens, references, locked state, and current controller before changing an established interface. Existing internal names and menu tokens are compatibility contracts; changing a label does not require renaming them.

Choose an existing parameter when it already expresses the control. Use spare parameters for a scene-specific control surface. Consider an HDA definition only when instances must share a versioned interface or be distributed as a reusable type. Select folders, menus, toggles, ramps, multiparms, and conditional visibility from the user's operation, not from a fixed visual template.

The relevant domain Skill owns what a control actually drives and whether the business output is correct. `decompose_houdini_task` owns module boundaries, and `handoff_houdini_network` owns how the proven control entry is presented for continued editing. This Skill is design guidance and does not itself modify `ParmTemplateGroup` or package an HDA.