"""Structured educational notes — one note record per topic chunk.

Given a topic chunk (transcript + optional OCR), produce a strict JSON
schema that downstream slide/PDF generators can consume directly:

    {
        "topic": "SLR(1) Parsing — Item Construction",
        "core_concepts": ["LR0 items", "closure", "GOTO"],
        "important_points": [
            "An LR0 item is a production with a dot marking parser progress.",
            ...
        ],
        "definitions": [{"term": "Closure", "definition": "..."}],
        "examples": ["S -> .E   →   S -> E.   after shifting"],
        "formulas": ["closure(I) = I ∪ { B -> .γ | A -> α.Bβ ∈ closure(I) }"],
        "exam_points": ["State the difference between LR(0) and SLR(1)."],
        "confidence": 0.83,
        "supporting_quotes": ["...short verbatim quote from transcript..."],
        "off_topic": false
    }

The note is **grounded**: the LLM is instructed to only emit content that
is directly supported by the chunk, and to return ``off_topic=true`` plus
empty arrays when the chunk is too generic (e.g. an intro greeting).

If the LLM is unavailable, we fall back to a deterministic extractor that
populates the same shape from heuristics — never blank.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from services.domain_normalization import extract_canonical_terms, normalize_text
from services.llm import LLMError, get_llm
from services.text_processing import normalize_whitespace
from services.topic_segmentation import fuse_chunk_context


# ── Schema ───────────────────────────────────────────────────────────────


class Definition(BaseModel):
    term: str = Field(description="Term being defined")
    definition: str = Field(description="One-sentence definition")


class StructuredNote(BaseModel):
    topic: str = Field(default="", description="Concise topic title (<=10 words)")
    core_concepts: List[str] = Field(default_factory=list)
    important_points: List[str] = Field(default_factory=list)
    definitions: List[Definition] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    formulas: List[str] = Field(default_factory=list)
    exam_points: List[str] = Field(default_factory=list)
    supporting_quotes: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    off_topic: bool = Field(default=False)


# ── Prompt ───────────────────────────────────────────────────────────────


_NOTE_PROMPT = """\
You are an expert lecture note-taker. From the CONTEXT below (transcript +
optional slide OCR), produce **strictly grounded** study notes — meaning every
single statement you emit must be directly supported by the context.

Rules — NEVER violate these:
  * Use ONLY the concepts that appear in the context. Do NOT introduce topics
    you've seen in similar lectures.
  * If the context is just a greeting / filler / off-topic chatter, set
    "off_topic": true and return empty arrays. Do not invent content.
  * Preserve canonical technical terms verbatim: LR0, SLR(1), FIRST, FOLLOW,
    CFG, NFA, DFA, GOTO, closure, augmented grammar, epsilon, etc.
  * Definitions must paraphrase the speaker — do not pull dictionary entries.
  * Each "supporting_quotes" entry must be a short (<=25 word) verbatim slice
    of the transcript that justifies the note. At least one quote per note.
  * "confidence" reflects how strongly the chunk discusses one clear topic:
    1.0 = unambiguous focused explanation; 0.4 = mixed; 0 = no real content.

Output STRICT JSON ONLY of the shape:
{{
  "topic": "<=10 word title",
  "core_concepts": ["..."],
  "important_points": ["..."],
  "definitions": [{{"term": "...", "definition": "..."}}],
  "examples": ["..."],
  "formulas": ["..."],
  "exam_points": ["..."],
  "supporting_quotes": ["..."],
  "confidence": <0..1>,
  "off_topic": <bool>
}}

