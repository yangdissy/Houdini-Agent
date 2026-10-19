# Workflow Guide Migration Matrix

This document governs migration of the 31 workflow guides from
`healkeiser/fxhoudinimcp` into Houdini-Agent's on-demand knowledge layer.
It is a migration inventory, not permission to copy the upstream prose or to
expand the Agent's execution privileges.

## Source and licensing

- Upstream repository: `https://github.com/healkeiser/fxhoudinimcp`
- Upstream directory: `python/fxhoudinimcp/prompts/markdown/workflows/`
- Inventory authority: upstream `tests/test_prompt_vocab.py::_FILE_CONTEXTS`;
  its test requires every shipped workflow Markdown file to be listed.
- Inventory count: 31 workflow files.
- Upstream license: MIT, copyright 2026 FXHoudini-MCP Contributors.
- Migration policy: rewrite and adapt each guide for this repository's tools,
  supported Houdini builds, safety model, and local help archives. Preserve the
  license notice and source attribution wherever copied expression or generated
  upstream material is retained. Prefer independently written local guidance.

## Local contract

- Workflow guide knowledge lives under `Doc/workflow_guides/` and is loaded only
  when requested.
- `houdini_agent/skills/workflow/get_workflow_guide/` owns guide lookup,
  rendering, generation support, and executable audits; it does not own the
  guide knowledge assets.
- All factual help citations must resolve against the archives in `Doc/`.
- All declared node types must exist in each applicable catalog under
  `Doc/node_catalog/` for Houdini 20.0.688, 20.5.684, and 21.0.596, or carry an
  explicit version constraint supported by the guide auditor.
- Tool and Skill references must resolve to local callable names. An upstream
  tool name is never migrated as if it were available locally.
- Guides provide decisions and verification order only. Blueprint Skills own
  recipes; core tools own scene reads and writes; ToolRegistry and Harness own
  authorization, confirmation, audit, and execution barriers.
- Any sampled cook keeps the local limits: explicit frame list, at most three
  frames, complete low-risk preflight, one confirmation, `force=False`, and
  restoration of the original frame.
- Unknown facts, missing help pages, incomplete node evidence, and unsupported
  local capabilities fail closed.

## Migration classes

| Class | Meaning |
|---|---|
| Adapt | Migrate the decision method and local help evidence into a guide. |
| Split | Keep guidance separate from an existing executable Blueprint Skill. |
| Redirect | Preserve only scope/deprecation guidance and route to a current workflow. |
| Defer | Requires missing local facts, tools, or version evidence before migration. |

## Matrix

Status values are `migrated`, `review`, `ready`, and `deferred`. `migrated`
means a local guide exists and passes current packaged-guide audits; it does not
mean the upstream and local documents are textually equivalent.

