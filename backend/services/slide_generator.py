"""Auto-generate slides (PDF + PPTX) from a lecture's structured notes.

The pipeline is now multi-stage instead of "raw transcript -> slides":

    transcript ─┐
                ├─► topic_segmentation ─► structured_notes ─► outline
    frame OCR ──┘                                                │
                                                                 ▼
                                                          validator
                                                                 │
                                                                 ▼
                                                       PDF / PPTX render

Each stage is testable in isolation. The LLM only sees one topic chunk at
a time, which avoids the context-drift / hallucinated-topic problem that
the previous "send 9 000 chars in one prompt" approach produced.

Public entry points:

    * ``generate_documents(...)`` — high-level: builds chunks (if needed),
       generates notes, validates, then renders both formats.
    * ``render_pdf(outline, ...)`` / ``render_pptx(outline, ...)`` — pure
      renderers, unchanged behaviour for backwards compatibility.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from config import settings
from services.domain_normalization import extract_canonical_terms, normalize_text
from services.llm import LLMError, get_llm
from services.slide_validator import (
    slides_share_dominant_topic,
    validate_outline,
)
from services.structured_notes import (
    generate_notes,
    select_publishable_notes,
)
from services.text_processing import join_segments, normalize_whitespace
from services.topic_segmentation import (
    overall_topic_signature,
    segment_transcript,
)


# ── Outline schema ────────────────────────────────────────────────────────


class SlideSpec(BaseModel):
    title: str = Field(description="Short slide title")
    bullets: List[str] = Field(default_factory=list, description="2-5 concise bullets")
    timestamp_seconds: Optional[float] = None
    section: Optional[str] = None
    chunk_id: Optional[int] = None


class OutlineResult(BaseModel):
    title: str
    subtitle: Optional[str] = None
    slides: List[SlideSpec]


@dataclass
class SlideOutline:
    title: str
    subtitle: Optional[str]
    slides: List[dict] = field(default_factory=list)
    validation: Dict[str, Any] = field(default_factory=dict)
    canonical_terms: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "slides": self.slides,
            "validation": self.validation,
            "canonical_terms": self.canonical_terms,
        }


# ── Outline-from-notes LLM prompt ─────────────────────────────────────────


_OUTLINE_FROM_NOTES_PROMPT = """\
You are turning structured study notes into a slide outline. Each note below
represents one topic chunk of a lecture and has already been validated as
grounded in the source video.

Produce 6 – 12 slides total. Rules — never break these:

  * Every slide must come from EXACTLY ONE input note. Set "chunk_id" to that
    note's chunk_id so the slide can be traced back.
  * The slide title must reuse the note's topic (paraphrase OK, <=8 words).
  * 2–5 bullet points per slide, each <=18 words. Use the note's
    important_points / definitions / examples / formulas as raw material.
  * Preserve canonical technical terms verbatim: {canonical_hint}.
  * Do NOT invent new concepts. If a note has only one short point, emit a
    slide with one bullet rather than padding with filler.
  * Skip notes flagged "off_topic" or with empty content.
  * Use timestamp_seconds = the note's start time.
  * Assign section labels: "Intro" for the first slide, "Wrap-up" for the
    last, "Examples" for slides whose primary bullets are examples,
    "Core" otherwise.

Return STRICT JSON ONLY of the shape:
{{"title": "<lecture title>", "subtitle": "<one-line summary>",
  "slides": [
    {{"title": "...", "bullets": ["..."], "timestamp_seconds": <num>,
      "section": "Intro|Core|Examples|Wrap-up", "chunk_id": <int>}}
  ]}}

