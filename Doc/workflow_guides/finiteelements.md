# Finite element workflow
<!-- tools: cook_sample_frames, inspect_frame_range_risk, search_houdini_help -->
<!-- evidence: runtime-search -->

Goal: {description}

There is no local finite-element auto-build blueprint and no dedicated packaged workflow scope. Use `search_houdini_help` to locate the exact FEM or solid-object pages for the active Houdini version before selecting nodes or parameters.

## Decisions

- Use FEM when volumetric deformation and material response require a finite-element solid model.
- Compare Vellum for efficient soft bodies and MPM for elastoplastic or multi-material behavior before accepting FEM cost.
- Separate source preparation, tetrahedralization, material regions, constraints, collisions, solve, surface transfer, and cache.

## Order of work

1. Inspect scale, topology, watertightness, thickness, rest state, and intended material behavior.
2. Validate tetrahedral quality and material-region assignment on a simple static sample.
3. Add constraints and collision geometry before increasing mesh density.
4. Run `inspect_frame_range_risk`; only a complete low-risk result may proceed to `cook_sample_frames`.
5. Sample at most three explicit frames and verify the current frame is restored.
6. Transfer deformation to render geometry and define cache output only after the coarse solve is stable.

## Failure signatures

- Inversion or explosive motion points first to tet quality, scale, rest state, constraints, or collisions.
- Excessive stiffness or softness may come from unit assumptions and material regions, not only one solver parameter.
- Increasing mesh density before validating boundary conditions multiplies cost without fixing setup errors.