"""Text utilities: chunking, normalisation, transcript helpers."""

from __future__ import annotations

import re
from typing import Iterable, List


def normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def chunk_text(text: str, *, max_chars: int = 2200, overlap: int = 220) -> List[str]:
    """Split a long string into overlapping chunks at sentence-ish boundaries."""
    text = normalize_whitespace(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        # Backtrack to nearest sentence end if we're not at the document end
        if end < len(text):
            for sep in (". ", "? ", "! ", "\n"):
                idx = text.rfind(sep, start + max_chars // 2, end)
                if idx != -1:
                    end = idx + len(sep)
                    break
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def join_segments(segments: Iterable[dict], *, key: str = "text") -> str:
    return normalize_whitespace(" ".join((s.get(key) or "") for s in segments))


def top_segments(segments: List[dict], scored: List[float], *, k: int = 3) -> List[dict]:
    """Pick top-k segments given a parallel list of scores."""
    if not segments or not scored:
        return segments[:k]
    pairs = list(zip(segments, scored))
    pairs.sort(key=lambda p: p[1], reverse=True)
    return [s for s, _ in pairs[:k]]
