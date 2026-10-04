"""Apply a run's validated native reasoning controls without changing their meaning.

Model support and inherited selections are resolved before ProviderConfig is frozen.
This module only checks the wire shape and keeps output formats and tools intact.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .providers import ProviderConfig


def _invalid() -> Exception:
    # Providers imports this helper, so resolve the shared error after import time.
    from .providers import ProviderError

    return ProviderError("思考参数格式与提供方协议不匹配", kind="config_error")


def _object(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or not value or not set(value) <= keys:
        raise _invalid()
    return value


def _string(value: Any) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _invalid()


def _integer(value: Any, *, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise _invalid()


def _thinking(value: Any, *, anthropic: bool) -> dict[str, Any]:
    keys = {"type", "budget_tokens", "display"} if anthropic else {"type", "keep"}
    thinking = _object(value, keys)
    modes = {"enabled", "disabled", "adaptive"} if anthropic else {"enabled", "disabled"}
    if not isinstance(thinking.get("type"), str) or thinking["type"] not in modes:
        raise _invalid()
    if anthropic:
        if thinking["type"] == "enabled":
            _integer(thinking.get("budget_tokens"), minimum=1)
        elif "budget_tokens" in thinking:
            raise _invalid()
        if "display" in thinking:
            if thinking["type"] != "adaptive":
                raise _invalid()
            _string(thinking["display"])
    elif "keep" in thinking and (thinking["type"] != "enabled" or thinking["keep"] != "all"):
        raise _invalid()
    return thinking


def apply_reasoning_parameters(payload: dict[str, Any], config: ProviderConfig) -> None:
    """Merge only reasoning controls for this protocol; never map or drop a choice."""
    raw = getattr(config, "reasoning_parameters_json", None)
    if raw is None:
        return
    if not isinstance(raw, str):
        raise _invalid()
    try:
        fields = json.loads(raw)
    except (ValueError, RecursionError) as error:
        raise _invalid() from error
    if not isinstance(fields, dict):
        raise _invalid()
    if not fields:
        return

    kind = config.provider_kind
    if kind == "openai_compatible":
        _object(fields, {"reasoning_effort", "thinking", "enable_thinking", "thinking_budget"})
        if "reasoning_effort" in fields:
            _string(fields["reasoning_effort"])
        if "thinking" in fields:
            _thinking(fields["thinking"], anthropic=False)
        if "enable_thinking" in fields and type(fields["enable_thinking"]) is not bool:
            raise _invalid()
        if "thinking_budget" in fields:
            _integer(fields["thinking_budget"], minimum=0)
        payload.update(fields)
    elif kind == "openai_responses":
        _object(fields, {"reasoning"})
        reasoning = _object(fields["reasoning"], {"effort"})
        _string(reasoning.get("effort"))
        payload.setdefault("reasoning", {}).update(reasoning)
    elif kind == "anthropic":
        _object(fields, {"thinking", "output_config"})
        thinking = _thinking(fields["thinking"], anthropic=True) if "thinking" in fields else None
        if "output_config" in fields:
            output = _object(fields["output_config"], {"effort"})
            _string(output.get("effort"))
        if thinking is not None and thinking["type"] == "enabled":
            _integer(payload.get("max_tokens"), minimum=1)
        if thinking is not None:
            payload["thinking"] = thinking
            if thinking["type"] == "enabled":
                # Keep the original reply allowance in addition to thinking.
                payload["max_tokens"] += thinking["budget_tokens"]
        if "output_config" in fields:
            payload.setdefault("output_config", {}).update(fields["output_config"])
    elif kind == "google":
        _object(fields, {"generationConfig"})
        generation = _object(fields["generationConfig"], {"thinkingConfig"})
        thinking = _object(generation["thinkingConfig"], {"thinkingLevel", "thinkingBudget", "includeThoughts"})
        if "thinkingLevel" in thinking and "thinkingBudget" in thinking:
            raise _invalid()
        if "thinkingLevel" in thinking:
            _string(thinking["thinkingLevel"])
        if "thinkingBudget" in thinking:
            _integer(thinking["thinkingBudget"], minimum=-1)
        if "includeThoughts" in thinking and type(thinking["includeThoughts"]) is not bool:
            raise _invalid()
        payload.setdefault("generationConfig", {})["thinkingConfig"] = thinking
    else:
        raise _invalid()
