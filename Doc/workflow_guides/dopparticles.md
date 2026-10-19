# Particle dynamics workflow
<!-- tools: inspect_frame_range_risk, simulation_workflow_guide -->
<!-- evidence: runtime-search -->

Goal: {description}

Use `simulation_workflow_guide` only when the requested effect overlaps its solver domains. For general particle dynamics, find the exact POP and DOP workflow through `search_houdini_help` before naming nodes or parameters.

## Decisions

- Define emission, inherited velocity, forces, collisions, attributes, state changes, and output as separate concerns.
- Prefer the simplest context that exposes the required behavior; do not add a full DOP network solely from habit.
- Particle count, neighbor operations, collision complexity, and substeps establish the main cost model.

## Order of work

1. Inspect source points, IDs, emission timing, velocity, lifetime, and scene scale.
2. Add one force or behavior at a time and verify its affected population.
3. Validate collision representation and fast motion before increasing particle count.
4. Use `inspect_frame_range_risk` before `cook_sample_frames`; sample at most three explicit frames.
5. Confirm IDs and required attributes survive into the output and cache stages.

## Failure signatures

- Missing particles usually begin with emission timing, source selection, lifetime, or display state.
- Unexpected force response often comes from attribute scope or population selection.
- Collision tunneling points to collision representation and time resolution before particle density.