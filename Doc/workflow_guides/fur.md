# Fur and hair workflow
<!-- tools: search_houdini_help -->
<!-- evidence: runtime-search -->

Goal: {description}

There is no local fur auto-build blueprint. Use `search_houdini_help` to verify the grooming system and exact nodes for the current Houdini version.

## Decisions

- Separate skin preparation, guide creation, guide editing, interpolation, attributes, deformation, simulation, render geometry, shading, and export.
- Keep guide density low enough for interactive art direction; render-hair density belongs downstream.
- Preserve stable skin coordinates and guide IDs across animation and caching.

## Order of work

1. Validate skin topology, normals, UVs, scale, motion, and rest state.
2. Create sparse guides and verify direction, length, clumping regions, and parting.
3. Test deformation on extreme poses before increasing guide or hair density.
4. If simulation is required, validate collisions and a small guide subset before sampled cooks.
5. Build render geometry and shading only after guides are stable; authorize cache and export writes separately.

## Failure signatures

- Swimming guides usually indicate unstable skin attachment, topology, or rest coordinates.
- Kinks and flips often begin with guide direction, orientation, or deformation discontinuities.
- Dense render hair cannot repair sparse guides with incorrect form or motion.