# -*- coding: utf-8 -*-
"""Build a consolidated learning report from existing read-only analyses."""

from typing import Any, Dict, List




def build_report(hip_name: str, analysis_results: Dict[str, Any]) -> Dict[str, Any]:
    capture = analysis_results.get("capture_network_memory", {}) or {}
    repeated = analysis_results.get("find_repeated_subgraphs", {}) or {}
    fragile = analysis_results.get("find_fragile_references", {}) or {}
    contract = analysis_results.get("extract_network_contract", {}) or {}
    explanations = analysis_results.get("explain_network_pattern", {}) or {}
    highlights = [
        {
            "root": item.get("root_path"),
            "score": item.get("score"),
            "memory_draft": item.get("memory_draft"),
        }
        for item in (capture.get("candidates", []) or [])[:3]
    ]
    risks = []
    if fragile.get("finding_count"):
        risks.append(f"发现 {fragile['finding_count']} 个脆弱引用，涉及 {fragile.get('affected_nodes', 0)} 个节点。")
    if contract.get("external_dependencies"):
        risks.append(f"接口契约包含 {len(contract['external_dependencies'])} 个外部依赖。")
    asset_candidates = (repeated.get("patterns", []) or [])[:5]
    report_text = (
        f"HIP 学习报告: {hip_name}\n"
        f"精华网络候选: {len(highlights)}\n"
        f"重复模式候选: {len(asset_candidates)}\n"
        f"接口必需属性: {', '.join(contract.get('required_attributes', [])) or '未提取'}\n"
        f"主要风险: {' '.join(risks) or '未发现已知高风险项'}\n"
        f"设计洞察: {' '.join(explanations.get('insights', [])) or '未提供'}"
    )
    memory_candidates = [item["memory_draft"] for item in highlights if item.get("memory_draft")]
    if contract.get("memory_draft"):
        memory_candidates.append(contract["memory_draft"])
    return {
        "hip_name": hip_name,
        "report": report_text,
        "highlights": highlights,
        "risks": risks,
        "assetization_candidates": asset_candidates,
        "memory_candidates": memory_candidates[:5],
    }


def run(hip_name: str, analysis_results: Dict[str, Any]) -> Dict[str, Any]:
    if not (hip_name or "").strip():
        return {"error": "hip_name 不能为空。"}
    return build_report(hip_name, analysis_results or {})