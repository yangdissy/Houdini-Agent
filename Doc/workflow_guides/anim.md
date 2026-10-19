# Animation workflow
<!-- tools: setup_kinefx_pipeline -->
<!-- evidence: runtime-search -->

Goal: {description}

Use `setup_kinefx_pipeline` for KineFX rig or retarget blueprints. For CHOP-based processing, verify the exact workflow and nodes through `search_houdini_help` before editing.

## Decisions

- Identify whether the task changes keys, channels, clips, skeleton transforms, retargeting, constraints, or procedural motion.
- Preserve existing keys, interpolation, expressions, takes, channel references, rest transforms, and frame range unless the user explicitly changes them.
- Work on a duplicated or isolated branch when altering established animation.

## Order of work

1. Inspect frame range, FPS, time units, takes, keyframes, interpolation, expressions, constraints, and channel references.
2. Record the original motion at representative and extreme poses.
3. Apply one scoped operation to known channels or joints.
4. Compare motion, hierarchy, contacts, loops, and bounds across representative frames.
5. Preserve the original branch until the edited result and downstream deformation are verified.

## Failure signatures

- Timing drift often indicates FPS, sample-rate, clip-range, or unit mismatch.
- Retarget offsets point first to hierarchy, rest transforms, scale, and orientation.
- Unexpected key changes may come from editing the wrong take, channel scope, or referenced control.