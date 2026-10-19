# Scene troubleshooting workflow
<!-- tools: debug_scene_workflow, search_houdini_help -->
<!-- evidence: runtime-search -->

Problem: {description}

Use `search_houdini_help` for the failing domain and read the exact node card or workflow page before a third speculative edit.

## Evidence loop

1. Reproduce and record the original symptom.
2. Find the first failing node or stage, including upstream dependencies.
3. Form one falsifiable hypothesis and run the cheapest discriminating read or low-cost check.
4. Apply one narrow fix and re-check the original symptom.
5. After two consecutive fixes fail on the same symptom, stop editing and collect new guide or official-help evidence.

## Common dead ends

- Editing the first node displaying an error without checking where the error begins.
- Treating a successful tool call as proof that the visual or simulation result is correct.
- Running an expensive cook when a static inspection or low-resolution sample can disprove the theory.
- Repeating parameter changes while node type, menu token, group, attribute, file path, or USD prim path remains uncertain.

Use `debug_scene_workflow` to structure local inspection and verification.