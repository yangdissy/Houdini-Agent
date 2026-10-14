"""PDG/TOP batch pipeline blueprint Skill."""

from houdini_agent.skills.workflow._blueprint import build_blueprint, chain, node




def run(target_node_path, wedge_count=4, failure_policy="fail"):
    target = str(target_node_path or "").strip()
    wedge_count = int(wedge_count)
    failure_policy = str(failure_policy or "fail").strip().lower()
    if not target or wedge_count < 1 or wedge_count > 100 or failure_policy not in ("fail", "continue"):
        return {"error": "target_node_path is required; wedge_count must be 1..100; failure_policy must be fail or continue."}
    nodes = [
        node("wedge", "wedge", "variations", {"wedgecount": wedge_count}),
        node("ropfetch", "ropfetch", "execute_target", {"roppath": target}),
        node("wait", "waitforall", "collect_results"),
        node("output", "partitionbyattribute", "batch_output"),
    ]
    return build_blueprint(
        "pdg_batch", "/tasks", nodes, chain("wedge", "ropfetch", "wait", "output"),
        "Do not cook the graph automatically. Review generated work-item paths, scheduler limits, retries, and failure handling before an explicit cook request.",
        target_node_path=target, wedge_count=wedge_count, failure_policy=failure_policy, final_node_id="output",
    )