# Houdini Digital Asset workflow
<!-- tools: design_houdini_parameter_ui, extract_network_contract -->
<!-- evidence: local-knowledge -->
<!-- sources: Doc/workflow_guide_migration_matrix.md -->

Goal: {description}

Use `extract_network_contract` before deciding to package a network. Use `design_houdini_parameter_ui` for the public control contract; neither Skill creates or modifies an HDA definition.

## Decisions

- Create an HDA only when multiple instances must share a versioned interface or the asset must be distributed.
- Treat type name, namespace, version, inputs, outputs, parameters, menu tokens, defaults, callbacks, sections, and library path as compatibility contracts.
- Keep reusable implementation separate from scene-specific paths, selections, and credentials.

## Order of work

1. Prove the source network and extract its boundary contract.
2. Remove or parameterize fragile absolute paths and hidden scene dependencies.
3. Define the smallest artist-facing interface without renaming established internal parameter names or menu tokens.
4. Create or update the definition only after explicitly confirming library path, namespace, version, and overwrite behavior.
5. Test a fresh instance, existing-instance compatibility, input changes, save/reload, and distribution location.

## Failure signatures

- An asset that works only in the authoring scene still contains hidden dependencies.
- Broken existing instances usually indicate incompatible parameter, menu-token, input, or type-name changes.
- Editing a shared definition without confirming the target library can affect unrelated scenes and users.