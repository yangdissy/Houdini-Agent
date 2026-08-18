# -*- coding: utf-8 -*-
"""Pure provider/model capability and request normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


DUOJIE_ANTHROPIC_MODELS = frozenset({"glm-4.7", "glm-5", "glm-5-turbo", "glm-5.1"})
MODEL_ID_ALIASES = {"k3[1m]": "k3"}


@dataclass(frozen=True)
class ModelCapabilities:
    model: str
    reasoning: bool
    deepseek_v4: bool
    deepseek_v4_pro: bool
    glm47: bool
    temperature_one: bool
    max_tokens_parameter: str


def normalize_model_id(model: str) -> str:
    normalized = str(model or "").strip()
    return MODEL_ID_ALIASES.get(normalized, normalized)


def protocol_for(provider: str, model: str) -> str:
    provider_id = (provider or "openai").lower()
    model_id = normalize_model_id(model).lower()
    if provider_id == "kimi_coding":
        return "anthropic"
    if provider_id == "duojie" and model_id in DUOJIE_ANTHROPIC_MODELS:
        return "anthropic"
    return "openai"


def model_capabilities(model: str) -> ModelCapabilities:
    model_id = normalize_model_id(model)
    lowered = model_id.lower()
    deepseek_v4 = "deepseek-v4" in lowered
    deepseek_v4_pro = deepseek_v4 and "v4-pro" in lowered
    temperature_one = (
        "k2" in lowered
        or lowered.startswith("k3")
        or lowered.startswith("kimi-for-coding")
        or lowered.startswith("gpt-5")
    )
    max_tokens_parameter = (
        "max_completion_tokens"
        if lowered.startswith(("gpt-5", "o1", "o3", "o4"))
        else "max_tokens"
    )
    return ModelCapabilities(
        model=model_id,
        reasoning=("reasoner" in lowered or "r1" in lowered or "v4-pro" in lowered or lowered == "glm-4.7"),
        deepseek_v4=deepseek_v4,
        deepseek_v4_pro=deepseek_v4_pro,
        glm47=lowered == "glm-4.7",
        temperature_one=temperature_one,
        max_tokens_parameter=max_tokens_parameter,
    )


def payload_temperature(model: str, temperature: Optional[float]) -> Optional[float]:
    if model_capabilities(model).temperature_one:
        return 1
    if temperature is None:
        return None
    return min(max(temperature, 0.0), 1.0)


def normalize_openai_parameters(
    provider: str,
    model: str,
    temperature: Optional[float],
    max_tokens: Optional[int],
    enable_thinking: bool,
    tools_present: bool,
) -> Dict[str, Any]:
    """Return only capability-dependent OpenAI-compatible payload parameters."""
    provider_id = (provider or "openai").lower()
    capabilities = model_capabilities(model)
    parameters: Dict[str, Any] = {}

    resolved_temperature = payload_temperature(capabilities.model, temperature)
    if resolved_temperature is not None:
        parameters["temperature"] = resolved_temperature
    if max_tokens:
        parameters[capabilities.max_tokens_parameter] = max_tokens

    if capabilities.glm47 and provider_id == "glm" and enable_thinking:
        parameters["thinking"] = {"type": "enabled"}
        if tools_present:
            parameters["tool_stream"] = True

    if provider_id in ("deepseek", "siliconflow") and enable_thinking and capabilities.deepseek_v4:
        parameters["thinking"] = {"type": "enabled"}
        if capabilities.deepseek_v4_pro:
            parameters["reasoning_effort"] = "high"

    return parameters