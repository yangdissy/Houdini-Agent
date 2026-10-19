# Import, cache, and export workflow
<!-- tools: setup_cache_pipeline -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `setup_cache_pipeline` for a versioned File Cache blueprint and `setup_export_pipeline` for Alembic, USD, FBX, BGEO, or VDB delivery. Neither Skill writes files.

## Decisions

- Choose format from the receiving application, required attributes, hierarchy, time sampling, units, and editability.
- Separate source validation, path/version policy, serialization, file writing, and read-back verification.
- Treat environment expansion, overwrite policy, frame range, and destination ownership as explicit approval boundaries.

## Order of work

1. Inspect source topology, attributes, hierarchy, units, axes, frame dependence, and bounds.
2. Define format, versioned destination, frame range, naming, and overwrite policy.
3. Obtain the cache or export blueprint and dry-run its nodes through governed tools.
4. Confirm expanded paths and estimated output scope before authorizing writes.
5. Read back representative outputs and compare counts, attributes, transforms, bounds, and frame changes.

## Failure signatures

- Successful file creation is not proof that the delivery contract survived serialization.
- Static output from animated input often indicates frame-range or time-sampling mistakes.
- Wrong placement usually indicates units, axes, hierarchy, or transform baking differences.