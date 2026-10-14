# -*- coding: utf-8 -*-
"""Single source of truth for Skill metadata, signatures, and arguments."""

import inspect
import keyword
import re


VALID_CATEGORIES = {
    "authoring", "docs", "geometry", "graph", "learning", "materials",
    "performance", "scene", "usd", "workflow",
}
VALID_RISK_LEVELS = {"low", "normal", "high"}
VALID_PARAMETER_TYPES = {"string", "integer", "number", "boolean", "array", "object"}
_PARAMETER_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def valid_name(name):
    return (
        isinstance(name, str)
        and bool(re.match(r"^[a-z][a-z0-9_]*$", name))
        and not keyword.iskeyword(name)
    )


def normalize_parameter_definitions(parameters):
    normalized = []
    names = set()
    for index, item in enumerate(parameters or []):
        if not isinstance(item, dict):
            return None, f"parameters[{index}] must be an object."
        name = str(item.get("name", "")).strip()
        param_type = str(item.get("type", "")).strip().lower()
        description = str(item.get("description", "")).strip()
        if not valid_name(name):
            return None, f"parameters[{index}].name must be lowercase snake_case."
        if name in names:
            return None, f"Duplicate parameter name: {name}"
        definition = dict(item)
        definition.update({
            "name": name,
            "type": param_type,
            "description": description,
            "required": bool(item.get("required", False)),
        })
        error = _validate_parameter(name, definition)
        if error:
            return None, error
        names.add(name)
        normalized.append(definition)
    return normalized, None


def _validate_parameter(name, definition):
    param_type = definition.get("type")
    type_names = param_type if isinstance(param_type, list) else [param_type]
    if not type_names or any(item not in VALID_PARAMETER_TYPES for item in type_names):
        return f"Unsupported parameter type for '{name}': {param_type}"
    if not str(definition.get("description", "")).strip():
        return f"Parameter '{name}' requires type and description."
    if definition.get("required") and "default" in definition:
        return f"Parameter '{name}' cannot be required and define a default."
    if "enum" in definition and (
            not isinstance(definition["enum"], list) or not definition["enum"]):
        return f"Parameter '{name}' enum must be a non-empty list."
    for bound in ("minimum", "maximum"):
        if bound in definition and (
                not isinstance(definition[bound], (int, float))
                or isinstance(definition[bound], bool)):
            return f"Parameter '{name}' {bound} must be numeric."
    if (
            "minimum" in definition and "maximum" in definition
            and definition["minimum"] > definition["maximum"]):
        return f"Parameter '{name}' minimum cannot exceed maximum."
    if ("minimum" in definition or "maximum" in definition) and not set(type_names).issubset({"integer", "number"}):
        return f"Parameter '{name}' numeric limits require integer or number type."
    return None


def validate_metadata(info, expected_name=None, legacy=False):
    if not isinstance(info, dict):
        return "SKILL_INFO must be a literal dictionary."
    name = str(info.get("name", "")).strip()
    if not valid_name(name):
        return "SKILL_INFO.name must be a lowercase Python identifier."
    if expected_name is not None and name != expected_name:
        return f"Skill name must match its filename: {name!r} != {expected_name!r}"
    category = str(info.get("category", "other" if legacy else "")).strip().lower()
    if legacy and category == "other":
        return None
    if category not in VALID_CATEGORIES:
        return f"Unknown Skill category: {category}"
    if not str(info.get("description", "")).strip():
        return "SKILL_INFO.description is required."
    risk_level = str(info.get("risk_level", "low" if legacy else "")).strip().lower()
    if risk_level not in VALID_RISK_LEVELS:
        return "SKILL_INFO.risk_level must be low, normal, or high."
    parameters = info.get("parameters", {})
    if not isinstance(parameters, dict):
        return "SKILL_INFO.parameters must be a dictionary."
    for parameter_name, definition in parameters.items():
        if not valid_name(parameter_name):
            return f"Invalid parameter name: {parameter_name}"
        if not isinstance(definition, dict):
            return f"Parameter '{parameter_name}' requires type and description."
        error = _validate_parameter(parameter_name, definition)
        if error:
            return error
    return None


def validate_run_signature(info, run_fn):
    if not callable(run_fn) or inspect.iscoroutinefunction(run_fn):
        return "Skill must define a synchronous run() function."
    signature = inspect.signature(run_fn)
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_kwargs:
        return None
    declared = set(info.get("parameters", {}))
    accepted = {
        name for name, parameter in signature.parameters.items()
        if parameter.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        and not name.startswith("_")
    }
    missing = sorted(declared - accepted)
    if missing:
        return f"run() does not accept declared parameters: {', '.join(missing)}"
    undocumented_required = sorted(
        name for name, parameter in signature.parameters.items()
        if parameter.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        and parameter.default is inspect.Parameter.empty
        and not name.startswith("_")
        and name not in declared
    )
    if undocumented_required:
        return f"run() has required parameters missing from SKILL_INFO: {', '.join(undocumented_required)}"
    return None


def validate_params(info, params):
    definitions = info.get("parameters", {})
    if not definitions:
        return dict(params), None
    unknown = sorted(set(params) - set(definitions))
    if unknown:
        return None, _argument_error("unknown_parameter", unknown[0], f"未知 Skill 参数: {', '.join(unknown)}")
    validated = dict(params)
    for name, definition in definitions.items():
        if name not in validated:
            if "default" in definition:
                validated[name] = definition["default"]
            elif definition.get("required"):
                return None, _argument_error("missing_required_parameter", name, f"缺少必填 Skill 参数: {name}")
            continue
        value = validated[name]
        expected = definition.get("type")
        expected_names = expected if isinstance(expected, list) else [expected]
        valid = any(isinstance(value, _PARAMETER_TYPES[name]) for name in expected_names)
        if set(expected_names).issubset({"integer", "number"}) and isinstance(value, bool):
            valid = False
        if not valid:
            expected_text = " 或 ".join(expected_names)
            return None, _argument_error("invalid_parameter_type", name, f"Skill 参数 '{name}' 必须是 {expected_text}")
        if "enum" in definition and value not in definition["enum"]:
            return None, _argument_error("parameter_not_in_enum", name, f"Skill 参数 '{name}' 必须是以下值之一: {definition['enum']}")
        if "minimum" in definition and value < definition["minimum"]:
            return None, _argument_error("parameter_below_minimum", name, f"Skill 参数 '{name}' 不能小于 {definition['minimum']}")
        if "maximum" in definition and value > definition["maximum"]:
            return None, _argument_error("parameter_above_maximum", name, f"Skill 参数 '{name}' 不能大于 {definition['maximum']}")
    return validated, None


def _argument_error(code, parameter, message):
    return {"error": message, "error_code": code, "parameter": parameter}