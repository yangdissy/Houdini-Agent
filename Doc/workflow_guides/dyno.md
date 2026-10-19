# Dynamics workflow
<!-- tools: cook_sample_frames, inspect_frame_range_risk, setup_dynamics_sim, simulation_workflow_guide -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `simulation_workflow_guide` to choose FLIP, Vellum, RBD, or MPM before designing a network. Smoke, fire, and explosions belong to the dedicated Pyro guide.

## Decisions

- Match the solver to the material behavior and required interactions; do not choose from appearance alone.
- Separate source, collision, solve, cache, and post-process stages so each boundary is inspectable.
- Use `setup_dynamics_sim` only after selecting FLIP, Vellum, or RBD. It has no MPM mode.

## Order of work

1. Inspect scene scale, source animation, collider motion, frame range, and output requirements.
2. Select one solver family and read its dedicated workflow guide.
3. Validate source geometry and attributes before building the solver chain.
4. Draft or dry-run the smallest representative setup.
5. Run `inspect_frame_range_risk`; only a complete low-risk result may proceed to `cook_sample_frames`.
6. Sample at most three explicit frames, verify the current frame is restored, then decide whether a longer cache is justified.

## Failure signatures

- Ambiguous material behavior means solver selection is not complete.
- Solver tuning cannot repair invalid scale, topology, source attributes, or collider motion.
- A successful build is not proof that geometry or fields change correctly over time.