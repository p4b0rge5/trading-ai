"""
JSON Schema generator for StrategySpec.

Exports the Pydantic model as a strict JSON Schema that can be fed
to OpenAI's `response_format={type: "json_schema", ...}` for constrained
generation — the LLM *must* return valid strategy spec JSON.
"""

from __future__ import annotations

from engine.models import StrategySpec


def get_json_schema() -> dict:
    """Return the JSON Schema for StrategySpec."""
    schema = StrategySpec.model_json_schema()
    return schema


def get_json_schema_name() -> str:
    return "StrategySpec"


def get_json_schema_description() -> str:
    return (
        "A complete trading strategy specification. "
        "The LLM must produce valid JSON matching this schema — "
        "no markdown, no explanations, only the JSON object."
    )


def pretty_schema() -> str:
    """Return a human-readable version of the schema (for system prompt)."""
    import json
    schema = get_json_schema()
    # Simplify for embedding in prompt — remove $defs and keep required fields
    return json.dumps(schema, indent=2, ensure_ascii=False)
