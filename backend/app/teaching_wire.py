"""Native output formats for the current server-created teaching request.

The runtime still validates quotes, bounds, tokens and successful completion.
These wire options do not add tools or change protocol-native history.
"""
from __future__ import annotations

import copy
from typing import Any


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _nullable_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [_object(properties), {"type": "null"}]}


ENVELOPE_SCHEMA = _object({
    "reply": {"type": "string"},
    "teaching": _object({
        "step": {"type": ["string", "null"]},
        "attempt": _nullable_object({
            "quote": {"type": "string"},
            "needs_help": {"type": ["boolean", "null"]},
        }),
        "mode": _nullable_object({
            "value": {"type": "string", "enum": ["stepwise", "socratic", "feynman", "practice_first", "project", "adaptive",
                                                      "direct_answer", "full_explanation"]},
            "scope": {"type": "string", "enum": ["turn", "conversation"]},
            "quote": {"type": "string"},
            "persistence_quote": {"type": ["string", "null"]},
        }),
        "help": _nullable_object({
            "kind": {"type": "string", "enum": ["hint", "explain_step", "example", "try_first"]},
            "quote": {"type": "string"},
        }),
        "practice": _nullable_object({
            "question": {"type": ["string", "null"]},
            "feedback": {"type": ["string", "null"]},
        }),
        "project": _nullable_object({
            "goal": {"type": ["string", "null"]},
            "instruction": {"type": ["string", "null"]},
            "feedback": {"type": ["string", "null"]},
            "change_quote": {"type": ["string", "null"]},
        }),
        "adaptation": _nullable_object({
            "method": {"type": ["string", "null"], "enum": ["stepwise", "socratic", "feynman", "practice_first", "project", "direct_answer", "full_explanation", None]},
            "reason": {"type": ["string", "null"]},
            "rule_id": {"type": ["string", "null"]},
            "draft": _nullable_object({
                "scenario": {"type": "string", "enum": ["general", "concepts", "problem_solving", "coding", "project"]},
                "method": {"type": "string", "enum": ["stepwise", "socratic", "feynman", "practice_first", "project", "direct_answer", "full_explanation"]},
                "start": {"type": "string", "enum": ["auto", "example_first", "try_first", "explain_first"]},
                "help": {"type": "string", "enum": ["auto", "one_hint", "explain_when_stuck"]},
                "quote": {"type": "string"},
                "reason": {"type": "string"},
            }),
        }),
        "learning": _nullable_object({
            "observations": {"type": "array", "items": _object({
                "point_id": {"type": ["string", "null"]},
                "topic": {"type": "string"},
                "state": {"type": "string", "enum": ["progress", "difficulty", "uncertain"]},
                "quote": {"type": "string"},
                "feedback": {"type": "string"},
            })},
            "used": {"type": "array", "items": {"type": "string"}},
        }),
    }),
    "token": {"type": "string"},
})


def output_kind(messages: list[dict[str, Any]]) -> str:
    """Only the newest runtime message can select the current output format."""
    for message in reversed(messages):
        if message.get("_teaching_runtime") is True:
            return 'json' if message.get("_teaching_output") == "json" else 'legacy'
    return 'plain'


def uses_json(messages: list[dict[str, Any]]) -> bool:
    return output_kind(messages) == 'json'


def apply_json_output(payload: dict[str, Any], kind: str,
                      messages: list[dict[str, Any]]) -> None:
    """Add the selected provider's native format without changing tool policy."""
    if not uses_json(messages):
        return
    if kind == "openai_compatible":
        payload["response_format"] = {"type": "json_object"}
    elif kind == "openai_responses":
        payload.setdefault("text", {})["format"] = {"type": "json_object"}
    elif kind == "google":
        payload.setdefault("generationConfig", {})["responseMimeType"] = "application/json"
    elif kind == "anthropic":
        payload.setdefault("output_config", {})["format"] = {
            "type": "json_schema", "schema": copy.deepcopy(ENVELOPE_SCHEMA),
        }
