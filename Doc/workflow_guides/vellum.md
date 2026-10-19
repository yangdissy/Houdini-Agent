# Vellum workflow
<!-- tools: inspect_frame_range_risk, simulation_workflow_guide -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `simulation_workflow_guide` with the Vellum domain, then use `setup_dynamics_sim` only for a cloth, softbody, or grain starter blueprint.

## Decisions

- Choose the constraint model from the source geometry and intended deformation before tuning stiffness.
- Point count and constraint count establish the cost floor; substeps and constraint iterations multiply it.
- Dry sparse grains usually favor Vellum; cohesive chunky material or multi-material interaction may favor MPM.

## Order of work

1. Inspect scale, topology, thickness, normals, initial intersections, and collider motion.
2. Build constraints and inspect their attributes before solving.
3. Run at draft resolution with simple collision geometry.
4. Use `inspect_frame_range_risk` before `cook_sample_frames`; sample at most three explicit frames.
5. Tune constraint behavior before increasing substeps, iterations, or geometry density.
6. Add post-process and cache stages only after the solve is stable.

## Failure signatures

- Excessive stretching usually indicates the wrong constraint model or inadequate iterations, not only low stiffness.
- Explosive motion points first to intersections, bad scale, or abrupt collider motion.
- Solver tuning around malformed constraint attributes hides the setup defect instead of fixing it.