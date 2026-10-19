# TOP and PDG workflow
<!-- tools: setup_pdg_batch_pipeline -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `setup_pdg_batch_pipeline` for a wedge, ROP execution, output collection, and retry blueprint. It does not cook work items, run external processes, or write files.

## Decisions

- Define work-item inputs, attributes, expected outputs, failure policy, and retry rules before graph construction.
- Keep graph generation separate from cooking; external execution remains separately authorized.
- Prefer deterministic paths and explicit dependencies over callbacks with hidden side effects.

## Order of work

1. Inspect the target ROP or cache node and its path expansion over representative frames and wedges.
2. Define wedge attributes and expected output uniqueness.
3. Build the smallest graph and generate work items without cooking them.
4. Inspect dependencies, commands, environments, output paths, and collision risks.
5. Authorize execution separately, then validate collected outputs and failed-item reporting.

## Failure signatures

- Overwritten outputs usually indicate non-unique paths across work items.
- Missing dependencies produce races or consumers running before files exist.
- Retrying nondeterministic or invalid work items hides the underlying contract failure.