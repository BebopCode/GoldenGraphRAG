"""Prompt construction.

The ontology is injected into the prompt as the *only* allowed labels. This is
the single biggest lever on extraction quality: a closed label set prevents the
messy, inconsistent graphs that free-form extraction produces.
"""

from __future__ import annotations

from kg.config.models import Ontology

SYSTEM_PROMPT = (
    "You are a precise knowledge-graph extraction engine. From the text you are "
    "given, identify entities and the relationships between them, using ONLY the "
    "node labels and relationship labels listed in the schema. "
    "Return ONLY a single JSON object — no prose, no code fences, no commentary. "
    "Every relationship's source_name and target_name must exactly match the "
    "`name` of an entity you also extracted."
)

_OUTPUT_FORMAT_HINT = """\
Return JSON shaped exactly like this:
{
  "entities": [
    {"name": "<display name>", "label": "<node label>", "properties": {"<k>": "<v>"}}
  ],
  "relationships": [
    {"source_name": "<name>", "target_name": "<name>",
     "label": "<rel label>", "properties": {"<k>": "<v>"}}
  ]
}"""

_RETRY_REMINDER = (
    "Your previous response was not valid JSON or did not match the schema. "
    "Try again and return ONLY the JSON object described above, nothing else."
)


def _describe_ontology(ontology: Ontology) -> str:
    lines: list[str] = []
    lines.append("ALLOWED NODE LABELS (use only these for entity.label):")
    for nt in ontology.node_types:
        desc = f" — {nt.description}" if nt.description else ""
        props = f" (properties: {', '.join(nt.properties)})" if nt.properties else ""
        lines.append(f"  - {nt.label}{desc}{props}")
    if ontology.relationship_types:
        lines.append("ALLOWED RELATIONSHIP LABELS (use only these for relationship.label):")
        for rt in ontology.relationship_types:
            desc = f" — {rt.description}" if rt.description else ""
            lines.append(f"  - {rt.label}: {rt.source} -> {rt.target}{desc}")
    else:
        lines.append(
            "ALLOWED RELATIONSHIP LABELS: (none defined; return an empty relationships list)"
        )
    return "\n".join(lines)


def build_extraction_prompt(chunk_text: str, ontology: Ontology) -> str:
    """Build the user prompt: ontology schema + output format + the text."""
    return (
        f"{_describe_ontology(ontology)}\n\n"
        f"{_OUTPUT_FORMAT_HINT}\n\n"
        f'TEXT:\n"""\n{chunk_text}\n"""\n'
    )


def build_retry_prompt(base_prompt: str) -> str:
    return f"{base_prompt}\n\n{_RETRY_REMINDER}"
