"""Domain-aware term normalization for transcript + OCR text.

Cleans up two recurring problems we see in multilingual technical lectures:

  1. Whisper romanises Devanagari technical terms phonetically — "follow set"
     becomes "फॉलो" or "phaalo" depending on the audio. We restore the canonical
     English term so downstream LLMs see "FOLLOW set" not "फॉलो सेट".
  2. OCR on slides hallucinates near-look-alikes — "R0" instead of "LR0",
     "S → epsilon" mis-read as "S to epislon", etc.

The normalizer is intentionally conservative: it only rewrites tokens that
appear in a curated lookup or that match a high-confidence regex. Everything
else passes through unchanged, so we never *introduce* new errors.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple


# ── Hindi/Devanagari + romanised → canonical English ──────────────────────
# Keep this list short and high-precision. False positives (rewriting an
# unrelated word) are worse than missed corrections.
_HINDI_LOOKUP: Dict[str, str] = {
    # Compiler / parsing
    "फॉलो": "FOLLOW",
    "फर्स्ट": "FIRST",
    "पार्सिंग": "parsing",
    "पाल सिंह": "parsing",  # whisper mis-hearing
    "पार्सर": "parser",
    "ग्रामर": "grammar",
    "व्याकरण": "grammar",
    "टोकन": "token",
    "लेक्सर": "lexer",
    "लेक्सिकल": "lexical",
    "सिंटेक्स": "syntax",
    "सेमेंटिक": "semantic",
    "रिडक्शन": "reduction",
    "शिफ्ट": "shift",
    "स्टेट": "state",
    "नॉन टर्मिनल": "non-terminal",
    "टर्मिनल": "terminal",
    "ऑग्मेंटेड": "augmented",
    "क्लोजर": "closure",
    "गो टू": "GOTO",
    "गोटो": "GOTO",
    "ऑटोमेटा": "automata",
    "एप्सिलॉन": "epsilon",
    "एप्सिलोन": "epsilon",
    # General CS
    "अल्गोरिथम": "algorithm",
    "एल्गोरिथम": "algorithm",
    "डेटा स्ट्रक्चर": "data structure",
}


# ── Acronym / shorthand normalization ─────────────────────────────────────
# (pattern, replacement, optional context keyword that must appear nearby)
_ACRONYM_RULES: List[Tuple[re.Pattern, str, str]] = [
    # "R0" / "LR 0" / "LR-0" → "LR0" (only near parser/grammar context)
    (re.compile(r"\bR\s*0\b", re.IGNORECASE), "LR0", "parser|parsing|grammar|item"),
    (re.compile(r"\bL\s*R\s*[-–]?\s*0\b", re.IGNORECASE), "LR0", ""),
    (re.compile(r"\bL\s*R\s*[-–]?\s*1\b", re.IGNORECASE), "LR1", ""),
    # `\b` won't match after a literal `)`, so use a lookahead on non-word
    # to consume an optional closing paren without double-stamping it.
    (re.compile(r"\bS\s*L\s*R\s*[-–(]?\s*1\s*\)?(?=\W|$)", re.IGNORECASE), "SLR(1)", ""),
    (re.compile(r"\bL\s*A\s*L\s*R\s*[-–(]?\s*1\s*\)?(?=\W|$)", re.IGNORECASE), "LALR(1)", ""),
    # Common CS terms
    (re.compile(r"\bC\s*F\s*G\b", re.IGNORECASE), "CFG", ""),
    (re.compile(r"\bD\s*F\s*A\b", re.IGNORECASE), "DFA", ""),
    (re.compile(r"\bN\s*F\s*A\b", re.IGNORECASE), "NFA", ""),
    # FOLLOW / FIRST sets — keep uppercased so they read as sets, not verbs
    (re.compile(r"\bfollow\s+set\b", re.IGNORECASE), "FOLLOW set", ""),
    (re.compile(r"\bfirst\s+set\b", re.IGNORECASE), "FIRST set", ""),
    # epsilon variants
    (re.compile(r"\b(epislon|epsilom|epislom|epsiln)\b", re.IGNORECASE), "epsilon", ""),
]


# ── OCR-specific cleanup ──────────────────────────────────────────────────
# Run only on OCR text — these patterns are common scanner artifacts.
_OCR_CLEAN: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"[|│]\s*"), " "),            # vertical bars from table edges
    (re.compile(r"[•●◦]"), "* "),             # bullet glyphs → ascii
    (re.compile(r"→|⟶|⇒"), " -> "),           # arrows
    (re.compile(r"[“”]"), '"'),     # smart quotes
    (re.compile(r"[‘’]"), "'"),
    (re.compile(r"\s{2,}"), " "),
    (re.compile(r"(?<=\w)-\s*\n\s*(?=\w)"), ""),  # de-hyphenate line breaks
]


def _replace_hindi(text: str) -> str:
    out = text
    for k, v in _HINDI_LOOKUP.items():
        if k in out:
            out = out.replace(k, v)
    return out


def _apply_acronyms(text: str) -> str:
    lower = text.lower()
    out = text
    for pat, repl, ctx in _ACRONYM_RULES:
        if ctx:
            if not re.search(ctx, lower):
                continue
        out = pat.sub(repl, out)
    return out


def normalize_text(text: str, *, source: str = "transcript") -> str:
    """Return ``text`` with domain-specific cleanups applied.

    ``source`` selects which rule packs to run:
      * ``"transcript"`` — Hindi→English + acronyms
      * ``"ocr"``        — OCR cleanup + acronyms (Hindi rare in slide OCR)
      * ``"any"``        — run everything
    """
    if not text:
        return ""

    out = text

    if source in ("ocr", "any"):
        for pat, repl in _OCR_CLEAN:
            out = pat.sub(repl, out)

    if source in ("transcript", "any"):
        out = _replace_hindi(out)

    out = _apply_acronyms(out)
    return out.strip()


def normalize_segments(segments: Iterable[dict], *, key: str = "text") -> List[dict]:
    """Return new segment dicts with ``key`` replaced by its normalized form."""
    out: List[dict] = []
    for seg in segments:
        new = dict(seg)
        new[key] = normalize_text(seg.get(key) or "", source="transcript")
        out.append(new)
    return out


def extract_canonical_terms(text: str) -> List[str]:
    """Pull out canonical domain terms (LR0, FOLLOW, FIRST, SLR(1) …).

    Used by validation to confirm that generated slides mention at least one
    canonical term from the source chunk — a cheap topic-grounding signal.
    """
    if not text:
        return []
    pats = [
        r"\bLR[01]\b",
        r"\bSLR\(1\)\b",
        r"\bLALR\(1\)\b",
        r"\bCFG\b",
        r"\bDFA\b",
        r"\bNFA\b",
        r"\bFOLLOW\b",
        r"\bFIRST\b",
        r"\bGOTO\b",
        r"\bclosure\b",
        r"\bepsilon\b",
        r"\baugmented\b",
        r"\bshift[- ]?reduce\b",
        r"\bnon[- ]?terminal\b",
        r"\bterminal\b",
        r"\bparser\b",
        r"\bparsing\b",
        r"\bgrammar\b",
        r"\btoken\b",
        r"\blexer\b",
        r"\blexical\b",
        r"\bsyntax\b",
        r"\bsemantic\b",
    ]
    found: List[str] = []
    seen: set[str] = set()
    for p in pats:
        for m in re.findall(p, text, flags=re.IGNORECASE):
            key = m.upper() if len(m) <= 6 else m.lower()
            if key not in seen:
                seen.add(key)
                found.append(m)
    return found
