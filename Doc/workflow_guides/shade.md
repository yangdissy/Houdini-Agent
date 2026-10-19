# Material and shading workflow
<!-- tools: setup_material_lookdev -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `setup_material_lookdev` for a MaterialX/Karma or classic SOP material blueprint. It does not modify the scene.

## Decisions

- Detect the renderer and material context before choosing nodes. Prefer MaterialX for current Karma/USD work.
- Define texture color spaces, scalar versus color data, UV requirements, displacement bounds, and binding targets explicitly.
- Keep shader construction, material binding, preview lighting, and final rendering independently verifiable.

## Order of work

1. Inspect renderer, geometry attributes, UVs, material paths, and texture metadata.
2. Build a minimal material under neutral preview lighting.
3. Validate base color, roughness, metalness, normals, opacity, and displacement one channel at a time.
4. Verify material binding on the final composed geometry or USD prims.
5. Compare preview and target renderer before adding expensive shading features.

## Failure signatures

- Incorrect roughness or normals often indicate wrong color space or channel interpretation.
- A valid material that renders unassigned points to binding paths or composition.
- Displacement artifacts point first to scale, bounds, subdivision, and normal orientation.