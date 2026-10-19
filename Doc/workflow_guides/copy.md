# Copy and instancing workflow
<!-- tools: setup_instance_scatter -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `setup_instance_scatter` when the task needs a SOP or USD point-instancing blueprint. It does not modify the scene.

## Decisions

- Choose copies versus instances from editability, memory, renderer, and variation requirements.
- Treat template points and their attributes as the instance contract: position, orientation, scale, variant, ID, and visibility.
- Keep source transforms, template generation, attribute authoring, copying, and output independently inspectable.

## Order of work

1. Inspect source geometry transforms, pivot, bounds, units, and packed state.
2. Inspect template-point count and attributes before copying.
3. Test one source and a small point set before adding variants or high counts.
4. Validate orientation, scale, deterministic IDs, and variant distribution.
5. Check bounds, memory behavior, viewport representation, and final renderer compatibility.

## Failure signatures

- Wrong orientation usually begins with missing or conflicting orientation attributes or source transforms.
- Unexpected scale often combines source scale with template scale twice.
- Changing variants between evaluations indicates unstable point IDs or random seeds.