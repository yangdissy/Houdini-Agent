# -*- coding: utf-8 -*-
"""Plan quality gate and DAG-aware runtime helpers."""

from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple


VALID_STEP_STATUSES = {"pending", "running", "done", "error", "blocked"}
TERMINAL_STEP_STATUSES = {"done", "error", "blocked"}
BATCH_TOOLS = {"create_nodes_batch", "batch_set_parameters", "layout_nodes"}


@dataclass
class PlanDiagnostic:
    severity: str
    code: str
    message: str
    step_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class PlanQualityGate:
    """Validate and score a normalized Plan dict."""

    def __init__(self, known_tools: Optional[Iterable[str]] = None):
        self.known_tools = set(known_tools or [])

    def evaluate(self, plan: dict) -> Tuple[float, List[PlanDiagnostic]]:
        diagnostics: List[PlanDiagnostic] = []
        steps = plan.get("steps", []) or []

        if not steps:
            diagnostics.append(PlanDiagnostic("error", "empty_steps", "Plan must contain at least one step."))
            return 0.0, diagnostics

        step_ids = [str(s.get("id", "")) for s in steps]
        step_id_set = set(step_ids)
        if len(step_ids) != len(step_id_set):
            diagnostics.append(PlanDiagnostic("error", "duplicate_step_id", "Step ids must be unique."))

        for step in steps:
            step_id = str(step.get("id", ""))
            if not step_id:
                diagnostics.append(PlanDiagnostic("error", "missing_step_id", "Every step must have an id."))
            for dep in step.get("depends_on", []) or []:
                if dep not in step_id_set:
                    diagnostics.append(
                        PlanDiagnostic("error", "unknown_dependency", f"Dependency '{dep}' does not exist.", step_id)
                    )
            status = step.get("status", "pending")
            if status not in VALID_STEP_STATUSES:
                diagnostics.append(
                    PlanDiagnostic("error", "invalid_status", f"Invalid step status '{status}'.", step_id)
                )

        cycle = self._find_cycle(steps)
        if cycle:
            diagnostics.append(
                PlanDiagnostic("error", "dependency_cycle", "Plan dependencies contain a cycle: " + " -> ".join(cycle))
            )

        phase_diagnostics = self._evaluate_phases(plan, step_id_set)
        diagnostics.extend(phase_diagnostics)
        diagnostics.extend(self._evaluate_architecture(plan))
        diagnostics.extend(self._evaluate_step_quality(steps))

        score = self._score(plan, diagnostics)
        return score, diagnostics

    @staticmethod
    def has_errors(diagnostics: Iterable[PlanDiagnostic]) -> bool:
        return any(d.severity == "error" for d in diagnostics)

    def _find_cycle(self, steps: List[dict]) -> List[str]:
        deps_by_step = {str(s.get("id", "")): list(s.get("depends_on", []) or []) for s in steps}
        visiting: Set[str] = set()
        visited: Set[str] = set()
        stack: List[str] = []

        def visit(step_id: str) -> Optional[List[str]]:
            if step_id in visiting:
                start = stack.index(step_id) if step_id in stack else 0
                return stack[start:] + [step_id]
            if step_id in visited:
                return None
            visiting.add(step_id)
            stack.append(step_id)
            for dep in deps_by_step.get(step_id, []):
                if dep not in deps_by_step:
                    continue
                cycle = visit(dep)
                if cycle:
                    return cycle
            stack.pop()
            visiting.remove(step_id)
            visited.add(step_id)
            return None

        for step_id in deps_by_step:
            cycle = visit(step_id)
            if cycle:
                return cycle
        return []

    def _evaluate_phases(self, plan: dict, step_ids: Set[str]) -> List[PlanDiagnostic]:
        diagnostics: List[PlanDiagnostic] = []
        steps = plan.get("steps", []) or []
        phases = plan.get("phases", []) or []
        if len(steps) >= 3 and not phases:
            diagnostics.append(PlanDiagnostic("warning", "missing_phases", "Plans with 3+ steps should group steps into phases."))
            return diagnostics

        covered: Set[str] = set()
        for phase in phases:
            for step_id in phase.get("step_ids", []) or []:
                if step_id not in step_ids:
                    diagnostics.append(
                        PlanDiagnostic("error", "phase_unknown_step", f"Phase references unknown step '{step_id}'.")
                    )
                covered.add(step_id)
        if phases:
            missing = sorted(step_ids - covered)
            if missing:
                diagnostics.append(
                    PlanDiagnostic("warning", "phase_coverage_gap", "Phases do not cover steps: " + ", ".join(missing))
                )
        return diagnostics

    def _evaluate_architecture(self, plan: dict) -> List[PlanDiagnostic]:
        diagnostics: List[PlanDiagnostic] = []
        architecture = plan.get("architecture", {}) or {}
        nodes = architecture.get("nodes", []) or []
        connections = architecture.get("connections", []) or []
        node_ids = {str(n.get("id", "")) for n in nodes if n.get("id")}

        for conn in connections:
            src = str(conn.get("from", ""))
            dst = str(conn.get("to", ""))
            if src and src not in node_ids:
                diagnostics.append(PlanDiagnostic("error", "architecture_unknown_source", f"Connection source '{src}' is not in architecture.nodes."))
            if dst and dst not in node_ids:
                diagnostics.append(PlanDiagnostic("error", "architecture_unknown_target", f"Connection target '{dst}' is not in architecture.nodes."))
        if nodes and connections and len(connections) < max(0, len(nodes) - 1):
            diagnostics.append(PlanDiagnostic("warning", "sparse_architecture", "Architecture has fewer connections than expected for a connected node graph."))
        return diagnostics

    def _evaluate_step_quality(self, steps: List[dict]) -> List[PlanDiagnostic]:
        diagnostics: List[PlanDiagnostic] = []
        for index, step in enumerate(steps):
            step_id = str(step.get("id", ""))
            deps = step.get("depends_on", []) or []
            if index > 0 and not deps:
                diagnostics.append(
                    PlanDiagnostic("warning", "missing_depends_on", "Non-first steps should declare depends_on.", step_id)
                )

            expected = str(step.get("expected_result", "")).strip()
            if len(expected) < 12:
                diagnostics.append(
                    PlanDiagnostic("warning", "weak_expected_result", "expected_result should be specific and verifiable.", step_id)
                )

            tools = [str(t) for t in (step.get("tools", []) or [])]
            if not tools:
                diagnostics.append(
                    PlanDiagnostic("warning", "missing_tools", "Step should list the tools expected for execution.", step_id)
                )
            if self.known_tools:
                unknown = [t for t in tools if t not in self.known_tools]
                if unknown:
                    diagnostics.append(
                        PlanDiagnostic("error", "unavailable_tool", "Unavailable tools: " + ", ".join(unknown), step_id)
                    )
        return diagnostics

    def _score(self, plan: dict, diagnostics: List[PlanDiagnostic]) -> float:
        score = 1.0
        for diagnostic in diagnostics:
            score -= 0.25 if diagnostic.severity == "error" else 0.06

        steps = plan.get("steps", []) or []
        architecture = plan.get("architecture", {}) or {}
        nodes = architecture.get("nodes", []) or []
        if nodes and len(steps) >= len(nodes):
            score -= 0.10

        step_tools = [tool for step in steps for tool in (step.get("tools", []) or [])]
        if step_tools:
            batch_ratio = sum(1 for tool in step_tools if tool in BATCH_TOOLS) / max(len(step_tools), 1)
            score += min(0.08, batch_ratio * 0.08)

        return round(max(0.0, min(1.0, score)), 3)


