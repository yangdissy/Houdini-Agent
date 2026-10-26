# -*- coding: utf-8 -*-
"""
Plan Manager — Plan 模式的数据模型与文件管理

职责：
- Plan 数据的 CRUD（创建、读取、更新、删除）
- Plan 文件持sion_id}久化到当前用户 cache root 下的 plans/plan_{ses.json
- 精简版 Plan 上下文生成（用于注入 LLM，最小化 token 消耗）
- 一个 session 只有一个 active plan，重复创建时自动归档旧 plan
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from .plan_runtime import PlanQualityGate, PlanRuntime


def validate_plan_questions(questions: Any) -> None:
    if not isinstance(questions, list) or not 1 <= len(questions) <= 2:
        raise ValueError("Provide 1 or 2 questions.")
    question_ids = set()
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("Each question must be an object.")
        question_id = question.get("id")
        if not isinstance(question_id, str) or not question_id.strip() or question_id in question_ids:
            raise ValueError("Question ids must be non-empty and unique.")
        question_ids.add(question_id)
        if not isinstance(question.get("prompt"), str) or not question["prompt"].strip():
            raise ValueError("Question prompt is required.")
        for flag in ("allow_multiple", "allow_free_text"):
            if flag in question and not isinstance(question[flag], bool):
                raise ValueError(f"{flag} must be a boolean.")
        options = question.get("options", [])
        if not isinstance(options, list) or (not options and not question.get("allow_free_text")):
            raise ValueError("Provide options or enable free text.")
        option_ids = set()
        for option in options:
            if not isinstance(option, dict):
                raise ValueError("Each option must be an object.")
            option_id = option.get("id")
            if (not isinstance(option_id, str) or not option_id.strip()
                    or option_id.startswith("__free_text__:") or option_id in option_ids):
                raise ValueError("Option ids must be non-empty, unique and not reserved.")
            if not isinstance(option.get("label"), str) or not option["label"].strip():
                raise ValueError("Option label is required.")
            option_ids.add(option_id)


def normalize_plan_answers(questions: list, answers: Any) -> dict:
    if not isinstance(answers, dict) or set(answers) != {question["id"] for question in questions}:
        raise ValueError("Answer every question using its question id.")
    normalized = {}
    for question in questions:
        selections = answers[question["id"]]
        if not isinstance(selections, list) or not all(isinstance(value, str) for value in selections):
            raise ValueError("Answers must be lists of option ids or free text.")
        option_ids = {option["id"] for option in question.get("options", [])}
        selected = []
        free_text = ""
        for value in selections:
            if value.startswith("__free_text__:"):
                text = value[len("__free_text__:"):].strip()
                if not question.get("allow_free_text") or not text or free_text:
                    raise ValueError("Invalid free text answer.")
                free_text = text
            elif value not in option_ids or value in selected:
                raise ValueError("Unknown or duplicate option id.")
            else:
                selected.append(value)
        if not selected and not free_text:
            raise ValueError("Answer every question before submitting.")
        if not question.get("allow_multiple") and len(selected) > 1:
            raise ValueError("Only one option may be selected.")
        normalized[question["id"]] = {"selected_option_ids": selected, "free_text": free_text}
    return normalized


class PlanQualityError(ValueError):
    def __init__(self, diagnostics: list) -> None:
        self.diagnostics = [diagnostic.to_dict() for diagnostic in diagnostics]
        messages = "; ".join(item["message"] for item in self.diagnostics if item["severity"] == "error")
        super().__init__(f"Plan failed quality gate: {messages}")


class PlanManager:
    """Plan 文件管理器

    文件存储路径:
        <cache_root>/plans/plan_{session_id}.json

    Plan JSON Schema (增强版):
        {
            "plan_id": "a1b2c3d4",
            "session_id": "e5f6g7h8",
            "title": "...",
            "overview": "...",
            "complexity": "low|medium|high",
            "estimated_total_operations": 25,
            "phases": [{"name": "Phase 1: ...", "step_ids": ["step-1", "step-2"]}],
            "created_at": "2026-02-26T10:30:00",
            "status": "draft|confirmed|executing|completed|rejected",
            "architecture": {"nodes": [...], "connections": [...], "groups": [...]},
            "steps": [
                {
                    "id": "step-1",
                    "title": "构建基础地形",
                    "description": "详细描述，含具体路径和参数值...",
                    "sub_steps": ["创建节点", "设置参数"],
                    "tools": ["create_node", "set_node_parameter"],
                    "depends_on": [],
                    "expected_result": "可验证的预期结果",
                    "risk": "low|medium|high",
                    "estimated_operations": 4,
                    "fallback": "失败回退策略",
                    "notes": "备注",
                    "status": "pending|running|done|error",
                    "result_summary": null
                }
            ]
        }
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            cache_dir = Path(__file__).resolve().parent.parent.parent / "cache"
        self._plans_dir = cache_dir / "plans"
        self._plans_dir.mkdir(parents=True, exist_ok=True)
        self._runtime = PlanRuntime()

    # ------------------------------------------------------------------
    # 路径工具
    # ------------------------------------------------------------------

    def _plan_path(self, session_id: str) -> Path:
        return self._plans_dir / f"plan_{session_id}.json"

    def _archive_path(self, session_id: str) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self._plans_dir / f"plan_{session_id}_archived_{ts}.json"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_plan(self, session_id: str, plan_data: dict) -> dict:
        """创建新 Plan 并持久化

        如果该 session 已有 active plan，旧 plan 自动归档。

        Args:
            session_id: 会话 ID
            plan_data: AI 通过 create_plan 工具提交的数据
                必须包含 title, steps; 可选 overview

        Returns:
            完整的 plan dict（含自动生成的 plan_id, created_at 等）
        """
        # 规范化 steps（增强版：支持子步骤/预期结果/风险/回退等）
        steps = []
        for i, s in enumerate(plan_data.get("steps", [])):
            step = {
                "id": s.get("id", f"step-{i + 1}"),
                "title": s.get("title", s.get("description", "")),
                "description": s.get("description", ""),
                "sub_steps": s.get("sub_steps", []),
                "tools": s.get("tools", []),
                "depends_on": s.get("depends_on", []),
                "expected_result": s.get("expected_result", ""),
                "risk": s.get("risk", "low"),
                "estimated_operations": s.get("estimated_operations", 1),
                "fallback": s.get("fallback", ""),
                "notes": s.get("notes", ""),
                "status": "pending",
                "result_summary": None,
            }
            steps.append(step)

        plan = {
            "plan_id": str(uuid.uuid4())[:8],
            "session_id": session_id,
            "title": plan_data.get("title", "Untitled Plan"),
            "overview": plan_data.get("overview", ""),
            "complexity": plan_data.get("complexity", "medium"),
            "estimated_total_operations": plan_data.get("estimated_total_operations", sum(
                s.get("estimated_operations", 1) for s in plan_data.get("steps", [])
            )),
            "phases": plan_data.get("phases", []),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "status": "draft",  # draft → confirmed → executing → completed
            "steps": steps,
            "architecture": plan_data.get("architecture", {}),
        }

        quality_score, diagnostics = self._quality_gate().evaluate(plan)
        plan["quality"] = {
            "score": quality_score,
            "diagnostics": [d.to_dict() for d in diagnostics],
        }
        if PlanQualityGate.has_errors(diagnostics):
            raise PlanQualityError(diagnostics)

        # 归档旧 plan。必须在新 plan 通过 quality gate 后执行，避免坏计划删除 active plan。
        old_path = self._plan_path(session_id)
        archive_path = None
        if old_path.exists():
            archive_path = self._archive_path(session_id)
            old_path.rename(archive_path)

        try:
            self._save(session_id, plan)
        except Exception:
            if archive_path is not None and archive_path.exists():
                if old_path.exists():
                    old_path.unlink()
                archive_path.rename(old_path)
            raise
        return plan

    def load_plan(self, session_id: str) -> Optional[dict]:
        """加载该 session 的 active plan

        Returns:
            plan dict, 或 None（不存在）
        """
        path = self._plan_path(session_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def update_step(
        self,
        session_id: str,
        step_id: str,
        status: str,
        result_summary: Optional[str] = None,
        evidence: Optional[List[dict]] = None,
    ) -> Optional[dict]:
        """更新单个步骤的状态

        Args:
            session_id: 会话 ID
            step_id: 步骤 ID
            status: 新状态 ("running" | "done" | "error")
            result_summary: 可选的结果摘要

        Returns:
            更新后的 plan dict, 或 None（plan 不存在）
        """
        plan = self.load_plan(session_id)
        if not plan:
            return None

        can_transition, reason = self._runtime.can_transition(plan, step_id, status)
        if not can_transition:
            raise ValueError(reason)
        if status in {"blocked", "error"} and (not isinstance(result_summary, str) or not result_summary.strip()):
            raise ValueError("Blocked or error steps require a reason in result_summary.")

        for step in plan["steps"]:
            if step["id"] == step_id:
                step["status"] = status
                if result_summary is not None:
                    step["result_summary"] = result_summary
                if evidence is not None:
                    step["evidence"] = evidence
                step["verification"] = {
                    "reference_check": "verified" if step.get("evidence") else "not_provided",
                    "acceptance": "unverified",
                }
                break

        plan["status"] = self._runtime.plan_status(plan)

        self._save(session_id, plan)
        return plan

    def confirm_plan(self, session_id: str) -> Optional[dict]:
        """将 plan 状态设为 confirmed"""
        plan = self.load_plan(session_id)
        if plan:
            if plan.get("status", "draft") != "draft":
                raise ValueError(f"Plan cannot be confirmed from status '{plan.get('status')}'.")
            quality_score, diagnostics = self._quality_gate().evaluate(plan)
            plan["quality"] = {
                "score": quality_score,
                "diagnostics": [d.to_dict() for d in diagnostics],
            }
            if PlanQualityGate.has_errors(diagnostics):
                raise PlanQualityError(diagnostics)
            plan["status"] = "confirmed"
            self._save(session_id, plan)
        return plan

    def reject_plan(self, session_id: str) -> Optional[dict]:
        """将 plan 状态设为 rejected"""
        plan = self.load_plan(session_id)
        if plan:
            if plan.get("status", "draft") not in ("draft", "confirmed"):
                raise ValueError(f"Plan cannot be rejected from status '{plan.get('status')}'.")
            plan["status"] = "rejected"
            self._save(session_id, plan)
        return plan

    def delete_plan(self, session_id: str):
        """删除该 session 的 plan 文件"""
        path = self._plan_path(session_id)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # 上下文注入（精简版）
    # ------------------------------------------------------------------

    def get_plan_for_context(self, session_id: str) -> str:
        """生成精简版 Plan 上下文用于注入 LLM

        只包含标题 + 当前进度 + 未完成步骤，最小化 token 消耗。
        约 100-200 tokens。

        Returns:
            格式化字符串, 或空字符串（无 plan）
        """
        plan = self.load_plan(session_id)
        if not plan or plan.get("status") in ("rejected", "draft"):
            return ""

        steps = plan.get("steps", [])
        if not steps:
            return ""

        done_count = sum(1 for s in steps if s["status"] == "done")
        total = len(steps)

        lines = [f"[Active Plan: {plan.get('title', 'Untitled')}]"]
        lines.append(f"Progress: {done_count}/{total} done")
        unverified = [step["id"] for step in steps if step.get("status") == "done"
                      and step.get("verification", {}).get("acceptance", "unverified") == "unverified"]
        if unverified:
            lines.append("Acceptance unverified: " + ", ".join(unverified))
        for step in steps:
            if step.get("status") in {"error", "blocked"}:
                lines.append(f"{step['id']} {step['status']}: {step.get('result_summary', '')}")

        # 当前正在执行的步骤
        for s in steps:
            if s["status"] == "running":
                tools_str = ", ".join(s.get("tools", [])) if s.get("tools") else ""
                title = s.get("title", s.get("description", s["id"]))
                line = f'Current: {s["id"]} "{title}"'
                if tools_str:
                    line += f" (tools: {tools_str})"
                expected = s.get("expected_result", "")
                if expected:
                    line += f" | Expected: {expected}"
                fallback = s.get("fallback", "")
                if fallback:
                    line += f" | Fallback: {fallback}"
                lines.append(line)
                # 子步骤提示
                sub = s.get("sub_steps", [])
                if sub:
                    lines.append(f"  Sub-steps: {'; '.join(sub)}")
                break

        # 下一个待执行的步骤
        ready_steps = self._runtime.next_ready_steps(plan)
        if ready_steps:
            s = ready_steps[0]
            title = s.get("title", s.get("description", s["id"]))
            lines.append(f'Ready next: {s["id"]} "{title}"')
        frontier = self._runtime.frontier_context(plan)
        if frontier:
            lines.append(frontier)

        # 剩余未完成步骤数量
        remaining = [s for s in steps if s["status"] == "pending"]
        if len(remaining) > 1:
            names = ", ".join(
                f'"{s.get("title", s.get("description", s["id"]))}"'
                for s in remaining[1:]
            )
            lines.append(f"Remaining: {names}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 工具注册信息
    # ------------------------------------------------------------------

    @staticmethod
    def get_plan_tools() -> List[dict]:
        """返回 Plan 模式专用的工具定义列表"""
        return [PLAN_TOOL_CREATE, PLAN_TOOL_UPDATE_STEP, PLAN_TOOL_ASK_QUESTION]

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _save(self, session_id: str, plan: dict):
        path = self._plan_path(session_id)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(plan, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(temp_path), str(path))
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _quality_gate(self) -> PlanQualityGate:
        try:
            from .tool_registry import get_tool_registry

            registry = get_tool_registry()
            known_tools = registry.get_executable_tool_names("plan_executing")
        except Exception as exc:
            raise RuntimeError("Plan tool registry is unavailable") from exc
        return PlanQualityGate(known_tools=known_tools)


# ======================================================================
# Plan 工具定义（OpenAI Function Calling 格式）
# ======================================================================

PLAN_TOOL_CREATE = {
    "type": "function",
    "function": {
        "name": "create_plan",
        "description": (
            "Create a structured, engineering-grade execution plan for the user to review. "
            "The plan is displayed as an interactive card with DAG flow diagram. "
            "The user must confirm before execution begins.\n"
            "CRITICAL REQUIREMENTS:\n"
            "1. Group steps by SUBSYSTEM, not by individual node. One step = one complete logical "
            "subsystem (e.g. 'scatter system: Grid+Scatter+CopyToPoints+Box'). Prefer batch tools "
            "when applicable. Analysis, layout and verification steps do not require node creation.\n"
            "2. Declare actual depends_on; independent root steps may use []. Missing dependencies "
            "on non-first steps produce a quality warning, not an invented linear dependency.\n"
            "3. Plans with 3+ steps should use phases for logical grouping; omissions produce quality warnings.\n"
            "4. Describe concrete targets, relevant paths and applicable parameters or checks.\n"
            "5. steps.tools must list the exact Houdini tool names. Prefer batch tools "
            "(create_nodes_batch, batch_set_parameters, layout_nodes) over per-node tools.\n"
            "6. depends_on drives the execution DAG. Unknown dependencies and cycles are rejected.\n"
            "For node-building tasks, avoid per-node steps; merge related work into subsystems. "
            "For non-building tasks architecture is optional. For large networks include only the affected portion."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Plan title (concise, describes the goal)",
                },
                "overview": {
                    "type": "string",
                    "description": "Brief overview of the plan approach",
                },
                "complexity": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Overall complexity assessment",
                },
                "estimated_total_operations": {
                    "type": "integer",
                    "description": "Estimated total number of tool operations across all steps",
                },
                "phases": {
                    "type": "array",
                    "description": "Recommended for 3+ steps. Group steps into logical phases and cover all step ids. Missing phases or coverage produce quality warnings.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Phase name, e.g. 'Phase 1: Base Geometry'",
                            },
                            "step_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of step IDs belonging to this phase",
                            },
                        },
                        "required": ["name", "step_ids"],
                    },
                },
                "steps": {
                    "type": "array",
                    "description": "Ordered list of execution steps with detailed breakdown",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique step ID, e.g. 'step-1'",
                            },
                            "title": {
                                "type": "string",
                                "description": "Short step title for display",
                            },
                            "description": {
                                "type": "string",
                                "description": "Detailed description including specific node paths, parameter names and values",
                            },
                            "sub_steps": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Atomic sub-operations within this step",
                            },
                            "tools": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Houdini tools to use in this step",
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Ids of actual prerequisite steps. Use [] for independent roots. Unknown ids and cycles are rejected; non-first empty dependencies produce a quality warning.",
                            },
                            "expected_result": {
                                "type": "string",
                                "description": "Verifiable expected outcome after this step completes",
                            },
                            "risk": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                                "description": "Risk level of this step",
                            },
                            "estimated_operations": {
                                "type": "integer",
                                "description": "Estimated number of tool operations in this step",
                            },
                            "fallback": {
                                "type": "string",
                                "description": "Fallback strategy if the primary approach fails",
                            },
                            "notes": {
                                "type": "string",
                                "description": "Technical notes or important considerations",
                            },
                        },
                        "required": ["id", "title", "description", "tools", "expected_result"],
                    },
                },
                "architecture": {
                    "type": "object",
                    "description": (
                        "Optional for analysis, layout, and other non-building tasks. For node-building tasks, "
                        "describe the affected target network, not every existing node in a large scene. "
                        "This is a design blueprint, not the execution steps. Without it the UI shows the step DAG."
                    ),
                    "properties": {
                        "nodes": {
                            "type": "array",
                            "description": "Nodes in the affected portion of the target network",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "Unique node identifier (use the actual node name, e.g. 'grid1', 'mountain1')",
                                    },
                                    "label": {
                                        "type": "string",
                                        "description": "Display label (node type or descriptive name, e.g. 'Grid SOP', 'Mountain', 'Scatter')",
                                    },
                                    "type": {
                                        "type": "string",
                                        "enum": ["sop", "obj", "mat", "vop", "rop", "dop", "lop", "cop", "chop", "out", "subnet", "null", "other"],
                                        "description": "Houdini node category for visual styling",
                                    },
                                    "group": {
                                        "type": "string",
                                        "description": "Logical group name for visual grouping (e.g. 'Terrain', 'Scatter System', 'Materials')",
                                    },
                                    "is_new": {
                                        "type": "boolean",
                                        "description": "True if this node will be created by the plan; false if it already exists",
                                    },
                                    "params": {
                                        "type": "string",
                                        "description": "Key parameters to set (brief, e.g. 'Height=2, Noise=Perlin')",
                                    },
                                },
                                "required": ["id", "label", "type"],
                            },
                        },
                        "connections": {
                            "type": "array",
                            "description": "Connections between nodes (output → input)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "from": {
                                        "type": "string",
                                        "description": "Source node ID",
                                    },
                                    "to": {
                                        "type": "string",
                                        "description": "Destination node ID",
                                    },
                                    "label": {
                                        "type": "string",
                                        "description": "Optional connection label (e.g. input index or semantic label like 'template')",
                                    },
                                },
                                "required": ["from", "to"],
                            },
                        },
                        "groups": {
                            "type": "array",
                            "description": "Visual grouping of nodes into logical sections",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "Group display name (e.g. 'Terrain Generation', 'Scatter System')",
                                    },
                                    "node_ids": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Node IDs belonging to this group",
                                    },
                                    "color": {
                                        "type": "string",
                                        "description": "Optional hint color for the group (e.g. 'blue', 'green', 'purple')",
                                    },
                                },
                                "required": ["name", "node_ids"],
                            },
                        },
                    },
                    "required": ["nodes", "connections"],
                },
            },
            "required": ["title", "overview", "steps"],
        },
    },
}

