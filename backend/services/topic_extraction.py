"""Topic + keyword extraction.

Two complementary techniques:

1. **YAKE** — lightweight statistical keyphrase extractor. Fast, no model,
   great for surfacing "frequently used terms" inside a single transcript.
2. **LLM** — when GEMINI_API_KEY is available we ask Gemini to synthesise
   a small set of high-level topics from the transcript. Used to drive
   recommendations (Part 6).

Both are best-effort; missing dependencies fall back to a simple frequency
counter so callers always get *something*.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, List, Optional

from pydantic import BaseModel, Field

from .llm import LLMError, get_llm
from .text_processing import normalize_whitespace


# A fairly aggressive English stop list — fine for educational transcripts.
_STOP = set(
    """
    a an the and or but if while of at by for with about as is are was were be been being
    have has had do does did doing this that these those i you he she it we they them us
    my your his her its our their me your me to in on into over under again further then
    once here there when where why how all any both each few more most other some such no
    nor not only own same so than too very s t can will just don should now also like one
    two three four five six seven eight nine ten go going get got see saw seen come came
    take taken make made know known think thought said say says go gone gone really kind
    sort thing things stuff people way ways something someone anyone everything everyone
    okay ok yeah yes no nope hmm uh um er so well right
    """.split()
)


class Topic(BaseModel):
    name: str = Field(description="Short topic name, 1-4 words")
    summary: str = Field(description="One-sentence summary suitable for search queries")


class TopicList(BaseModel):
    topics: List[Topic]


# ── Keyword extraction ────────────────────────────────────────────────────


def extract_keywords(text: str, *, max_n: int = 12) -> List[dict]:
    """Returns a list of {term, score, count} sorted by score desc."""
    text = normalize_whitespace(text)
    if not text:
        return []

    # Try YAKE first; fall back to a frequency counter on import error.
    try:
        import yake  # type: ignore

        kw_extractor = yake.KeywordExtractor(
            lan="en",
            n=3,  # up to 3-word phrases
            top=max_n * 2,
            dedupLim=0.7,
            windowsSize=2,
        )
        ranked = kw_extractor.extract_keywords(text)
        # YAKE: lower score = better. Normalise to a 0..1 "relevance".
        if not ranked:
            return _frequency_keywords(text, max_n=max_n)
        max_score = max(s for _, s in ranked) or 1.0
        results = []
        counts = Counter(re.findall(r"[A-Za-z][A-Za-z0-9'-]+", text.lower()))
        for term, score in ranked[:max_n]:
            if term.lower() in _STOP:
                continue
            results.append(
                {
                    "term": term,
                    "score": round(1.0 - (score / max_score), 4),
                    "count": counts.get(term.split()[0].lower(), 1),
                }
            )
        return results
    except ImportError:
        return _frequency_keywords(text, max_n=max_n)


def _frequency_keywords(text: str, *, max_n: int) -> List[dict]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text.lower())
    tokens = [t for t in tokens if t not in _STOP]
    counts = Counter(tokens)
    most = counts.most_common(max_n)
    if not most:
        return []
    top_count = most[0][1] or 1
    return [
        {"term": term, "score": round(c / top_count, 4), "count": c} for term, c in most
    ]


# ── LLM topic synthesis ────────────────────────────────────────────────────

_TOPIC_PROMPT = """\
You are an educational content analyst. Given a transcript excerpt, return
the 3-6 most significant *topics*. Topics should be self-contained search
queries — concrete enough to find articles, papers and tutorials about.

Avoid filler topics ('introduction', 'conclusion', 'overview').

Return strictly valid JSON of the form:
{{"topics": [{{"name": "...", "summary": "..."}}]}}

Transcript:
\"\"\"{transcript}\"\"\"
"""


def extract_topics(transcript_text: str, *, fallback_keywords: bool = True) -> List[dict]:
    """LLM-driven topic synthesis. Falls back to keyword extraction on failure."""
    text = normalize_whitespace(transcript_text)
    if not text:
        return []

    llm = get_llm()
    if not llm.is_available():
        if fallback_keywords:
            return [
                {"name": k["term"], "summary": k["term"]}
                for k in extract_keywords(text, max_n=6)
            ]
        return []

    excerpt = text[:6000]  # cap context length
    prompt = _TOPIC_PROMPT.format(transcript=excerpt)
    try:
        result = llm.generate_json(
            prompt,
            TopicList,
            temperature=0.2,
            cache_namespace="topics",
        )
    except LLMError as exc:
        print(f"[topics] LLM failed: {exc}")
        result = None

    if result and result.topics:
        return [t.model_dump() for t in result.topics]
    if fallback_keywords:
        return [
            {"name": k["term"], "summary": k["term"]}
            for k in extract_keywords(text, max_n=6)
        ]
    return []
