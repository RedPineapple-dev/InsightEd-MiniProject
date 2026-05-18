"""
LLM Engine — public-facing API used by alignment_engine and annotation_engine.

Thin facade over `services.llm`. Adds:
  - retry with exponential backoff on transient errors
  - structured-output validation via Pydantic
  - JSON-only output via `response_mime_type='application/json'`
  - graceful fallbacks — callers always get *something*
  - **batched** annotation generation for ~6× fewer API calls
  - **slimmed** prompts to reduce token usage

Public API:
  - match_segment_to_document(segment_text, candidates)
  - generate_annotations(segment_text)
  - generate_annotations_batch(units)        # NEW
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from services.llm import LLMError, get_llm

load_dotenv(override=True)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")


# ── Schemas ───────────────────────────────────────────────────────────────

class MatchResult(BaseModel):
    type: str = Field(description="'slide' or 'pdf'")
    id: int
    reason: str = ""
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        v = (v or "").lower().strip()
        if v not in {"slide", "pdf"}:
            raise ValueError("type must be 'slide' or 'pdf'")
        return v


class ConceptAnnotation(BaseModel):
    concept: str
    explanation: str
    importance: str = "medium"

    @field_validator("importance")
    @classmethod
    def _normalize_importance(cls, v: str) -> str:
        v = (v or "medium").lower().strip()
        return v if v in {"high", "medium", "low"} else "medium"


class AnnotationResult(BaseModel):
    concepts: List[ConceptAnnotation] = Field(default_factory=list)


class BatchAnnotationUnit(BaseModel):
    id: int
    concepts: List[ConceptAnnotation] = Field(default_factory=list)


class BatchAnnotationResult(BaseModel):
    results: List[BatchAnnotationUnit] = Field(default_factory=list)


# ── Prompt builders (slim) ────────────────────────────────────────────────

def build_matching_prompt(segment_text: str, candidates: List[Dict[str, Any]]) -> str:
    lines = [
        "Pick the candidate that best matches the transcript segment.",
        "",
        f"Segment: {segment_text.strip()[:1400]}",
        "",
        "Candidates:",
    ]
    for cand in candidates:
        doc_type = cand.get("type", "?")
        doc_id = cand.get("id", "?")
        doc_text = (cand.get("text") or "").strip().replace("\n", " ")[:240]
        lines.append(f"- {doc_type}#{doc_id}: {doc_text}")
    lines.append('JSON only: {"type":"slide|pdf","id":<int>,"reason":"<short>","confidence":<0..1>}')
    return "\n".join(lines)


_ANNOTATION_SYSTEM_RULES = (
    "Extract concepts actually explained in the transcript. "
    "Use canonical technical forms (LR0, FOLLOW, FIRST, NFA, DFA, CFG, GOTO). "
    "Max 4 concepts. Skip filler. Don't invent. "
    "Importance: high|medium|low."
)


def build_annotation_prompt(segment_text: str) -> str:
    return (
        f"{_ANNOTATION_SYSTEM_RULES}\n\n"
        f"Transcript: {segment_text.strip()[:1800]}\n\n"
        'JSON only: {"concepts":[{"concept":"...","explanation":"...","importance":"high|medium|low"}]}'
    )


def build_batch_annotation_prompt(units: List[Dict[str, Any]]) -> str:
    """Pack N segments into one Gemini call.

    Each unit must have {"id": int, "text": str}. The model returns a JSON
    array keyed by id so we can de-multiplex on the client.
    """
    parts = [
        _ANNOTATION_SYSTEM_RULES,
        "For EACH segment below return its concepts list (empty if filler).",
        "",
    ]
    for u in units:
        parts.append(f"#{u['id']}: {(u.get('text') or '').strip()[:1100]}")
    parts.append(
        '\nJSON only: {"results":[{"id":<int>,"concepts":'
        '[{"concept":"...","explanation":"...","importance":"high|medium|low"}]}]}'
    )
    return "\n".join(parts)


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

    valid = any(
        c.get("type") == result.type and c.get("id") == result.id for c in candidates
    )
    if not valid:
        print(
            f"[llm_engine] LLM returned non-candidate match "
            f"{result.type}#{result.id}, falling back"
        )
        return fallback

    return result.model_dump()


def generate_annotations(
    segment_text: str,
    model_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract concept annotations from a transcript segment (single call).

    Prefer ``generate_annotations_batch`` when annotating multiple units;
    this single-call version is kept for backward compatibility.
    """
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
            temperature=0.2,
            cache_namespace="annotation",
        )
    except LLMError as exc:
        print(f"[llm_engine] annotation failed: {exc}")
        return []

    if not result:
        return []
    return [c.model_dump() for c in result.concepts]


def generate_annotations_batch(
    units: List[Dict[str, Any]],
    model_name: Optional[str] = None,
) -> Dict[int, List[Dict[str, Any]]]:
    """Batched annotation generation.

    Args:
        units: list of {"id": int, "text": str}. Group of 5–8 is ideal.

    Returns:
        dict mapping id -> list of concept dicts. Missing/failed ids map to [].
    """
    if not units:
        return {}

    ids = [int(u["id"]) for u in units]
    empty = {i: [] for i in ids}

    llm = get_llm()
    if not llm.is_available():
        return empty

    prompt = build_batch_annotation_prompt(units)
    try:
        result = llm.generate_json(
            prompt,
            BatchAnnotationResult,
            model=model_name or DEFAULT_MODEL,
            temperature=0.2,
            cache_namespace="annotation_batch",
        )
    except LLMError as exc:
        print(f"[llm_engine] batch annotation failed ({len(units)} units): {exc}")
        return empty

    if not result:
        return empty

    out: Dict[int, List[Dict[str, Any]]] = {i: [] for i in ids}
    for r in result.results:
        if r.id in out:
            out[r.id] = [c.model_dump() for c in r.concepts]
    return out


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
