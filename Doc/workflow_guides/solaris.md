# Solaris and USD scene assembly workflow
<!-- tools: search_houdini_help, usd_scene_assembly_guide -->
<!-- evidence: packaged-help -->
<!-- nodes: lop/reference, lop/sublayer -->

Goal: {description}

Read `lop/reference.txt`, `lop/sublayer.txt`, and relevant composition pages found with `search_houdini_help`.

## Decisions

- Plan asset inputs, layout, materials, lights, camera, render settings, and output as separate LOP stages.
- Prefer references, sublayers, SOP Import, Material Library, and Assign Material over Python-authored USD edits.
- Use `usd_scene_assembly_guide` for the local module and verification contract.

## Order of work

1. Inspect the current layer stack and prim hierarchy.
2. Establish references and SOP imports before lookdev.
3. Build materials and verify binding prim paths.
4. Add lights and camera, then validate in viewport or Hydra preview.
5. Add final render settings and disk output only after composition is correct.

## Failure signatures

- Missing geometry points to composition, payload, purpose, or prim-path issues before shading.
- Missing materials usually indicate a binding path mismatch or a material outside the composed stage.
- Renderer differences should be isolated in preview before spending final-render time.