# KineFX character workflow
<!-- tools: setup_kinefx_pipeline -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `setup_kinefx_pipeline` for skeleton rig, capture, or retarget blueprints. It does not modify the scene. Route new procedural character work through KineFX or an explicitly validated APEX path rather than deprecated object-level bone workflows.

## Decisions

- Identify whether the task is skeleton construction, rig posing, capture, deformation, retargeting, or animation transfer.
- Preserve stable joint names, hierarchy, rest transforms, and coordinate conventions across every stage.
- Treat APEX as a distinct current system requiring its own verified nodes and graph contract; do not guess an APEX translation.

## Order of work

1. Inspect skeleton topology, names, transforms, scale, orientation, and rest pose.
2. Select one mode and obtain the corresponding blueprint.
3. Validate joints and transforms before capture or retarget operations.
4. Test deformation or retargeting on a small representative motion range.
5. Preserve the original skeleton and animation branch until equivalence is verified.

## Failure signatures

- Twisted or offset joints usually indicate rest-transform, orientation, or coordinate mismatches.
- Retarget drift often begins with hierarchy or naming correspondence, not animation curves.
- Correct controls with wrong deformation point to capture weights or rest geometry.