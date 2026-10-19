# Rendering workflow
<!-- tools: setup_render -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `setup_render` only after detecting the intended renderer. It returns a Karma LOP or classic Mantra ROP blueprint; it does not build nodes or render images.

## Decisions

- Prefer Karma for current USD/Solaris workflows. Use Mantra only when an existing classic scene or delivery requirement needs it.
- Separate camera, lighting, materials, render settings, products, output path, and execution.
- A viewport preview is evidence about framing and broad look, not proof of final-render equivalence.

## Order of work

1. Inspect scene context, renderer, camera, resolution, frame range, color management, and delivery format.
2. Validate geometry visibility, material assignments, lights, and camera before final settings.
3. Obtain and dry-run the renderer-specific blueprint through governed build tools.
4. Render or capture the cheapest representative preview.
5. Confirm expanded output paths, overwrite policy, frame range, and cost before authorizing final rendering.

## Failure signatures

- Missing objects point first to context, purpose, visibility, layer composition, or camera clipping.
- Missing materials point first to binding paths and renderer compatibility.
- Black or noisy output requires separate checks for lights, exposure, sampling, and color management.