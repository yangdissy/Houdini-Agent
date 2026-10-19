# SOP heightfield terrain workflow
<!-- tools: setup_heightfield_terrain -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md, Doc/heightfields_knowledge_base.txt -->

Goal: {description}

Use `setup_heightfield_terrain` for a terrain blueprint only after world size, resolution, masks, erosion, scattering, and output requirements are explicit. The Skill does not modify the scene.

## Decisions

- Use SOP heightfields for world-space terrain geometry, erosion, masks, scattering, and terrain export.
- Keep this workflow separate from Copernicus heightfield image processing.
- Resolution and world size jointly determine voxel size, memory use, and feature scale.

## Order of work

1. Define terrain extent, target voxel size, units, output format, and downstream use.
2. Build broad forms before adding erosion or high-frequency detail.
3. Keep masks named and inspectable; verify their ranges before they drive later stages.
4. Run erosion at draft resolution and validate flow, debris, and boundary behavior.
5. Prepare scattering and export from stable masks, then validate the final terrain bounds and layers.

## Failure signatures

- Features at the wrong scale usually indicate inconsistent world size or voxel size.
- Flat or extreme downstream effects often begin with an empty, inverted, or unnormalized mask.
- Raising resolution before validating broad forms multiplies cost without improving the terrain design.