CONTEXT:
{context}
"""


# ── Heuristic fallback ───────────────────────────────────────────────────


def _heuristic_note(chunk: Dict[str, Any]) -> StructuredNote:
    text = normalize_whitespace(chunk.get("text") or "")
    terms = chunk.get("key_terms") or extract_canonical_terms(text)
    if not text:
        return StructuredNote(off_topic=True)

    # Topic title: first canonical term + first sentence keyword
    title_hint = (chunk.get("title_hint") or "").rstrip(".!?")
    if not title_hint:
        title_hint = text[:60]
    topic = (terms[0] + " — " + title_hint) if terms else title_hint

    sentences = [s.strip() for s in _split_sentences(text) if len(s.strip()) > 12]
    important = sentences[:4]
    examples = [s for s in sentences if " example" in s.lower() or "for instance" in s.lower()][:2]
    formulas = [s for s in sentences if "->" in s or "→" in s or "=" in s][:2]

    return StructuredNote(
        topic=topic[:80],
        core_concepts=terms[:6] or [w for w in title_hint.split() if w.istitle()][:4],
        important_points=important,
        definitions=[],
        examples=examples,
        formulas=formulas,
        exam_points=[],
        supporting_quotes=sentences[:1],
        confidence=0.45,
        off_topic=False,
    )


def _split_sentences(text: str) -> List[str]:
    import re

    pieces = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in pieces if p.strip()]


# ── Public API ───────────────────────────────────────────────────────────


def generate_note(chunk: Dict[str, Any], *, allow_llm: bool = True) -> Dict[str, Any]:
    """Produce one structured-note dict for ``chunk``."""
    if not chunk or not (chunk.get("text") or "").strip():
        return StructuredNote(off_topic=True).model_dump()

    llm = get_llm() if allow_llm else None
    parsed: Optional[StructuredNote] = None

    if llm and llm.is_available():
        context = fuse_chunk_context(chunk, max_chars=4500)
        prompt = _NOTE_PROMPT.format(context=context)
        try:
            parsed = llm.generate_json(
                prompt,
                StructuredNote,
                temperature=0.15,
                max_retries=2,
                cache_namespace="structured_note",
            )
        except LLMError as exc:
            print(f"[notes] LLM failed for chunk {chunk.get('chunk_id')}: {exc}")
            parsed = None

    if not parsed:
        parsed = _heuristic_note(chunk)

    # Post-process: drop hallucinated bullets that don't share a single
    # canonical term with the source. This is the cheap topic-grounding guard.
    source_terms = set(
        t.lower()
        for t in (chunk.get("key_terms") or []) + (chunk.get("ocr_terms") or [])
    )
    if source_terms and not parsed.off_topic:
        def _is_grounded(b: str) -> bool:
            low = (b or "").lower()
            return any(t in low for t in source_terms) or any(
                term.lower() in low for term in extract_canonical_terms(b)
            )

        # Only filter if at least some bullets are grounded — otherwise we'd
        # nuke the entire chunk and emit nothing useful.
        grounded_points = [p for p in parsed.important_points if _is_grounded(p)]
        if grounded_points:
            parsed.important_points = grounded_points
        grounded_examples = [e for e in parsed.examples if _is_grounded(e)]
        if grounded_examples:
            parsed.examples = grounded_examples

    out = parsed.model_dump()
    # Echo chunk metadata so the slide layer doesn't have to look it up.
    out["chunk_id"] = chunk.get("chunk_id")
    out["start"] = chunk.get("start")
    out["end"] = chunk.get("end")
    out["timestamp"] = chunk.get("timestamp")
    return out


def generate_notes(chunks: List[Dict[str, Any]], *, allow_llm: bool = True) -> List[Dict[str, Any]]:
    """Produce notes for every chunk. Skips chunks flagged ``off_topic``
    when the LLM judges them so."""
    notes: List[Dict[str, Any]] = []
    for c in chunks:
        n = generate_note(c, allow_llm=allow_llm)
        notes.append(n)
    return notes


def select_publishable_notes(notes: List[Dict[str, Any]], *, min_confidence: float = 0.4) -> List[Dict[str, Any]]:
    """Filter out off-topic / low-confidence notes before slide generation."""
    out: List[Dict[str, Any]] = []
    for n in notes:
        if n.get("off_topic"):
            continue
        conf = float(n.get("confidence") or 0.0)
        if conf < min_confidence and not (n.get("core_concepts") or n.get("important_points")):
            continue
        out.append(n)
    return out
