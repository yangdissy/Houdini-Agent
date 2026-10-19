# Procedural prop workflow
<!-- tools: procedural_modeling_guide -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `procedural_modeling_guide` for the network method and `design_houdini_parameter_ui` only after the prop's art-directable controls are known.

## Decisions

- Separate silhouette, construction, repeated elements, damage/detail, materials, UVs, LODs, collision, and output.
- Expose artist decisions rather than internal node parameters.
- Choose unique geometry or `setup_instance_scatter` from variation, memory, editability, and renderer requirements.

## Order of work

1. Define scale, axes, pivot, naming, variation range, output contexts, and delivery contract.
2. Build silhouette and primary construction at low density.
3. Add repeated parts and controlled variation with stable seeds and IDs.
4. Validate topology, normals, UVs, material groups, bounds, pivot, and named outputs.
5. Add detail, LOD, collision, packaging, and export only after the core controls are stable.

## Failure signatures

- Difficult revisions indicate that artist decisions are buried inside implementation parameters.
- Unstable variation points to changing topology, IDs, or random seeds.
- Correct geometry with bad downstream placement usually indicates pivot, scale, or axis-contract errors.