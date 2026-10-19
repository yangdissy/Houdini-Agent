# Crowd workflow
<!-- tools: inspect_frame_range_risk -->
<!-- evidence: runtime-search -->

Goal: {description}

There is no local one-call crowd blueprint. Crowd node families differ across contexts and Houdini versions, so use `search_houdini_help` and `get_node_card` before naming or configuring nodes.

## Decisions

- Separate agent preparation, clips, states, transitions, placement, simulation or motion paths, variation, caching, USD publication, and rendering.
- Preserve stable agent definitions, joint names, clip metadata, IDs, and variant assignments.
- Choose simulation, SOP motion paths, or procedural USD crowds from interaction needs, scale, and renderer requirements rather than habit.

## Order of work

1. Validate one agent definition, locomotion clip, scale, orientation, and loop behavior.
2. Add state or motion-path transitions on a small agent count.
3. Verify terrain projection, avoidance, speed, timing, and deterministic IDs.
4. Run `inspect_frame_range_risk` before `cook_sample_frames`; sample at most three explicit frames.
5. Increase population only after behavior is stable, then validate cache size, LOD, variation, USD output, and render representation.

## Failure signatures

- Sliding feet usually indicate clip speed, root motion, retiming, scale, or terrain mismatch.
- State changes that never occur point first to transition conditions and agent metadata.
- Population changes between evaluations indicate unstable seeds, IDs, or source ordering.