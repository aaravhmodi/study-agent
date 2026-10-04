"""Deterministic assessment-to-coursework matching for the local dashboard."""

import re
from collections.abc import Sequence
from typing import Any

from app.models import Assessment, Resource

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "post",
    "pre",
    "the",
    "to",
    "with",
}


def relevant_coursework(
    assessment: Assessment, resources: Sequence[Resource], limit: int = 8
) -> list[dict[str, Any]]:
    """Rank stored course resources against an assessment without using an LLM."""
    assessment_tokens = _tokens(
        f"{assessment.title} {assessment.assessment_type} {assessment.description or ''}"
    )
    ranked: list[tuple[float, Resource, set[str]]] = []
    for resource in resources:
        title_tokens = _tokens(resource.title)
        description_tokens = _tokens(resource.description or "")
        overlap = assessment_tokens & (title_tokens | description_tokens)
        title_overlap = assessment_tokens & title_tokens
        score = len(overlap) + len(title_overlap) * 1.5
        if resource.resource_type in {"PDF", "SLIDES", "DOCUMENT", "PAGE"}:
            score += 0.1
        ranked.append((score, resource, overlap))

    ranked.sort(key=lambda item: (item[0], item[1].first_seen_at), reverse=True)
    selected = ranked[:limit]
    return [
        {
            "id": resource.id,
            "title": resource.title,
            "type": resource.resource_type,
            "url": resource.url,
            "description": resource.description,
            "match_reason": (
                f"Matched terms: {', '.join(sorted(overlap))}"
                if overlap
                else "Course material for this assessment; no exact title match was available."
            ),
        }
        for _, resource, overlap in selected
    ]


def study_guidance(assessment: Assessment) -> list[str]:
    """Return practical study actions based on the assessment type."""
    kind = assessment.assessment_type.lower()
    if kind in {"quiz", "test", "exam"}:
        return [
            "Review the matched notes or slides once to map the examinable concepts.",
            (
                "Close the notes and use active recall: write the key definitions, steps, "
                "and formulas from memory."
            ),
            (
                "Work practice questions without looking at the solution, then mark weak "
                "areas for a second pass."
            ),
        ]
    if kind in {"assignment", "lab", "project"}:
        return [
            (
                "Read the instructions and submission notes first; turn every deliverable "
                "into a checklist."
            ),
            "Review the matched concepts and one worked example before starting the deliverable.",
            (
                "Draft, test, or solve in small sections, then compare your work against "
                "the rubric or requirements."
            ),
        ]
    return [
        "Read the matched coursework and write a short summary of the concepts it covers.",
        (
            "Use active recall to list what you can explain and mark anything that still "
            "feels unclear."
        ),
        "Finish with a small practice problem or self-test before moving on.",
    ]


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]{3,}", value.casefold()) if token not in _STOP_WORDS
    }
