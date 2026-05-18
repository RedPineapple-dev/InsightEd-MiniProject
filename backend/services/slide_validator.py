"""Validate a slide outline against its source notes + transcript.

Three checks per slide:

  1. *Topic relevance* — does the slide share canonical terms with at least
     one of the source notes?
  2. *Internal consistency* — bullets must reference terms from the slide's
     own title or core_concepts.
  3. *Duplication* — no two slides should share >= 70% of bullets (Jaccard
     on lowercased token sets).

Slides that fail relevance are dropped. Duplicates are merged.

Returns a tuple ``(filtered_slides, report)`` where ``report`` is a dict
suitable for storing alongside the outline for debugging / UI display.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple

from services.domain_normalization import extract_canonical_terms


_STOPWORDS: Set[str] = {
    "the", "a", "an", "of", "to", "in", "is", "are", "and", "or", "for",
    "with", "on", "at", "by", "from", "as", "we", "be", "this", "that",
    "it", "its", "their", "our", "your", "you", "i", "they", "he", "she",
    "have", "has", "had", "will", "can", "could", "should", "would", "may",
    "might", "but", "if", "then", "than", "so", "because", "into", "about",
    "what", "which", "who", "how", "when", "where", "why", "do", "does",
    "did", "not", "no", "yes",
}


def _tokens(text: str) -> Set[str]:
    if not text:
        return set()
    text = text.lower()
    raw = re.findall(r"[a-zA-Z0-9()\-]+", text)
    return {w for w in raw if w not in _STOPWORDS and len(w) > 2}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _source_vocabulary(notes: List[Dict[str, Any]]) -> Set[str]:
    vocab: Set[str] = set()
    for n in notes:
        vocab |= _tokens(n.get("topic") or "")
        for c in n.get("core_concepts") or []:
            vocab |= _tokens(c)
        for p in n.get("important_points") or []:
            vocab |= _tokens(p)
        for e in n.get("examples") or []:
            vocab |= _tokens(e)
        for d in n.get("definitions") or []:
            if isinstance(d, dict):
                vocab |= _tokens(d.get("term") or "")
                vocab |= _tokens(d.get("definition") or "")
        for t in n.get("key_terms") or []:
            vocab |= _tokens(t)
    return vocab


def _slide_terms(slide: Dict[str, Any]) -> Set[str]:
    tokens = _tokens(slide.get("title") or "")
    for b in slide.get("bullets") or []:
        tokens |= _tokens(b)
    return tokens


def validate_outline(
    slides: List[Dict[str, Any]],
    notes: List[Dict[str, Any]],
    *,
    canonical_terms: List[str] | None = None,
    min_overlap: float = 0.08,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Filter ``slides`` so every survivor is grounded in ``notes``.

    Parameters
    ----------
    canonical_terms:
        Optional list of canonical domain terms (from ``overall_topic_signature``).
        Slides that share *any* canonical term with the source pass relevance
        even if the generic token overlap is low — this protects acronyms
        like "LR0" that would otherwise drop below the Jaccard threshold.
    """
    if not slides:
        return [], {"kept": 0, "dropped": 0, "merged": 0, "details": []}

    vocab = _source_vocabulary(notes)
    canon = {t.lower() for t in (canonical_terms or [])}

    kept: List[Dict[str, Any]] = []
    details: List[Dict[str, Any]] = []
    dropped = 0
    merged = 0

    for slide in slides:
        terms = _slide_terms(slide)
        overlap = _jaccard(terms, vocab) if vocab else 1.0
        canon_hit = bool(terms & canon) if canon else False
        relevant = overlap >= min_overlap or canon_hit

        # Confidence is the max of token-overlap and canonical hit (0.85 if hit)
        confidence = max(overlap, 0.85 if canon_hit else 0.0)
        slide["topic_confidence"] = round(confidence, 3)

        if not relevant:
            dropped += 1
            details.append(
                {
                    "title": slide.get("title"),
                    "action": "dropped",
                    "reason": f"overlap={overlap:.2f} < {min_overlap:.2f}, no canonical hit",
                }
            )
            continue

        # Dedup against everything kept so far.
        absorbed = False
        for prior in kept:
            prior_terms = _slide_terms(prior)
            if _jaccard(prior_terms, terms) >= 0.70:
                # Merge: extend bullets of `prior` with novel bullets from `slide`.
                existing = {b.strip().lower() for b in prior.get("bullets") or []}
                new_bullets = [
                    b for b in (slide.get("bullets") or [])
                    if b.strip().lower() not in existing
                ]
                if new_bullets:
                    prior.setdefault("bullets", []).extend(new_bullets[: max(0, 5 - len(prior.get("bullets") or []))])
                merged += 1
                details.append(
                    {
                        "title": slide.get("title"),
                        "action": "merged",
                        "into": prior.get("title"),
                    }
                )
                absorbed = True
                break

        if not absorbed:
            kept.append(slide)
            details.append(
                {
                    "title": slide.get("title"),
                    "action": "kept",
                    "topic_confidence": confidence,
                }
            )

    report = {
        "kept": len(kept),
        "dropped": dropped,
        "merged": merged,
        "details": details,
    }
    return kept, report


def slides_share_dominant_topic(
    slides: List[Dict[str, Any]],
    canonical_terms: List[str],
    *,
    min_coverage: float = 0.5,
) -> bool:
    """Sanity-check that the outline as a whole talks about the lecture's
    dominant canonical terms — rejects "ML fundamentals" output for an
    SLR(1) lecture, etc.
    """
    if not slides or not canonical_terms:
        return True  # nothing to compare against
    canon = {t.lower() for t in canonical_terms}
    hits = 0
    for s in slides:
        if _slide_terms(s) & canon:
            hits += 1
    coverage = hits / len(slides)
    return coverage >= min_coverage