NOTES (JSON array):
{notes_json}
"""


def _llm_outline_from_notes(
    notes: List[Dict[str, Any]],
    *,
    fallback_title: str,
    canonical_terms: List[str],
) -> Optional[OutlineResult]:
    llm = get_llm()
    if not llm.is_available():
        return None
    import json as _json

    # Trim notes to what the prompt actually needs (don't ship internal fields).
    trimmed = []
    for n in notes:
        trimmed.append(
            {
                "chunk_id": n.get("chunk_id"),
                "start": n.get("start"),
                "topic": n.get("topic"),
                "core_concepts": (n.get("core_concepts") or [])[:6],
                "important_points": (n.get("important_points") or [])[:5],
                "definitions": (n.get("definitions") or [])[:3],
                "examples": (n.get("examples") or [])[:3],
                "formulas": (n.get("formulas") or [])[:3],
                "exam_points": (n.get("exam_points") or [])[:3],
            }
        )
    canonical_hint = ", ".join(canonical_terms[:10]) or "preserve all acronyms as-is"
    prompt = _OUTLINE_FROM_NOTES_PROMPT.format(
        canonical_hint=canonical_hint,
        notes_json=_json.dumps(trimmed, ensure_ascii=False),
    )
    try:
        return llm.generate_json(
            prompt,
            OutlineResult,
            temperature=0.2,
            max_retries=2,
            cache_namespace="slide_outline_v2",
        )
    except LLMError as exc:
        print(f"[slides] LLM outline failed: {exc}")
        return None


# ── Deterministic outline (LLM-free) ─────────────────────────────────────


def _outline_from_notes_heuristic(
    notes: List[Dict[str, Any]],
    *,
    fallback_title: str,
) -> SlideOutline:
    slides: List[Dict[str, Any]] = []
    total = len(notes)
    for i, n in enumerate(notes):
        title = (n.get("topic") or n.get("title") or "").strip() or f"Section {i + 1}"
        bullets: List[str] = []
        for p in (n.get("important_points") or [])[:3]:
            bullets.append(p)
        for d in (n.get("definitions") or [])[:2]:
            if isinstance(d, dict) and d.get("term") and d.get("definition"):
                bullets.append(f"{d['term']}: {d['definition']}")
        for e in (n.get("examples") or [])[:1]:
            bullets.append(f"Example — {e}")
        for f in (n.get("formulas") or [])[:1]:
            bullets.append(f"Formula — {f}")
        bullets = [b[:140] for b in bullets if b][:5]
        if not bullets:
            bullets = [(n.get("topic") or "Discussed in this segment")[:140]]
        slides.append(
            {
                "title": title[:80],
                "bullets": bullets,
                "timestamp_seconds": float(n.get("start") or 0.0),
                "section": "Intro" if i == 0 else "Wrap-up" if i == total - 1 else "Core",
                "chunk_id": n.get("chunk_id"),
            }
        )

    # Pick a useful subtitle: the longest topic-line that has a verb.
    subtitle = ""
    for n in notes:
        topic = (n.get("topic") or "").strip()
        if 12 <= len(topic) <= 80:
            subtitle = topic
            break

    return SlideOutline(title=fallback_title, subtitle=subtitle, slides=slides)


# ── Top-level outline builder ────────────────────────────────────────────


def build_outline_from_notes(
    notes: List[Dict[str, Any]],
    *,
    fallback_title: str = "Lecture Notes",
    canonical_terms: Optional[List[str]] = None,
) -> SlideOutline:
    """Build *and validate* a slide outline from structured notes.

    Drops hallucinated / off-topic slides; merges duplicates. The returned
    outline always has a ``validation`` dict that the caller can surface.
    """
    notes = select_publishable_notes(notes)
    if not notes:
        return SlideOutline(title=fallback_title, subtitle=None, slides=[])

    canonical = canonical_terms or []
    if not canonical:
        seen: Dict[str, int] = {}
        for n in notes:
            for t in (n.get("core_concepts") or []):
                ct = extract_canonical_terms(t) or [t]
                for c in ct:
                    key = c.upper() if len(c) <= 6 else c.lower()
                    seen[key] = seen.get(key, 0) + 1
        canonical = [k for k, _ in sorted(seen.items(), key=lambda p: p[1], reverse=True)[:12]]

    llm_result = _llm_outline_from_notes(
        notes, fallback_title=fallback_title, canonical_terms=canonical
    )

    if llm_result and llm_result.slides:
        outline = SlideOutline(
            title=llm_result.title or fallback_title,
            subtitle=llm_result.subtitle,
            slides=[s.model_dump() for s in llm_result.slides],
            canonical_terms=canonical,
        )
    else:
        outline = _outline_from_notes_heuristic(notes, fallback_title=fallback_title)
        outline.canonical_terms = canonical

    # Validation pass
    kept, report = validate_outline(
        outline.slides, notes, canonical_terms=canonical, min_overlap=0.08
    )
    # If validation nuked everything, fall back to heuristic (better than empty)
    if not kept:
        outline = _outline_from_notes_heuristic(notes, fallback_title=fallback_title)
        outline.canonical_terms = canonical
        kept, report = validate_outline(
            outline.slides, notes, canonical_terms=canonical, min_overlap=0.0
        )

    outline.slides = kept
    outline.validation = {
        **report,
        "dominant_topic_consistent": slides_share_dominant_topic(kept, canonical, min_coverage=0.4),
        "canonical_terms": canonical,
    }
    return outline


def generate_outline(
    transcript_segments: List[Dict[str, Any]],
    *,
    fallback_title: str = "Lecture Notes",
    encode_fn=None,
    ocr_records: Optional[List[Dict[str, Any]]] = None,
    notes: Optional[List[Dict[str, Any]]] = None,
    allow_llm: bool = True,
) -> SlideOutline:
    """Backwards-compatible entry point.

    When ``notes`` is supplied (the pipeline path), it's used directly.
    Otherwise we run the full transcript → chunks → notes → outline pipeline.
    """
    if not notes:
        chunks = segment_transcript(
            transcript_segments,
            encode_fn=encode_fn,
            ocr_records=ocr_records,
        )
        if not chunks:
            return SlideOutline(title=fallback_title, subtitle=None, slides=[])
        notes = generate_notes(chunks, allow_llm=allow_llm)
        canonical = overall_topic_signature(chunks)
    else:
        canonical = []
        for n in notes:
            for t in (n.get("core_concepts") or []):
                for c in extract_canonical_terms(t) or [t]:
                    canonical.append(c)
        canonical = list(dict.fromkeys(canonical))[:12]

    return build_outline_from_notes(
        notes, fallback_title=fallback_title, canonical_terms=canonical
    )


# ── PDF rendering (reportlab) ─────────────────────────────────────────────


def _format_ts(t: Optional[float]) -> str:
    if t is None:
        return ""
    s = max(0, int(t))
    return f"{s // 60:02d}:{s % 60:02d}"


def render_pdf(outline: SlideOutline, *, output_path: Path) -> Path:
    from reportlab.lib import colors  # type: ignore
    from reportlab.lib.pagesizes import LETTER  # type: ignore
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # type: ignore
    from reportlab.lib.units import inch  # type: ignore
    from reportlab.platypus import (  # type: ignore
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        PageBreak,
        ListFlowable,
        ListItem,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        textColor=colors.HexColor("#10b981"),
        spaceAfter=8,
        fontSize=28,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        textColor=colors.HexColor("#475569"),
        fontSize=14,
        spaceAfter=24,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=4,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Italic"],
        textColor=colors.HexColor("#10b981"),
        fontSize=10,
        spaceAfter=4,
    )
    bullet_style = ParagraphStyle(
        "Bullet",
        parent=styles["Normal"],
        leftIndent=12,
        bulletIndent=0,
        fontSize=11,
        leading=16,
    )

    story = [Paragraph(_xml_safe(outline.title), title_style)]
    if outline.subtitle:
        story.append(Paragraph(_xml_safe(outline.subtitle), subtitle_style))
    else:
        story.append(Spacer(1, 12))

    for slide in outline.slides:
        head = slide.get("title") or "Slide"
        ts = _format_ts(slide.get("timestamp_seconds"))
        section = slide.get("section") or ""
        story.append(Paragraph(f"<b>{_xml_safe(head)}</b>", h2))
        meta_bits = [b for b in [section, ts] if b]
        if meta_bits:
            story.append(Paragraph(_xml_safe(" · ".join(meta_bits)), section_style))
        bullets = [Paragraph(_xml_safe(b), bullet_style) for b in (slide.get("bullets") or [])]
        if bullets:
            story.append(ListFlowable([ListItem(b) for b in bullets], bulletType="bullet", leftIndent=14))
        story.append(Spacer(1, 12))

    doc.build(story)
    return output_path


def _xml_safe(text: str) -> str:
    """ReportLab parses Paragraph contents as XML — escape stray markup."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ── PPTX rendering (python-pptx) ──────────────────────────────────────────


