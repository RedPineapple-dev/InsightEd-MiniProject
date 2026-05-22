"""Topic segmentation — split a transcript into semantic chunks.

Each chunk is one "scene" in the lecture: a contiguous run of transcript
segments that discuss the same topic, bounded by:

  * pauses in the speech (gap between segment.end and next segment.start)
  * embedding similarity drops between adjacent sliding windows
  * (optional) frame OCR transitions that change slide content

Output shape per chunk:

    {
        "chunk_id": int,
        "start": float,          # seconds
        "end": float,
        "timestamp": "MM:SS",
        "segment_ids": [int],
        "text": str,             # normalized transcript text
        "ocr_text": str,         # joined OCR from frames inside the chunk
        "ocr_terms": [str],      # canonical domain terms found in OCR
        "key_terms": [str],      # canonical terms from transcript
        "title_hint": str,       # first sentence — cheap fallback title
        "confidence": float,     # 0..1 — boundary confidence
    }

The module never calls the LLM directly — it only uses embeddings + rule
heuristics, so it works even when Gemini is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from services.domain_normalization import (
    extract_canonical_terms,
    normalize_text,
)
from services.text_processing import normalize_whitespace


# ── Tunables (all overridable via segment() kwargs) ───────────────────────
DEFAULT_PAUSE_SEC = 2.5
DEFAULT_MIN_CHUNK_SEC = 25.0
DEFAULT_MAX_CHUNK_SEC = 240.0
DEFAULT_SIM_DROP_THRESHOLD = 0.30   # cosine-sim drop that signals topic shift
DEFAULT_WINDOW = 3                  # segments per sliding window


def _seg_text(seg: Dict[str, Any]) -> str:
    return normalize_text(seg.get("text") or "", source="transcript")


def _window_text(segments: List[Dict[str, Any]], i: int, window: int) -> str:
    lo = max(0, i - window + 1)
    return " ".join(_seg_text(s) for s in segments[lo : i + 1])


def _safe_encode(encoder, texts: List[str]) -> np.ndarray:
    try:
        return np.asarray(encoder(texts), dtype=np.float32)
    except Exception:
        return np.zeros((len(texts), 1), dtype=np.float32)


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _detect_boundaries(
    segments: List[Dict[str, Any]],
    *,
    pause_sec: float,
    window: int,
    sim_drop: float,
    encode_fn,
) -> List[int]:
    """Return indices i where a *new* topic chunk starts (always includes 0)."""
    n = len(segments)
    if n <= 1:
        return [0] if n == 1 else []

    # 1) Pause-based boundaries are cheap and very reliable.
    pause_boundaries: List[int] = [0]
    for i in range(1, n):
        prev_end = float(segments[i - 1].get("end") or 0.0)
        cur_start = float(segments[i].get("start") or 0.0)
        if cur_start - prev_end >= pause_sec:
            pause_boundaries.append(i)

    # 2) Embedding-based topic-shift detection over sliding windows.
    sem_boundaries: List[int] = []
    if encode_fn is not None and n > window * 2:
        win_texts = [_window_text(segments, i, window) for i in range(n)]
        embs = _safe_encode(encode_fn, win_texts)
        if embs.size and embs.shape[0] == n:
            for i in range(window, n - window):
                left = embs[i - 1]
                right = embs[i]
                sim = _cos(left, right)
                # Compare with the local rolling average to avoid global noise.
                k = min(window, i, n - i - 1)
                ref = float(
                    np.mean(
                        [
                            _cos(embs[i - 1 - d], embs[i - d])
                            for d in range(1, k + 1)
                        ]
                    )
                ) if k else sim
                if ref - sim >= sim_drop:
                    sem_boundaries.append(i)

    boundaries = sorted(set(pause_boundaries + sem_boundaries))
    return boundaries


def _merge_short_chunks(
    boundaries: List[int],
    segments: List[Dict[str, Any]],
    *,
    min_chunk_sec: float,
    max_chunk_sec: float,
) -> List[int]:
    """Merge chunks that are shorter than ``min_chunk_sec`` into the next one,
    and split chunks longer than ``max_chunk_sec`` at the largest internal gap.
    """
    if not boundaries:
        return boundaries

    def chunk_span(start_idx: int, end_idx: int) -> float:
        if start_idx >= len(segments) or end_idx <= start_idx:
            return 0.0
        s = float(segments[start_idx].get("start") or 0.0)
        e = float(segments[end_idx - 1].get("end") or s)
        return max(0.0, e - s)

    bounds = list(boundaries)
    bounds.append(len(segments))  # sentinel for "end"

    # First pass: drop boundaries that produce too-short head chunks (except 0).
    out: List[int] = [bounds[0]]
    for k in range(1, len(bounds) - 1):
        span = chunk_span(bounds[k - 1], bounds[k])
        if span < min_chunk_sec and k != len(bounds) - 2:
            continue  # merge with following
        out.append(bounds[k])

    # Second pass: split chunks that are too long. We pick the largest pause
    # inside the chunk and insert a boundary there.
    refined: List[int] = []
    for k in range(len(out)):
        refined.append(out[k])
        lo = out[k]
        hi = out[k + 1] if k + 1 < len(out) else len(segments)
        if chunk_span(lo, hi) <= max_chunk_sec:
            continue
        # find largest gap inside
        best_gap = 0.0
        best_idx = -1
        for i in range(lo + 1, hi):
            prev_end = float(segments[i - 1].get("end") or 0.0)
            cur_start = float(segments[i].get("start") or 0.0)
            gap = cur_start - prev_end
            if gap > best_gap:
                best_gap = gap
                best_idx = i
        if best_idx > 0:
            refined.append(best_idx)
    refined = sorted(set(refined))
    return refined


def _format_ts(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def _first_sentence(text: str, max_chars: int = 80) -> str:
    import re

    t = normalize_whitespace(text)
    if not t:
        return ""
    m = re.search(r"[.!?]", t)
    head = t[: m.start() + 1] if m else t[:max_chars]
    return head.strip()[:max_chars]


def _attach_ocr(
    chunk: Dict[str, Any],
    ocr_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Pick OCR rows whose timestamp falls inside the chunk."""
    if not ocr_records:
        chunk["ocr_text"] = ""
        chunk["ocr_terms"] = []
        chunk["ocr_confidence"] = 0.0
        return chunk
    lo, hi = chunk["start"], chunk["end"]
    inside = [r for r in ocr_records if lo - 0.5 <= float(r.get("start") or 0.0) <= hi + 0.5]
    if not inside:
        chunk["ocr_text"] = ""
        chunk["ocr_terms"] = []
        chunk["ocr_confidence"] = 0.0
        return chunk
    joined = normalize_whitespace(" ".join(r.get("text") or "" for r in inside))
    chunk["ocr_text"] = joined
    chunk["ocr_terms"] = extract_canonical_terms(joined)
    chunk["ocr_confidence"] = round(
        sum(float(r.get("confidence") or 0.0) for r in inside) / max(1, len(inside)), 3
    )
    return chunk


