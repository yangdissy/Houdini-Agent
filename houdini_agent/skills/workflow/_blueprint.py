"""Shared helpers for read-only workflow blueprints."""


def build_blueprint(name, parent_path, nodes, connections, notes, **details):
    result = {
        "blueprint": name,
        "parent_path": parent_path,
        "nodes": nodes,
        "connections": connections,
        "execution": {
            "tool": "create_nodes_batch",
            "notes": (
                "Run create_nodes_batch with dry_run=True first, then pass this blueprint's "
                f"nodes and connections with parent_path='{parent_path}'. {notes} "
                "After creation, verify_network and validate_node_network before accepting the result."
            ),
        },
    }
    result.update(details)
    return result


def node(node_id, node_type, name, parameters=None):
    return {"id": node_id, "type": node_type, "name": name, "parameters": parameters or {}}


def chain(*node_ids):
    return [
        {"from": source, "to": destination, "input": 0}
        for source, destination in zip(node_ids, node_ids[1:])
    ]