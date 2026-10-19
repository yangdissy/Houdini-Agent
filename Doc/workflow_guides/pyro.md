# Pyro workflow
<!-- tools: cook_sample_frames, inspect_frame_range_risk, search_houdini_help, setup_pyro_sim -->
<!-- evidence: packaged-help -->
<!-- nodes: sop/pyrosource, sop/pyrosolver -->

Goal: {description}

Read `sop/pyrosource.txt` and `sop/pyrosolver.txt` with `search_houdini_help` before improvising a setup.

## Decisions

- Establish source attributes and collision geometry before tuning the solver.
- Voxel size controls the cost model. Start coarse and request approval before increasing resolution.
- Use `setup_pyro_sim` for the local blueprint, then execute its recipe through harness-managed tools.

## Order of work

1. Inspect source geometry, scale, animation, and intended density, temperature, and flame fields.
2. Build or dry-run the low-resolution SOP Pyro blueprint.
3. Verify node types, parameters, connections, and display output.
4. Run `inspect_frame_range_risk`; only a low and complete result may proceed to `cook_sample_frames`.
5. Sample no more than three frames and confirm the current frame is restored.
6. Increase resolution only after motion, collisions, and shaping read correctly.

## Failure signatures

- Missing emission usually means the source fields or rasterization are wrong, not that more turbulence is needed.
- A clipped plume points to bounds or resizing before it points to shaping.
- Slow iteration points first to voxel size, active bounds, and cache strategy.