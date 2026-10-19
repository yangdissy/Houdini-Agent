# Grain simulation workflow
<!-- tools: inspect_frame_range_risk, simulation_workflow_guide -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `simulation_workflow_guide` to select Vellum or MPM before building. The word "grain" alone is not enough to choose a solver.

## Decisions

- Use Vellum grains for sparse, dry, non-cohesive material and efficient small-scale effects.
- Use MPM for cohesive chunks such as snow or soil, dense material, or interaction with other simulated materials.
- Treat particle size, packing, friction, cohesion, boundaries, and source scale as an explicit material contract.

## Order of work

1. Decide whether grains should flow independently, clump, deform, or interact with another material.
2. Route to the Vellum or MPM guide and inspect source packing and collider scale.
3. Test a small quantity at coarse resolution before expanding the source region.
4. Use `inspect_frame_range_risk` before `cook_sample_frames`; sample at most three explicit frames.
5. Validate rest behavior, collision containment, and material response before caching.

## Failure signatures

- Crumbling cohesive material may indicate Vellum was chosen where MPM is a better fit.
- Slow sparse grains may indicate MPM grid cost is unnecessary.
- Unstable piles point first to scale, overlap, boundaries, particle size, and friction.