def render_pptx(outline: SlideOutline, *, output_path: Path) -> Path:
    from pptx import Presentation  # type: ignore
    from pptx.dml.color import RGBColor  # type: ignore
    from pptx.util import Inches, Pt  # type: ignore

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    brand = RGBColor(0x10, 0xB9, 0x81)
    accent = RGBColor(0xF5, 0x9E, 0x0B)
    ink = RGBColor(0x0F, 0x17, 0x2A)
    muted = RGBColor(0x47, 0x55, 0x69)

    title_layout = prs.slide_layouts[6]  # blank
    s = prs.slides.add_slide(title_layout)
    title_box = s.shapes.add_textbox(Inches(0.8), Inches(2.4), Inches(11.5), Inches(2))
    tf = title_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = outline.title
    p.runs[0].font.size = Pt(48)
    p.runs[0].font.bold = True
    p.runs[0].font.color.rgb = brand

    if outline.subtitle:
        sub_box = s.shapes.add_textbox(Inches(0.8), Inches(4.4), Inches(11.5), Inches(1.4))
        sp = sub_box.text_frame.paragraphs[0]
        sp.text = outline.subtitle
        sp.runs[0].font.size = Pt(20)
        sp.runs[0].font.color.rgb = muted

    for slide in outline.slides:
        ss = prs.slides.add_slide(title_layout)
        section = slide.get("section")
        ts = _format_ts(slide.get("timestamp_seconds"))
        meta_box = ss.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.5), Inches(0.5))
        meta = meta_box.text_frame.paragraphs[0]
        meta.text = " · ".join([b for b in [section or "", ts] if b])
        if meta.runs:
            meta.runs[0].font.size = Pt(14)
            meta.runs[0].font.color.rgb = accent

        ti_box = ss.shapes.add_textbox(Inches(0.8), Inches(1.0), Inches(11.5), Inches(1.2))
        ti = ti_box.text_frame.paragraphs[0]
        ti.text = slide.get("title") or "Slide"
        ti.runs[0].font.size = Pt(36)
        ti.runs[0].font.bold = True
        ti.runs[0].font.color.rgb = ink

        body_box = ss.shapes.add_textbox(Inches(0.8), Inches(2.4), Inches(11.5), Inches(4.5))
        body_tf = body_box.text_frame
        body_tf.word_wrap = True
        bullets = slide.get("bullets") or []
        for i, b in enumerate(bullets):
            para = body_tf.paragraphs[0] if i == 0 else body_tf.add_paragraph()
            para.text = f"•  {b}"
            for run in para.runs:
                run.font.size = Pt(20)
                run.font.color.rgb = ink
            para.space_after = Pt(8)

    prs.save(str(output_path))
    return output_path


