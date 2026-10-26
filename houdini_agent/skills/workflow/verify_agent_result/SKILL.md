---
{"name":"verify_agent_result","category":"workflow","description":"验证 Agent 刚完成的 Houdini 场景操作是否达到用户目标。适用于建模、材质、灯光、相机、构图、USD lookdev 或其他会改变 3D 视口结果的任务。先执行最小只读技术检查，再用 visual_review（内部调用 capture_viewport 并把图片回传给视觉模型）自行审查当前视口；清楚区分技术事实、视觉观察和无法从截图证明的事项。视觉任务未完成模型自审时不得宣称验证通过。","risk_level":"low","parameters":{"review_type":{"type":"string","description":"视觉审查类型。","required":false,"default":"general","enum":["general","geometry","composition","material","lighting","usd"]},"target_path":{"type":"string","description":"与本次执行结果对应的 Houdini 节点或网络路径；未知时留空。","required":false,"default":""},"visual_goal":{"type":"string","description":"要验证的明确视觉目标或用户验收标准；未知时只检查通用可读性和明显视觉缺陷。","required":false,"default":""},"output_path":{"type":"string","description":"可选截图保存路径，例如 $HIP/agent_verification.jpg。仅作为额外文件证据，不能替代 visual_review 的模型自审。","required":false,"default":""},"width":{"type":"integer","description":"截图宽度，默认 960。细节审查可显式提高。","required":false,"default":960,"minimum":160,"maximum":1920},"height":{"type":"integer","description":"截图高度，默认 540。细节审查可显式提高。","required":false,"default":540,"minimum":120,"maximum":1080}}}
---
# Verify Agent Result

Use this Skill as the completion gate for a Houdini task whose result should be visible in the 3D viewport. Invoke it after the final Plan step is complete, or when no Plan exists and the Agent is about to claim the task is complete. It is a verification workflow, not permission to modify the scene further.

Task completion is the trigger, not node creation. Verify only the final visible output before claiming success. Invoke this Skill at most once per user task, not after every node or Plan step. Skip it for pure queries, non-visual changes, failed or cancelled tasks, and intermediate iterations. A second invocation is allowed only when the first review is inconclusive and one recapture can resolve it. Pass the final output-node path as `target_path` and the user's requested visible outcome as `visual_goal`.

## Allowed tools

Use only the smallest applicable read-only verification tools:

- `verify_network` as the default technical check when a SOP network or node graph changed. It already checks network health, cooks the display node, reports update mode, and returns basic display geometry counts.
- `get_geometry_summary` only when `verify_network` evidence is unavailable or the acceptance target specifically requires bounds, attributes, groups, target-node rather than display-node counts, or a more precise freshness signal.
- `temporary_auto_validate_geometry` when the final SOP may be stale because Houdini is in Manual update mode. It temporarily switches to Auto, force-cooks and reads the target, then restores the original mode.
- `inspect_material_assignments` or the smallest equivalent read-only material check when bindings changed.
- `inspect_lop_stage` or the smallest equivalent read-only USD check when a LOP/USD stage changed.
- `visual_review` for the final viewport capture and bounded visual assessment.
- `capture_viewport` only when an additional saved image file is required. It never replaces `visual_review` for completion validation.

Do not call mutation tools while running this Skill. If verification finds a defect, report it and propose the smallest correction; do not apply that correction unless the user requested autonomous repair and the normal tool policy authorizes it.

## Procedure

1. Restate the concrete acceptance target in one sentence. Derive it from `visual_goal` and the user's request; do not invent art direction.
2. Select the smallest technical check needed for the operation type. Reuse successful read-only evidence already returned in the current execution round when it covers the final `target_path` (or its containing network), was collected after the last scene mutation, and includes every fact required below. Do not repeat `verify_network`, geometry, material, or USD inspection merely because this Skill started; call only checks whose evidence is missing or stale. For a normal SOP completion, one successful `verify_network` result with fresh non-empty display geometry is sufficient technical evidence; do not add `get_geometry_summary` for duplicate point/primitive counts. Use the specialized geometry check only for the additional facts listed above. For newly created nodes, confirm that `target_path` exists and inspect the containing network. Skip unrelated checks. If `target_path` is missing and a technical check requires it, mark that check as unavailable instead of guessing a path.
3. Complete any missing technical check before the screenshot. Call `temporary_auto_validate_geometry(node_path=target_path)` only if the available evidence reports Manual update mode or unknown/stale freshness. When the current mode is Auto and freshness is established, do not call it. For a required scoped validation, continue only when it reports successful cook/read and restoration of the exact original update mode. Do not use persistent `set_update_mode` for verification. If the target is not a SOP, use its applicable technical check and explicitly state whether viewport freshness could be established.
4. Record facts such as network errors, primitive counts, bounds, material bindings, USD composition, and restored update mode separately from visual observations.
5. Call `visual_review` exactly once with `review_type`, `target_path`, `visual_goal`, `width`, and `height`. The tool captures the now-refreshed current Scene Viewer and injects the image into the next model turn so the Agent itself performs the review. Do not change camera, lighting, display mode, isolation, or visibility merely to make the result look better.
6. If the active model cannot analyze images and `visual_review` is unavailable, stop with `inconclusive` and require switching to a vision-capable model before rerunning this completion gate. Do not fall back to a human-only screenshot and do not claim the visual task is complete. When `output_path` is provided, `capture_viewport` may save an additional copy only after or alongside the required model review.
7. Fail closed when scoped validation/cook/restore fails, capture fails, no Scene Viewer exists, the target is not visible, the image is blank or obstructed, or technical evidence is unavailable. Report `inconclusive`; do not inspect or infer success from a stale viewport.
8. Compare only visible evidence against the acceptance target. Distinguish:
   - `technical_facts`: results proven by read-only Houdini tools.
   - `visual_observations`: facts visible in the captured viewport.
   - `limitations`: facts the current checks cannot prove.
9. Return one verdict:
   - `pass`: required technical checks pass and visible evidence satisfies the stated target.
   - `partial`: some criteria pass but a concrete gap remains.
   - `fail`: a required criterion is contradicted by evidence.
   - `inconclusive`: evidence is missing, capture failed, or the target is not inspectable.

## Reporting contract

Keep the result concise and evidence-based:

```text
verdict: pass | partial | fail | inconclusive
target: <acceptance target>
technical_facts:
- <tool-backed fact>
visual_observations:
- <visible fact, or "not reviewed">
limitations:
- <what remains unproven>
recommended_next_action: <none, recapture, or smallest correction>
```

Never claim that a viewport screenshot proves geometry freshness, clean network state, correct material bindings, simulation validity, export correctness, or render correctness. Those require their corresponding technical checks.