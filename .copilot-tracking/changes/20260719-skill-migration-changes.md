<!-- markdownlint-disable-file -->
# Release Changes: fxhoudinimcp Skill Migration

**Related Plan**: skill_migration_plan.md
**Implementation Date**: 2026-07-19

## Summary

Implemented the first-batch Houdini workflow discipline rule and read-only guide skills for SOP procedural modeling, LOP/USD scene assembly, and scene debugging.

## Changes

### Added

- rules/houdini_work_discipline.md - Added global Houdini node-first, tool-priority, planning, and verification discipline.
- houdini_agent/skills/procedural_modeling_guide.py - Added a low-risk read-only SOP procedural modeling guide skill.
- houdini_agent/skills/usd_scene_assembly_guide.py - Added a low-risk read-only LOP/USD scene assembly and lookdev guide skill.
- houdini_agent/skills/debug_scene_workflow.py - Added a low-risk read-only scene debugging workflow guide skill.

### Modified

- .copilot-tracking/plans/skill_migration_plan.md - Marked first-batch implementation and validation tasks complete.

### Removed

- None.

## Release Summary

**Total Files Affected**: 6

### Files Created (5)

- rules/houdini_work_discipline.md - Global Houdini workflow discipline for node-first planning, tool priority, and verification.
- houdini_agent/skills/procedural_modeling_guide.py - Read-only SOP procedural modeling guide skill.
- houdini_agent/skills/usd_scene_assembly_guide.py - Read-only LOP/USD scene assembly guide skill.
- houdini_agent/skills/debug_scene_workflow.py - Read-only Houdini scene debugging route skill.
- .copilot-tracking/changes/20260719-skill-migration-changes.md - Implementation tracking and release summary for the first-batch migration.

### Files Modified (1)

- .copilot-tracking/plans/skill_migration_plan.md - Updated implementation status for Phase 1 through Phase 3 and left Phase 4 as future evaluation.

### Files Removed (0)

- None.

### Dependencies & Infrastructure

- **New Dependencies**: None.
- **Updated Dependencies**: None.
- **Infrastructure Changes**: None.
- **Configuration Updates**: None; rules are auto-discovered from rules/*.md.

### Deployment Notes

No deployment step is required. The rule is picked up by the existing rules directory scanner, and the skill loader auto-discovers the new Python skill files.