# ── Public API ────────────────────────────────────────────────────────────


def generate_documents(
    transcript_segments: List[Dict[str, Any]],
    *,
    title: str,
    formats: List[str],
    output_dir: Optional[Path] = None,
    encode_fn=None,
    ocr_records: Optional[List[Dict[str, Any]]] = None,
    notes: Optional[List[Dict[str, Any]]] = None,
    chunks: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """Generate the requested formats.

    The pipeline orchestrator should pass ``chunks`` *and* ``notes`` —
    they're produced earlier in the pipeline and re-used here so we don't
    re-run topic segmentation or hit the LLM twice.

    Callers that only have a transcript (e.g. the legacy /documents/generate
    route) can still call this with just ``transcript_segments``; we'll
    build chunks + notes inline.
    """
    if output_dir is None:
        output_dir = settings.generated_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if notes is None:
        if chunks is None:
            chunks = segment_transcript(
                transcript_segments,
                encode_fn=encode_fn,
                ocr_records=ocr_records,
            )
        notes = generate_notes(chunks or [])

    canonical = overall_topic_signature(chunks) if chunks else []
    outline = build_outline_from_notes(
        notes, fallback_title=title, canonical_terms=canonical
    )

    base = f"insighted-{uuid.uuid4().hex[:10]}"
    written: dict = {
        "outline": outline.to_dict(),
        "notes": notes,
        "chunks": chunks or [],
        "files": {},
    }
    for fmt in formats:
        fmt = (fmt or "").lower().strip()
        if fmt == "pdf":
            path = output_dir / f"{base}.pdf"
            try:
                render_pdf(outline, output_path=path)
                written["files"]["pdf"] = path
            except Exception as exc:
                print(f"[slides] PDF render failed: {exc}")
        elif fmt == "pptx":
            path = output_dir / f"{base}.pptx"
            try:
                render_pptx(outline, output_path=path)
                written["files"]["pptx"] = path
            except Exception as exc:
                print(f"[slides] PPTX render failed: {exc}")
        else:
            raise ValueError(f"Unsupported format: {fmt}")
    return written
