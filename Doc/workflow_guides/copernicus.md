# Copernicus workflow
<!-- tools: setup_copernicus_pipeline -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md, Doc/copernicus_knowledge_base.txt -->

Goal: {description}

Use `setup_copernicus_pipeline` for a texture-generation and channel-packing blueprint. It does not modify the scene or write images.

## Decisions

- Define resolution, planes, channels, color space, bit depth, border behavior, and output format before building.
- Keep data planes such as height, normals, masks, and IDs distinct from display-referred color.
- Prefer Copernicus for new compositing and texture workflows; use legacy COP2 only for explicit maintenance work.

## Order of work

1. State the input and output contract for every plane.
2. Build generators and transforms at a small representative resolution.
3. Inspect intermediate planes and channel packing before adding output nodes.
4. Validate color transforms only on color data.
5. Confirm path expansion and overwrite policy before authorizing image writes.

## Failure signatures

- Missing output channels usually indicate a plane-name or packing mismatch.
- Washed-out or clipped data often comes from applying color transforms to non-color planes.
- Resolution-dependent changes point to filtering, kernel size, or coordinate-space assumptions.