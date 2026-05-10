"""
LLM Engine Module — public-facing API used by alignment_engine and annotation_engine.

This module is now a thin facade over `services.llm` (Part 8 refactor).
The original function signatures are preserved so the rest of the codebase
keeps working unchanged.

Improvements:
  - retry with exponential backoff on transient errors (rate limits, 5xx)
  - structured-output validation via Pydantic
  - guaranteed JSON output via `response_mime_type="application/json"`
  - graceful fallbacks — callers always get *something*

Public API (unchanged):
  - match_segment_to_document(segment_text, candidates)
  - generate_annotations(segment_text)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from services.llm import LLMError, get_llm

load_dotenv(override=True)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


# ── Schemas ───────────────────────────────────────────────────────────────

class MatchResult(BaseModel):
    type: str = Field(description="Must be 'slide' or 'pdf'")
    id: int = Field(description="The ID of the matched document/slide")
    reason: str = Field(description="Short explanation of why this is the best match")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0", ge=0.0, le=1.0)

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        v = (v or "").lower().strip()
        if v not in {"slide", "pdf"}:
            raise ValueError("type must be 'slide' or 'pdf'")
        return v


class ConceptAnnotation(BaseModel):
    concept: str = Field(description="The name of the concept extracted")
    explanation: str = Field(description="Clear and concise explanation of the concept")
    importance: str = Field(description="Importance level: high, medium, or low")

    @field_validator("importance")
    @classmethod
    def _normalize_importance(cls, v: str) -> str:
        v = (v or "medium").lower().strip()
        return v if v in {"high", "medium", "low"} else "medium"


class AnnotationResult(BaseModel):
    concepts: List[ConceptAnnotation] = Field(default_factory=list)


# ── Prompt builders ───────────────────────────────────────────────────────

def build_matching_prompt(segment_text: str, candidates: List[Dict[str, Any]]) -> str:
    lines = [
        "You are an AI system that links lecture video segments to slides or PDF pages.",
        "Read the transcript segment, then pick the candidate that best matches.",
        "Prefer matches where the slide explicitly covers the concepts in the segment.",
        "",
        "Transcript segment:",
        segment_text.strip(),
        "",
        "Candidates:",
    ]
    for idx, cand in enumerate(candidates, start=1):
        doc_type = cand.get("type", "unknown")
        doc_id = cand.get("id", "?")
        doc_text = (cand.get("text") or "").strip().replace("\n", " ")
        lines.append(f"{idx}. ({doc_type} {doc_id}): {doc_text[:300]}")
    lines.extend(
        [
            "",
            "Respond with strict JSON ONLY:",
            '{"type": "slide|pdf", "id": <int>, "reason": "<short>", "confidence": <0..1>}',
        ]
    )
    return "\n".join(lines)


def build_annotation_prompt(segment_text: str) -> str:
    return (
        "You are an educational annotator. Extract the most important concepts "
        "from the lecture transcript below.\n\n"
        "For each concept return: concept name, a 1-2 sentence student-friendly "
        "explanation, and an importance label of high/medium/low.\n\n"
        "Skip filler ('today we'll cover', 'thanks for watching').\n"
        "Return at most 4 concepts.\n\n"
        f"Transcript:\n\"\"\"{segment_text.strip()}\"\"\"\n\n"
        "Respond with strict JSON ONLY:\n"
        '{"concepts": [{"concept": "...", "explanation": "...", "importance": "high|medium|low"}]}'
    )


# ── Public API ────────────────────────────────────────────────────────────

def match_segment_to_document(
    segment_text: str,
    candidates: List[Dict[str, Any]],
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Match a transcript segment to its best candidate slide/page."""
    if not candidates:
        raise ValueError("No candidates provided")

    fallback = {
        "type": candidates[0].get("type", "unknown"),
        "id": candidates[0].get("id", 0),
        "reason": "Fallback to top embedding candidate.",
        "confidence": 0.5,
    }

    llm = get_llm()
    if not llm.is_available():
        return {**fallback, "reason": "LLM unavailable — using top embedding candidate."}

    prompt = build_matching_prompt(segment_text, candidates)

    try:
        result = llm.generate_json(
            prompt,
            MatchResult,
            model=model_name or DEFAULT_MODEL,
            cache_namespace="alignment",
        )
    except LLMError as exc:
        print(f"[llm_engine] match failed: {exc}")
        return {**fallback, "reason": f"LLM error: {exc}", "confidence": 0.0}

    if not result:
        return fallback

    # Cross-check the candidate exists
    valid = any(
        c.get("type") == result.type and c.get("id") == result.id for c in candidates
    )
    if not valid:
        print(f"[llm_engine] LLM returned non-candidate match {result.type}#{result.id}, falling back")
        return fallback

    return result.model_dump()


def generate_annotations(
    segment_text: str,
    model_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract concept annotations from a transcript segment."""
    text = (segment_text or "").strip()
    if not text:
        return []

    llm = get_llm()
    if not llm.is_available():
        return []

    prompt = build_annotation_prompt(text)
    try:
        result = llm.generate_json(
            prompt,
            AnnotationResult,
            model=model_name or DEFAULT_MODEL,
            temperature=0.25,
            cache_namespace="annotation",
        )
    except LLMError as exc:
        print(f"[llm_engine] annotation failed: {exc}")
        return []

    if not result:
        return []
    return [c.model_dump() for c in result.concepts]


# Backwards-compat: some legacy callers may import these directly.
def clean_json_response(text: str) -> Dict[str, Any]:
    """Kept for backward compatibility — used by older code paths."""
    import json
    s = (text or "").strip()
    if s.startswith("```json"):
        s = s[len("```json"):].strip()
    elif s.startswith("```"):
        s = s[len("```"):].strip()
    if s.endswith("```"):
        s = s[:-3].strip()
    return json.loads(s)
