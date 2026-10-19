# MPM workflow
<!-- tools: inspect_frame_range_risk, setup_dynamics_sim -->
<!-- evidence: runtime-search -->

Goal: {description}

Read the local `Doc/mpm/` knowledge corpus and use `simulation_workflow_guide` with the MPM domain. There is no local MPM auto-build blueprint, so this guide must not hand off to `setup_dynamics_sim`.

## Decisions

- Prefer MPM for cohesive elastoplastic materials and physical interaction between different materials.
- Prefer FLIP for detailed free-surface liquid when other materials are static colliders, Bullet for efficient rigid bodies, and Vellum grains for sparse dry material.
- Particle spacing, material points, grid resolution, and substeps determine memory and solve cost.

## Order of work

1. Choose the material model from behavior, not color or density alone.
2. Inspect source dimensions, sampling, material scale, initial overlap, and collider representation.
3. Build the smallest manually verified setup using exact nodes found through `search_houdini_help`.
4. Use `inspect_frame_range_risk` before `cook_sample_frames`; sample at most three explicit frames.
5. Validate material response and collisions before increasing resolution or substeps.
6. Add reconstruction and cache stages only after the material-point solve is credible.

## Failure signatures

- Material scale or source sampling inconsistent with particle spacing produces unstable or misleading behavior.
- Increasing substeps before validating collider sampling wastes time and may conceal the source defect.
- High-resolution stiff materials can be dramatically slower than Bullet or Vellum alternatives.