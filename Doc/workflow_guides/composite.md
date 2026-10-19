# Legacy COP2 compositing workflow
<!-- tools: -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Treat COP2 as a maintenance workflow. Route new compositing and texture work to the `copernicus` guide unless an existing scene, node type, or delivery contract requires COP2.

## Decisions

- Identify the legacy dependency that prevents migration before adding COP2 nodes.
- Preserve existing resolution, planes, color management, frame range, and file-path behavior during maintenance.
- Do not translate a network to Copernicus implicitly; migration is a separate, verifiable task.

## Order of work

1. Inspect the existing network and record its inputs, outputs, planes, resolution, and frame behavior.
2. Reproduce the current result before making changes.
3. Apply one narrow repair and compare against the original output contract.
4. For new functionality, evaluate an isolated Copernicus replacement rather than expanding legacy debt.
5. Confirm path and overwrite behavior before authorizing any render or file write.

## Failure signatures

- A visually similar frame is not proof that channels, alpha, data range, or animation match.
- Unexpected resizing often originates in a node's resolution policy.
- Silent color differences commonly indicate mismatched color management or premultiplication.