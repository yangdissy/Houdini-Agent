# FLIP liquid workflow
<!-- tools: inspect_frame_range_risk, setup_dynamics_sim, simulation_workflow_guide -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Start with `simulation_workflow_guide` using the FLIP domain. Use `setup_dynamics_sim` only for the local starter blueprint; emission, collisions, surfacing, whitewater, and caching still require task-specific validation.

## Decisions

- Use FLIP for detailed free-surface liquid, splashes, whitewater, or surface tension. When multiple materials must interact physically, compare MPM first.
- Particle separation controls solve cost; surfacing resolution introduces a separate downstream cost.
- Validate particles before tuning the surface mesh, and validate the base liquid before adding whitewater.

## Order of work

1. Confirm source volume, scene scale, velocity, emission timing, and collider motion.
2. Build the lowest useful particle resolution and keep particle output visible.
3. Check containment, mass continuity, collision thickness, and fast-motion tunneling.
4. Use `inspect_frame_range_risk` before `cook_sample_frames`; sample at most three explicit frames.
5. Add surfacing and whitewater only after the particle solve behaves correctly.
6. Define cache and final output paths separately from the solver setup.

## Failure signatures

- Vanishing or leaking fluid points first to source representation, scale, separation, or collisions.
- Thin or fast colliders may require better collision representation or substeps, not more surface detail.
- A poor mesh over good particles is a surfacing problem, not a reason to rebuild the solve.