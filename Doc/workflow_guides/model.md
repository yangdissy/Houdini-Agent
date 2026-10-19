# Procedural modeling workflow
<!-- tools: procedural_modeling_guide, search_houdini_help -->
<!-- evidence: packaged-help -->
<!-- nodes: sop/attribwrangle -->

Goal: {description}

Read `sop/attribwrangle.txt` and the relevant modeling pages found with `search_houdini_help`.

## Decisions

- Prefer native SOP nodes and visible branches over opaque VEX or Python.
- Keep base forms, masks, detailing, instancing, cleanup, UVs, and output independently inspectable.
- Use `procedural_modeling_guide` for the local method and `decompose_houdini_task` for genuinely complex assets.

## Order of work

1. Inspect the existing source and decide the output contract.
2. Block large forms at low density.
3. Add named branches for selection, detail, copies, cleanup, and UVs.
4. Verify each branch before merging.
5. Finish at a clearly named output node and validate visible geometry, groups, attributes, normals, and UVs.

## Failure signatures

- Hard-to-change geometry usually indicates hidden constants or an overly opaque wrangle.
- Copy failures usually originate in template attributes or source transforms.
- A correct edited node with a wrong viewport result often means the displayed downstream branch was not inspected.