PLAN_TOOL_UPDATE_STEP = {
    "type": "function",
    "function": {
        "name": "update_plan_step",
        "description": (
            "Update the status of a plan step. Call this BEFORE starting a step "
            "(status='running') and AFTER completing it (status='done', 'error' or 'blocked'). "
            "Use blocked for missing prerequisites and supply a reason for blocked/error. "
            "Terminal steps cannot be restarted. Evidence references are checked for provenance, "
            "not acceptance: success of a tool call does not prove expected_result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "step_id": {
                    "type": "string",
                    "description": "The step ID to update, e.g. 'step-1'",
                },
                "status": {
                    "type": "string",
                    "enum": ["running", "done", "error", "blocked"],
                    "description": "New status for the step",
                },
                "result_summary": {
                    "type": "string",
                    "description": "Brief result summary; a non-empty reason is required for error or blocked.",
                },
                "evidence_refs": {
                    "type": "array",
                    "maxItems": 20,
                    "description": "Optional current-session references. References are checked, not proof of acceptance. No references leaves acceptance unverified.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["operation_receipt", "result"]},
                            "ref": {"type": "string", "description": "request_ref or result_ref returned by a tool"},
                        },
                        "required": ["kind", "ref"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["step_id", "status"],
        },
    },
}


PLAN_TOOL_ASK_QUESTION = {
    "type": "function",
    "function": {
        "name": "ask_question",
        "description": (
            "Ask the user clarifying questions during planning. "
            "Use this when information is insufficient, ambiguous, or when multiple "
            "significantly different implementation approaches exist. "
            "Not available during plan execution: the plan confirmation already authorizes the work. "
            "Ask at most 1-2 key questions per call. Do not over-ask."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "description": "List of questions to ask (max 2)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique question ID, e.g. 'q1'",
                            },
                            "prompt": {
                                "type": "string",
                                "description": "The question text to display",
                            },
                            "options": {
                                "type": "array",
                                "description": "Selectable options for this question",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "description": "Option ID",
                                        },
                                        "label": {
                                            "type": "string",
                                            "description": "Option display text",
                                        },
                                    },
                                    "required": ["id", "label"],
                                },
                            },
                            "allow_multiple": {
                                "type": "boolean",
                                "description": "If true, user can select multiple options (checkbox). Default false (radio).",
                            },
                            "allow_free_text": {
                                "type": "boolean",
                                "description": "If true, show a free text input for custom answer. Default false.",
                            },
                        },
                        "required": ["id", "prompt", "options"],
                    },
                },
            },
            "required": ["questions"],
        },
    },
}


# ======================================================================
# 单例
# ======================================================================

_instances: Dict[str, PlanManager] = {}


def get_plan_manager(cache_dir: Optional[Path] = None) -> PlanManager:
    """获取指定 cache root 对应的 PlanManager。"""
    key = str(Path(cache_dir).resolve()) if cache_dir is not None else "__default__"
    if key not in _instances:
        _instances[key] = PlanManager(cache_dir)
    return _instances[key]
