# Muscles and tissue workflow
<!-- tools: inspect_frame_range_risk -->
<!-- evidence: runtime-search -->

Goal: {description}

There is no local one-call muscle blueprint. Identify the current tissue workflow or an explicit legacy setup through `search_houdini_help` before selecting nodes or parameters.

## Decisions

- Separate anatomical surfaces, muscle geometry, attachments, tissue layers, skin deformation, collisions, solve, and cache.
- Prefer the current tissue workflow for new work; preserve legacy systems only when an existing asset requires them.
- Validate anatomy, scale, rest state, and attachment behavior before changing solver quality.

## Order of work

1. Inspect skeleton motion, muscle placement, skin topology, scale, and rest transforms.
2. Establish attachments and collision relationships on a small representative region.
3. Validate deformation through extreme poses before simulating tissue detail.
4. Use `inspect_frame_range_risk` before `cook_sample_frames`; sample at most three explicit poses or frames.
5. Add secondary tissue, skin sliding, quality, and cache stages only after the base deformation is stable.

## Failure signatures

- Sliding or detached muscles point first to attachment regions and rest state.
- Volume loss or intersections may come from anatomy or collision setup rather than solver quality.
- Increasing substeps before testing extreme poses raises cost without proving the deformation contract.