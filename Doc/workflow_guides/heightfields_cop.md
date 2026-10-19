# Copernicus heightfield workflow
<!-- tools: setup_copernicus_pipeline -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md, Doc/copernicus_knowledge_base.txt -->

Goal: {description}

Use the local Copernicus knowledge corpus and `setup_copernicus_pipeline` only when terrain data is being processed as images or planes. The Skill returns a blueprint and does not write images.

## Decisions

- Confirm whether the task needs image-space terrain processing or SOP world-space terrain geometry.
- Define plane names, value ranges, resolution, color space, border behavior, and output encoding before building.
- Preserve height precision; do not normalize or color-transform height data accidentally.

## Order of work

1. Inspect incoming resolution, planes, numeric range, and coordinate convention.
2. Separate height, masks, normals, and display-only previews.
3. Validate each operation at low resolution and inspect edge behavior.
4. Define conversion back to SOP terrain or disk output explicitly.
5. Authorize any file write separately from creation of the Copernicus blueprint.

## Failure signatures

- Incorrect elevation after round-tripping usually indicates range, data type, or normalization loss.
- Seams and border artifacts usually originate in wrap or border policy.
- A correct-looking preview can still contain invalid numeric height data.