| # | Upstream file | Local topic | Local capability relationship | Class | Required factual evidence | Safety adaptation | Status |
|---:|---|---|---|---|---|---|---|
| 1 | `model.md` | `model` | `procedural_modeling_guide`, `decompose_houdini_task` | Split | SOP modeling pages; declared SOP nodes | Native nodes before opaque code; verify branch outputs | migrated |
| 2 | `copy.md` | `copy` | Procedural modeling and network inspection tools | Adapt | Copy/instance help; template attributes; SOP catalog | Inspect attributes and transforms before mutation | migrated |
| 3 | `dyno.md` | `dyno` | `simulation_workflow_guide` | Split | SOP Solver and DOP help; Sop/Dop nodes | Guide cannot cook; sampled validation keeps three-frame gate | migrated |
| 4 | `pyro.md` | `pyro` | `setup_pyro_sim`, `simulation_workflow_guide` | Split | Pyro help; Sop/Dop Pyro nodes | Draft first; preflight before sampled cook; approval before upres | migrated |
| 5 | `fluid.md` | `fluid` | Existing FLIP simulation blueprint | Split | Fluid/FLIP help; Sop/Dop nodes; cache path facts | Separate ocean coupling; no unapproved cache write or long cook | migrated |
| 6 | `vellum.md` | `vellum` | Existing Vellum simulation blueprint | Split | Vellum help; Sop/Dop nodes; constraint attributes | Diagnose topology/scale first; no automatic multi-frame solve | migrated |
| 7 | `destruction.md` | `destruction` | Existing RBD simulation blueprint | Split | Destruction help; Sop/Dop fracture and constraint nodes | Separate fracture, constraints, solve, cache; draft before upres | migrated |
| 8 | `mpm.md` | `mpm` | `simulation_workflow_guide`; no dedicated auto-build owner | Adapt | MPM help; 20.5/21.0 node availability | Guidance only until a separately reviewed blueprint exists | migrated |
| 9 | `grains.md` | `grains` | Simulation guide; overlaps Vellum and MPM | Adapt | Grains, Vellum, and MPM comparison pages | Require method choice before building; no solver guessing | migrated |
| 10 | `ocean.md` | `ocean` | Dedicated subject takes precedence over water/FLIP aliases | Adapt | Ocean Spectrum help; ocean SOP nodes | Do not silently route spectral ocean work to FLIP | migrated |
| 11 | `dopparticles.md` | `dopparticles` | Simulation guide and scene inspection | Adapt | POP/DOP particle help; Sop/Dop nodes | Inspection-first debugging; bounded sample cooks only | migrated |
| 12 | `finiteelements.md` | `finiteelements` | Simulation guide; no dedicated blueprint | Adapt | FEM help and validated Sop/Dop node set | High-cost legacy simulation remains guidance-only | migrated |
| 13 | `muscles.md` | `muscles` | Character and simulation guidance | Adapt | Current tissue workflow plus legacy Vellum comparison | Identify current versus legacy system before any build | migrated |
| 14 | `crowds.md` | `crowds` | Character workflow; no one-call crowd builder | Adapt | Crowd corpus, agent/state/cache node evidence | Cache-shaped and expensive; require staged plan and approvals | migrated |
| 15 | `character.md` | `character` | Character/KineFX workflow Skills | Redirect | KineFX/APEX help; current deprecation facts | Route new work away from deprecated object-level bones | migrated |
| 16 | `feathers.md` | `feathers` | Grooming workflow; no dedicated blueprint | Adapt | Feather corpus and versioned grooming nodes | Stage template, scatter, guide, sim, render, export separately | migrated |
| 17 | `fur.md` | `fur` | Grooming workflow; no dedicated blueprint | Adapt | Fur/hair help and Sop nodes | Separate guide editing, deformation, render geometry, and export | migrated |
| 18 | `heightfields.md` | `heightfields` | Heightfield workflow Skills | Split | SOP heightfield corpus and Sop nodes | Keep SOP terrain distinct from Copernicus terrain | migrated |
| 19 | `heightfields_cop.md` | `heightfields_cop` | Copernicus workflow | Adapt | Copernicus heightfield corpus; Cop nodes | Establish image/terrain space and output contract first | migrated |
| 20 | `copernicus.md` | `copernicus` | Copernicus blueprint/workflow guidance | Split | Copernicus corpus and Cop nodes | Verify spaces, planes, and display/output semantics | migrated |
| 21 | `composite.md` | `composite` | Legacy COP2 maintenance only | Redirect | COP2 deprecation page and Cop2 catalog evidence | New work redirects to Copernicus unless maintenance is explicit | migrated |
| 22 | `solaris.md` | `solaris` | `usd_scene_assembly_guide` | Split | LOP help, USD composition pages, Lop nodes | Inspect layer stack and prim paths; disk output remains separate | migrated |
| 23 | `tops.md` | `tops` | PDG workflow guidance | Adapt | TOP/PDG help and Top nodes | TOP execution and external processes require explicit authorization | migrated |
| 24 | `assets.md` | `assets` | HDA authoring and interface tools | Adapt | HDA help, definition/versioning pages, context-specific nodes | Definition writes and library paths require confirmation and backup | migrated |
| 25 | `render.md` | `render` | Render inspection/configuration tools | Redirect | Renderer-specific help and live render settings | Detect Karma versus Mantra before advice; rendering is separately authorized | migrated |
| 26 | `shade.md` | `shade` | Material and shader tools | Redirect | MaterialX/Karma and legacy Mantra material pages | Detect renderer; prevent legacy shader guidance in Karma workflows | migrated |
| 27 | `props.md` | `props` | Procedural modeling and assembly workflows | Adapt | Props workflow help; Sop nodes | Preserve art-directable controls and named output boundaries | migrated |
| 28 | `io.md` | `io` | Import/export and path-validation tools | Split | Format help, path syntax, Sop/Driver nodes | File writes/overwrites and external paths require explicit approval | migrated |
| 29 | `anim.md` | `anim` | Animation/KineFX workflow | Adapt | Animation and CHOP help; Sop/Chop nodes | Preserve keys and takes; scope edits explicitly | migrated |
| 30 | `ml.md` | `ml` | ML tools knowledge; no training orchestrator | Adapt | ML corpus, Sop/Top node evidence, data/export contracts | Dataset generation, training, and external execution need separate governance | migrated |
| 31 | `troubleshooting.md` | `troubleshooting` | `debug_scene_workflow`, read-only inspection tools | Split | Exact failing-domain help and node facts | Two failed fixes trigger new evidence; narrow fix then original-symptom check | migrated |

## Batch order

1. Review the five existing local guides against this matrix and keep their
   current audit green: `model`, `pyro`, `ocean`, `solaris`, `troubleshooting`.
2. Migrate the simulation decision set: `dyno`, `fluid`, `vellum`,
   `destruction`, `mpm`, `grains`, `dopparticles`.
3. Migrate current production domains: `copy`, `character`, `fur`,
   `heightfields`, `heightfields_cop`, `copernicus`, `composite`, `tops`,
   `assets`, `render`, `shade`, `props`, `io`, `anim`.
4. Migrate or explicitly retain deferral records for high-cost or weakly
   supported subjects: `finiteelements`, `crowds`, `feathers`, `ml`.

Each batch must pass `audit_packaged_guides()` and the focused workflow-guide
tests before the next batch begins. A topic may move to `migrated` only after
its local help citations, local tool references, and node declarations pass the
repository's executable audits.