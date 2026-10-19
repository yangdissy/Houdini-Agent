# RBD destruction workflow
<!-- tools: inspect_frame_range_risk, setup_dynamics_sim, simulation_workflow_guide -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `simulation_workflow_guide` with the RBD domain. Use `setup_dynamics_sim` only after fracture, packed-piece, and constraint requirements are understood.

## Decisions

- Separate fracturing, packed pieces, physical properties, constraints, collisions, solve, debris, and cache.
- Bullet is the default for efficient rigid pieces; compare MPM only when deformation or multi-material interaction is essential.
- Collision geometry should be no more detailed than the visible motion requires.

## Order of work

1. Verify piece packing, unique names, transforms, and fracture scale.
2. Inspect constraint endpoints and attributes before connecting the solver.
3. Test a small representative subset against simplified colliders.
4. Use `inspect_frame_range_risk` before `cook_sample_frames`; sample at most three explicit frames.
5. Confirm active states, collisions, and constraint breaking before adding debris.
6. Establish cache and output contracts only after the base solve is reproducible.

## Failure signatures

- Unpacked or malformed pieces make transforms and collisions unreliable.
- Missing or mismatched names disconnect pieces from constraints.
- Increasing substeps cannot compensate for invalid constraints or excessive collision detail.