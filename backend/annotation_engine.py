"""Annotation Engine.

Builds the timeline annotations that show up beside the video. The new
implementation does three things differently from the previous one:

  1. **Uses topic chunks when available.** If the pipeline has already
     run topic segmentation, we annotate one chunk = one annotation. This
     keeps annotation boundaries aligned with the slides/PDF/PPTX and
     avoids the "100-segment soup" that produced wildly off-topic
     concepts on long videos.
  2. **Normalises text before LLM calls.** We run the transcript through
     the domain normaliser so canonical terms (LR0, FOLLOW, …) reach the
     LLM with the correct spelling. This dramatically reduces "wrong
     topic" hallucinations on multilingual lectures.
  3. **Semantic dedup + confidence.** After generation we walk every
     concept and drop near-duplicates (string OR embedding similarity)
     and attach a 0..1 confidence score derived from the LLM's importance
     label plus a grounding check.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

import numpy as np

from llm_engine import generate_annotations, generate_annotations_batch
from services.domain_normalization import (
    extract_canonical_terms,
    normalize_text,
)
from services.recommendations import gather_resources
from services.text_processing import join_segments
from services.topic_extraction import extract_topics


# ── Filler / stopword heuristics ─────────────────────────────────────────
# Drop these BEFORE making an LLM call — they never produce useful
# concepts and silently burn quota.

_GREETING_PREFIXES = (
    "hello", "hi ", "hey", "welcome", "thanks", "thank you",
    "good morning", "good afternoon", "good evening",
    "okay guys", "ok guys", "alright", "all right",
    "so today", "today we", "today's", "in this video",
    "let's begin", "let's start", "let me", "uh ", "um ",
    "yeah", "right so", "okay so",
)

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "as",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "to", "of", "in", "on", "at", "for", "from", "by", "with",
    "about", "into", "over", "after", "before", "this", "that",
    "these", "those", "it", "its", "i", "you", "we", "they", "he",
    "she", "him", "her", "them", "us", "my", "your", "our",
    "have", "has", "had", "do", "does", "did", "can", "could",
    "will", "would", "should", "may", "might", "must", "shall",
    "not", "no", "yes", "okay", "ok", "well", "just", "really",
    "very", "much", "many", "lot", "more", "most", "some", "any",
    "all", "each", "every", "now", "then", "here", "there",
    "what", "when", "where", "why", "how", "which", "who",
    "uh", "um", "like", "kind", "sort", "thing", "stuff",
}


def is_filler_segment(text: str) -> bool:
    """Heuristic: is this segment too thin to bother sending to the LLM?

    Returns True for greetings, stopword-only chatter, or sub-15-word
    fragments. Used as a pre-filter before batched LLM calls.
    """
    t = (text or "").strip().lower()
    if not t:
        return True

    words = re.findall(r"[a-z][a-z']+", t)
    if len(words) < 15:
        return True

    non_stop = [w for w in words if w not in _STOPWORDS and len(w) > 2]
    # Even in long-ish chunks, if there's almost no content word the LLM
    # has nothing to grab onto.
    if len(non_stop) < 5:
        return True

    # Short greeting-only segments: starts with a greeting and is itself short.
    if len(words) < 25 and any(t.startswith(p) for p in _GREETING_PREFIXES):
        return True

    return False


def resource_search_links(concept: str) -> List[Dict[str, Any]]:
    if not concept:
        return []
    return gather_resources(concept, limit=12)


_IMPORTANCE_CONFIDENCE = {"high": 0.9, "medium": 0.7, "low": 0.5}


def _concept_confidence(concept: Dict[str, Any], grounded: bool) -> float:
    base = _IMPORTANCE_CONFIDENCE.get((concept.get("importance") or "medium").lower(), 0.6)
    if not grounded:
        base -= 0.25
    return round(max(0.0, min(1.0, base)), 3)


def _grounded_in_source(text: str, source_text: str) -> bool:
    """Cheap grounding check: does the concept share canonical terms with
    the source chunk, or does its name appear verbatim in the source?"""
    if not text or not source_text:
        return False
    low_src = source_text.lower()
    if text.lower() in low_src:
        return True
    canon_concept = {t.upper() for t in extract_canonical_terms(text)}
    canon_source = {t.upper() for t in extract_canonical_terms(source_text)}
    return bool(canon_concept & canon_source)


def _semantic_dedup(
    concepts: List[Dict[str, Any]],
    embedding_engine=None,
    *,
    name_sim: float = 0.88,
    explanation_sim: float = 0.85,
) -> List[Dict[str, Any]]:
    """Drop concepts that semantically duplicate an earlier one.

    Two-pass:
      * cheap: case-insensitive exact name match
      * embedding: cosine sim of concept name (and explanation, if engine
        available)
    """
    if not concepts:
        return []

    out: List[Dict[str, Any]] = []
    seen_names: List[str] = []
    name_vecs: List[np.ndarray] = []
    expl_vecs: List[np.ndarray] = []

    use_emb = (
        embedding_engine is not None
        and hasattr(embedding_engine, "encode_single")
        and hasattr(embedding_engine, "cosine_similarity")
    )

    for c in concepts:
        name = (c.get("concept") or "").strip()
        expl = (c.get("explanation") or "").strip()
        if not name:
            continue

        # Cheap dedup first
        norm_name = re.sub(r"\s+", " ", name.lower())
        if any(norm_name == n for n in seen_names):
            continue

        keep = True
        if use_emb:
            try:
                nv = embedding_engine.encode_single(name)
                ev = embedding_engine.encode_single(expl) if expl else None
            except Exception:
                nv = None
                ev = None

            if nv is not None:
                for prior_nv in name_vecs:
                    if embedding_engine.cosine_similarity(nv, prior_nv) >= name_sim:
                        keep = False
                        break
            if keep and ev is not None and expl_vecs:
                for prior_ev in expl_vecs:
                    if embedding_engine.cosine_similarity(ev, prior_ev) >= explanation_sim:
                        keep = False
                        break

            if keep:
                if nv is not None:
                    name_vecs.append(nv)
                if ev is not None:
                    expl_vecs.append(ev)

        if keep:
            seen_names.append(norm_name)
            out.append(c)

    return out


class AnnotationEngine:
    def __init__(self, embedding_engine=None):
        self.ee = embedding_engine

    # ── Annotation generation ───────────────────────────────────────────
    def annotate_transcript(
        self,
        transcript: List[Dict[str, Any]],
        embeddings: Dict[str, Any],
        *,
        chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Produce one annotation per topic chunk (preferred) or per ~100
        transcript segments (legacy fallback).

        Pass ``chunks`` from ``services.topic_segmentation.segment_transcript``
        to keep annotations aligned with the slide/PDF/PPTX output.
        """
        if not transcript:
            return []

        from services.llm import get_llm

        llm = get_llm()

        # Build the list of (chunk_text, target_segment, start, end, ctx_chunk)
        units: List[Dict[str, Any]] = []
        if chunks:
            seg_by_id = {s.get("id"): s for s in transcript}
            for c in chunks:
                seg_ids = c.get("segment_ids") or []
                seg_slice = [seg_by_id[i] for i in seg_ids if i in seg_by_id] or transcript[: 0]
                if not seg_slice:
                    continue
                mid_idx = len(seg_slice) // 2
                target = seg_slice[mid_idx]
                units.append(
                    {
                        "text": normalize_text(c.get("text") or "", source="transcript"),
                        "target": target,
                        "start": float(c.get("start") or seg_slice[0].get("start") or 0.0),
                        "end": float(c.get("end") or seg_slice[-1].get("end") or 0.0),
                        "chunk_id": c.get("chunk_id"),
                    }
                )
        else:
            chunk_size = 100
            for i in range(0, len(transcript), chunk_size):
                slice_ = transcript[i : i + chunk_size]
                combined = normalize_text(
                    " ".join((s.get("text") or "") for s in slice_),
                    source="transcript",
                )
                target = slice_[len(slice_) // 2]
                units.append(
                    {
                        "text": combined,
                        "target": target,
                        "start": float(slice_[0].get("start") or 0.0),
                        "end": float(slice_[-1].get("end") or 0.0),
                        "chunk_id": None,
                    }
                )

        # ── Pre-filter filler units locally (no LLM call) ─────────────
        BATCH_SIZE = 6
        non_filler_idx: List[int] = []
        filler_skipped = 0
        for i, u in enumerate(units):
            if is_filler_segment(u["text"]):
                filler_skipped += 1
            else:
                non_filler_idx.append(i)

        # ── Batched LLM call ──────────────────────────────────────────
        # Group non-filler units into batches; one Gemini call per batch.
        concepts_by_unit: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(len(units))}

        if llm.is_available() and non_filler_idx:
            total_batches = (len(non_filler_idx) + BATCH_SIZE - 1) // BATCH_SIZE
            print(
                f"[AnnotationEngine] units={len(units)} filler_skipped={filler_skipped} "
                f"batches={total_batches} (size={BATCH_SIZE})"
            )
            for b_idx, start in enumerate(range(0, len(non_filler_idx), BATCH_SIZE)):
                window = non_filler_idx[start : start + BATCH_SIZE]
                payload = [{"id": i, "text": units[i]["text"]} for i in window]
                try:
                    result = generate_annotations_batch(payload)
                except Exception as exc:
                    print(f"[AnnotationEngine] batch {b_idx + 1}/{total_batches} failed: {exc}")
                    result = {}
                for i in window:
                    concepts_by_unit[i] = result.get(i, []) or []
                # Polite pacing between batches only — not between units.
                if b_idx < total_batches - 1:
                    time.sleep(1)
        elif filler_skipped:
            print(f"[AnnotationEngine] units={len(units)} all-filler={filler_skipped} no LLM call")

        # ── Format + ground each annotation ──────────────────────────
        annotations: List[Dict[str, Any]] = []
        for idx, unit in enumerate(units):
            text = unit["text"]
            target = unit["target"]
            concepts_raw = concepts_by_unit.get(idx, [])

            formatted: List[Dict[str, Any]] = []
            for c in concepts_raw:
                name = normalize_text(c.get("concept") or "", source="transcript").strip()
                expl = normalize_text(c.get("explanation") or "", source="transcript").strip()
                if not name:
                    continue
                grounded = _grounded_in_source(name, text)
                conf = _concept_confidence(c, grounded)
                if not grounded and conf < 0.45:
                    continue  # likely hallucinated — drop
                formatted.append(
                    {
                        "concept": name,
                        "explanation": expl or "Discussed in this segment.",
                        "importance": (c.get("importance") or "medium").lower(),
                        "confidence": conf,
                        "grounded": grounded,
                    }
                )

            if not formatted:
                continue

            annotations.append(
                {
                    "id": target.get("id", idx),
                    "timestamp": target.get("timestamp", "00:00"),
                    "start": unit["start"],
                    "end": unit["end"],
                    "text": text,
                    "concepts": formatted,
                    "primary_concept": formatted[0]["concept"],
                    "chunk_id": unit.get("chunk_id"),
                    "confidence": round(
                        sum(c["confidence"] for c in formatted) / len(formatted), 3
                    ),
                }
            )

        # Global semantic dedup across all annotations' concept lists.
        # We dedup the *concept* records, not the annotation envelopes —
        # repeated concepts inside the same annotation are already dropped.
        for ann in annotations:
            ann["concepts"] = _semantic_dedup(ann["concepts"], embedding_engine=self.ee)
            if not ann["concepts"]:
                continue
            ann["primary_concept"] = ann["concepts"][0]["concept"]

        # Drop empty annotations that lost everything to dedup.
        annotations = [a for a in annotations if a.get("concepts")]

        return annotations

    # ── Recommendation (unchanged behaviour) ────────────────────────────
    def recommend(
        self,
        concept: Optional[str],
        timestamp: Optional[float],
        transcript: List[Dict[str, Any]],
        slides: List[Dict[str, Any]],
        embeddings: Dict[str, Any],
        analytics: Dict[str, Any],
    ) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        difficult = analytics.get("difficult_segments", [])

        if not concept and timestamp is not None:
            for seg in transcript:
                if seg.get("start", 0) <= timestamp <= seg.get("end", 9999):
                    words = [w for w in re.findall(r"\b[a-zA-Z]{3,}\b", seg["text"].lower())]
                    concept = words[0] if words else None
                    break

        if not concept and difficult:
            concept = difficult[0].get("primary_concept", "")

        if not concept:
            return {"recommendations": [], "resources": []}

        query_emb = None
        if self.ee and embeddings.get("slides"):
            query_emb = self.ee.encode_single(concept)

        for idx, slide in enumerate(slides):
            score = 0.5
            if query_emb is not None and embeddings.get("slides"):
                s_embs = np.array(embeddings["slides"])
                if idx < len(s_embs):
                    score = self.ee.cosine_similarity(query_emb, s_embs[idx])
            if score > 0.3:
                results.append(
                    {
                        "type": "slide",
                        "id": slide["id"],
                        "title": slide["title"],
                        "score": round(float(score), 3),
                        "reason": f"Related to '{concept}'",
                    }
                )

        for idx, seg in enumerate(transcript):
            score = 0.5
            if query_emb is not None and embeddings.get("transcript"):
                t_embs = np.array(embeddings["transcript"])
                if idx < len(t_embs):
                    score = self.ee.cosine_similarity(query_emb, t_embs[idx])
            if score > 0.4:
                results.append(
                    {
                        "type": "transcript",
                        "id": seg.get("id", idx),
                        "timestamp": seg["timestamp"],
                        "start": seg.get("start", 0),
                        "text": seg["text"][:100] + "...",
                        "score": round(float(score), 3),
                        "reason": f"Related to '{concept}'",
                    }
                )

        results.sort(key=lambda x: x["score"], reverse=True)

        snippet = join_segments(transcript[:6])[:300]
        topics = extract_topics(f"{concept}. {snippet}", fallback_keywords=True)
        primary = (
            topics[0].get("summary") or topics[0].get("name") or concept
            if topics
            else concept
        )
        resources = gather_resources(primary, limit=12)
        return {"recommendations": results[:8], "resources": resources}