class PlanRuntime:
    """DAG-aware runtime policy for Plan execution."""

    def next_ready_steps(self, plan: dict) -> List[dict]:
        steps = plan.get("steps", []) or []
        status_by_id = {s.get("id"): s.get("status", "pending") for s in steps}
        ready = []
        for step in steps:
            if step.get("status", "pending") != "pending":
                continue
            deps = step.get("depends_on", []) or []
            if all(status_by_id.get(dep) == "done" for dep in deps):
                ready.append(step)
        return ready

    def plan_status(self, plan: dict) -> str:
        """Derive the aggregate status without treating failures as completion."""
        statuses = [s.get("status", "pending") for s in (plan.get("steps", []) or [])]
        if statuses and all(status == "done" for status in statuses):
            return "completed"
        if any(status in ("error", "blocked") for status in statuses):
            return "blocked"
        if any(status == "running" for status in statuses):
            return "executing"
        return plan.get("status", "draft")

    def blocked_steps(self, plan: dict) -> List[dict]:
        steps = plan.get("steps", []) or []
        status_by_id = {s.get("id"): s.get("status", "pending") for s in steps}
        blocked = []
        for step in steps:
            if step.get("status", "pending") not in ("pending", "running"):
                continue
            deps = step.get("depends_on", []) or []
            if any(status_by_id.get(dep) in ("error", "blocked") for dep in deps):
                blocked.append(step)
        return blocked

    def can_transition(self, plan: dict, step_id: str, new_status: str) -> Tuple[bool, str]:
        if new_status not in VALID_STEP_STATUSES:
            return False, f"Invalid status '{new_status}'."

        steps = plan.get("steps", []) or []
        step = next((s for s in steps if s.get("id") == step_id), None)
        if not step:
            return False, f"Unknown step '{step_id}'."

        current = step.get("status", "pending")
        if current in TERMINAL_STEP_STATUSES and new_status != current:
            return False, f"Step '{step_id}' is already terminal ({current})."

        status_by_id = {s.get("id"): s.get("status", "pending") for s in steps}
        deps = step.get("depends_on", []) or []
        unmet = [dep for dep in deps if status_by_id.get(dep) != "done"]
        if new_status in ("running", "done") and unmet:
            return False, f"Step '{step_id}' has unmet dependencies: {', '.join(unmet)}."

        if new_status == "done" and current not in ("running", "done"):
            return False, f"Step '{step_id}' must be running before it can be done."

        return True, ""

    def frontier_context(self, plan: dict, max_steps: int = 5) -> str:
        ready = self.next_ready_steps(plan)
        blocked = self.blocked_steps(plan)
        lines: List[str] = []
        if ready:
            labels = [self._step_label(s) for s in ready[:max_steps]]
            lines.append("Ready: " + ", ".join(labels))
        if blocked:
            labels = [self._step_label(s) for s in blocked[:max_steps]]
            lines.append("Blocked: " + ", ".join(labels))
        return "\n".join(lines)

    @staticmethod
    def _step_label(step: dict) -> str:
        title = step.get("title", step.get("description", step.get("id", "")))
        return f'{step.get("id", "?")} "{title}"'