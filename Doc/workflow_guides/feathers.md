# Feather workflow
<!-- tools: search_houdini_help -->
<!-- evidence: runtime-search -->

Goal: {description}

There is no local feather auto-build blueprint. Feather tools vary across the three supported Houdini builds, so verify exact node availability with `search_houdini_help` and `get_node_card` before construction.

## Decisions

- Separate feather template construction, barb shape, attributes, placement, interpolation, clumping, deformation, collision cleanup, render representation, and export.
- Work with a few representative feathers before distributing them across a groom.
- Preserve stable skin coordinates, feather IDs, orientation, and rest attributes through deformation and caching.

## Order of work

1. Inspect skin topology, normals, UVs, scale, rest state, and deformation.
2. Build and validate one template's shaft, barbs, width, orientation, and material attributes.
3. Test placement and interpolation on a small patch before full coverage.
4. Validate deformation through extreme poses, then resolve intersections and clumping.
5. Add render density, LOD, caching, and export only after template and motion contracts are stable.

## Failure signatures

- Flipped or misaligned feathers point first to orientation, skin normals, or rest-space conventions.
- Swimming placement indicates unstable skin attachment or changed topology.
- Dense coverage hides template and interpolation defects while making diagnosis more expensive.