def segment_transcript(
    transcript: List[Dict[str, Any]],
    *,
    encode_fn=None,
    ocr_records: Optional[List[Dict[str, Any]]] = None,
    pause_sec: float = DEFAULT_PAUSE_SEC,
    window: int = DEFAULT_WINDOW,
    sim_drop: float = DEFAULT_SIM_DROP_THRESHOLD,
    min_chunk_sec: float = DEFAULT_MIN_CHUNK_SEC,
    max_chunk_sec: float = DEFAULT_MAX_CHUNK_SEC,
) -> List[Dict[str, Any]]:
    """Segment ``transcript`` into topic chunks.

    Parameters
    ----------
    encode_fn:
        Optional callable that turns ``list[str]`` into a 2-D numpy array of
        embeddings. If omitted, only pause-based boundaries are used.
    ocr_records:
        Optional list of OCR records from ``frame_ocr.extract_frame_ocr``.
        When present, the canonical terms in the OCR text are attached to
        each chunk and used by downstream validation.
    """
    if not transcript:
        return []

    n = len(transcript)
    boundaries = _detect_boundaries(
        transcript,
        pause_sec=pause_sec,
        window=window,
        sim_drop=sim_drop,
        encode_fn=encode_fn,
    )
    if not boundaries:
        boundaries = [0]
    boundaries = _merge_short_chunks(
        boundaries,
        transcript,
        min_chunk_sec=min_chunk_sec,
        max_chunk_sec=max_chunk_sec,
    )
    bounds = list(boundaries) + [n]

    chunks: List[Dict[str, Any]] = []
    for k in range(len(bounds) - 1):
        lo, hi = bounds[k], bounds[k + 1]
        if hi <= lo:
            continue
        seg_slice = transcript[lo:hi]
        text = normalize_whitespace(" ".join(_seg_text(s) for s in seg_slice))
        if not text:
            continue
        start = float(seg_slice[0].get("start") or 0.0)
        end = float(seg_slice[-1].get("end") or start)
        chunks.append(
            {
                "chunk_id": k,
                "start": round(start, 2),
                "end": round(end, 2),
                "timestamp": _format_ts(start),
                "segment_ids": [s.get("id", lo + i) for i, s in enumerate(seg_slice)],
                "text": text,
                "title_hint": _first_sentence(text),
                "key_terms": extract_canonical_terms(text),
                "confidence": 0.6 if k > 0 else 0.9,
            }
        )

    # Attach OCR overlap data
    if ocr_records:
        chunks = [_attach_ocr(c, ocr_records) for c in chunks]
    else:
        for c in chunks:
            c["ocr_text"] = ""
            c["ocr_terms"] = []
            c["ocr_confidence"] = 0.0

    return chunks


def fuse_chunk_context(chunk: Dict[str, Any], *, max_chars: int = 4500) -> str:
    """Return a single LLM-friendly context string for ``chunk``.

    Format:
        Transcript:
        \"\"\"...\"\"\"

        Slide OCR (terms: ...):
        \"\"\"...\"\"\"
    """
    parts: List[str] = []
    transcript_text = (chunk.get("text") or "").strip()
    ocr_text = (chunk.get("ocr_text") or "").strip()
    if transcript_text:
        # Reserve some budget for OCR
        budget = max_chars - (len(ocr_text) + 200) if ocr_text else max_chars
        parts.append(f'Transcript:\n"""{transcript_text[:max(500, budget)]}"""')
    if ocr_text:
        terms = ", ".join((chunk.get("ocr_terms") or [])[:10])
        header = f"Slide OCR (terms: {terms})" if terms else "Slide OCR"
        parts.append(f'{header}:\n"""{ocr_text[:1500]}"""')
    return "\n\n".join(parts) or transcript_text[:max_chars]


def overall_topic_signature(chunks: List[Dict[str, Any]], *, top_k: int = 12) -> List[str]:
    """Aggregate canonical terms across all chunks; useful for global validation."""
    counts: Dict[str, int] = {}
    for c in chunks:
        for t in (c.get("key_terms") or []) + (c.get("ocr_terms") or []):
            key = t.upper() if len(t) <= 6 else t.lower()
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda p: p[1], reverse=True)
    return [k for k, _ in ranked[:top_k]]
