"""Auto-generate slides (PDF + PPTX) from a lecture transcript (Part 5).

Pipeline:
  1. Outline   — LLM produces a structured slide outline from the transcript.
  2. Render    — PDF (reportlab) and PPTX (python-pptx) both built from
                 the same outline so they stay consistent.
  3. Persist   — files are written to backend/generated/ and served via
                 FastAPI's `/generated` static mount.

If the LLM is unavailable, a deterministic outline is built by chunking the
transcript and using the first sentence of each chunk as a title.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from config import settings
from services.llm import LLMError, get_llm
from services.text_processing import chunk_text, join_segments, normalize_whitespace


# ── Outline schema ────────────────────────────────────────────────────────


class SlideSpec(BaseModel):
    title: str = Field(description="Short slide title")
    bullets: List[str] = Field(default_factory=list, description="2-5 concise bullets")
    timestamp_seconds: Optional[float] = None
    section: Optional[str] = None


class OutlineResult(BaseModel):
    title: str
    subtitle: Optional[str] = None
    slides: List[SlideSpec]


@dataclass
class SlideOutline:
    title: str
    subtitle: Optional[str]
    slides: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"title": self.title, "subtitle": self.subtitle, "slides": self.slides}


# ── LLM outline generation ────────────────────────────────────────────────


_OUTLINE_PROMPT = """\
You are a lecture editor. Convert the transcript into a slide outline that a
student could review *without* watching the video. Aim for 6-12 content slides.

Each slide must have:
  * a short, specific title (max 8 words)
  * 2-5 concise bullet points (each <= 16 words, sentence fragments OK)
  * an approximate timestamp_seconds where the slide's content begins
  * a section label (one of: "Intro", "Core", "Examples", "Wrap-up") — keep
    consistent across slides

Avoid filler ("welcome", "thanks for watching"). Don't restate the transcript
verbatim — paraphrase. Skip greetings.

Return STRICT JSON ONLY of the form:
{{"title": "<lecture title>", "subtitle": "<one-line summary>", "slides": [...]}}

Transcript:
\"\"\"{transcript}\"\"\"
"""


def _llm_outline(transcript_text: str, *, fallback_title: str) -> Optional[OutlineResult]:
    llm = get_llm()
    if not llm.is_available():
        return None
    excerpt = transcript_text[:9000]
    prompt = _OUTLINE_PROMPT.format(transcript=excerpt)
    try:
        return llm.generate_json(
            prompt,
            OutlineResult,
            temperature=0.25,
            max_retries=2,
            cache_namespace="slide_outline",
        )
    except LLMError as exc:
        print(f"[slides] LLM outline failed: {exc}")
        return None


def _heuristic_outline(transcript_segments: List[dict], fallback_title: str) -> SlideOutline:
    text = join_segments(transcript_segments)
    chunks = chunk_text(text, max_chars=900, overlap=80)
    slides = []
    for i, chunk in enumerate(chunks[:10]):
        # First sentence as title
        first_period = re.search(r"[.!?]", chunk)
        head = chunk[: first_period.start() + 1] if first_period else chunk[:80]
        bullets = [b.strip() for b in re.split(r"[.!?]\s+", chunk) if b.strip()][1:5]
        if not bullets:
            bullets = [chunk[:120]]
        # Best-effort timestamp
        if i < len(transcript_segments):
            ts = float(transcript_segments[i].get("start") or 0)
        else:
            ts = None
        slides.append(
            {
                "title": head[:80],
                "bullets": [b[:120] for b in bullets],
                "timestamp_seconds": ts,
                "section": "Intro" if i == 0 else "Core" if i < len(chunks) - 1 else "Wrap-up",
            }
        )
    return SlideOutline(title=fallback_title, subtitle=None, slides=slides)


def generate_outline(
    transcript_segments: List[dict],
    *,
    fallback_title: str = "Lecture Notes",
) -> SlideOutline:
    text = normalize_whitespace(join_segments(transcript_segments))
    if not text:
        return SlideOutline(title=fallback_title, subtitle=None, slides=[])

    llm_result = _llm_outline(text, fallback_title=fallback_title)
    if llm_result and llm_result.slides:
        slides_dicts = [s.model_dump() for s in llm_result.slides]
        return SlideOutline(
            title=llm_result.title or fallback_title,
            subtitle=llm_result.subtitle,
            slides=slides_dicts,
        )
    return _heuristic_outline(transcript_segments, fallback_title)


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

    story = [Paragraph(outline.title, title_style)]
    if outline.subtitle:
        story.append(Paragraph(outline.subtitle, subtitle_style))
    else:
        story.append(Spacer(1, 12))

    for slide in outline.slides:
        head = slide.get("title") or "Slide"
        ts = _format_ts(slide.get("timestamp_seconds"))
        section = slide.get("section") or ""
        story.append(Paragraph(f"<b>{head}</b>", h2))
        meta_bits = [b for b in [section, ts] if b]
        if meta_bits:
            story.append(Paragraph(" · ".join(meta_bits), section_style))
        bullets = [Paragraph(b, bullet_style) for b in (slide.get("bullets") or [])]
        if bullets:
            story.append(ListFlowable([ListItem(b) for b in bullets], bulletType="bullet", leftIndent=14))
        story.append(Spacer(1, 12))

    doc.build(story)
    return output_path


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

    # Title slide
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

    # Content slides
    for slide in outline.slides:
        ss = prs.slides.add_slide(title_layout)

        # Section label
        section = slide.get("section")
        ts = _format_ts(slide.get("timestamp_seconds"))
        meta_box = ss.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.5), Inches(0.5))
        meta = meta_box.text_frame.paragraphs[0]
        meta.text = " · ".join([b for b in [section or "", ts] if b])
        meta.runs[0].font.size = Pt(14)
        meta.runs[0].font.color.rgb = accent

        # Title
        ti_box = ss.shapes.add_textbox(Inches(0.8), Inches(1.0), Inches(11.5), Inches(1.2))
        ti = ti_box.text_frame.paragraphs[0]
        ti.text = slide.get("title") or "Slide"
        ti.runs[0].font.size = Pt(36)
        ti.runs[0].font.bold = True
        ti.runs[0].font.color.rgb = ink

        # Bullets
        body_box = ss.shapes.add_textbox(Inches(0.8), Inches(2.4), Inches(11.5), Inches(4.5))
        body_tf = body_box.text_frame
        body_tf.word_wrap = True
        bullets = slide.get("bullets") or []
        for i, b in enumerate(bullets):
            p = body_tf.paragraphs[0] if i == 0 else body_tf.add_paragraph()
            p.text = f"•  {b}"
            for run in p.runs:
                run.font.size = Pt(20)
                run.font.color.rgb = ink
            p.space_after = Pt(8)

    prs.save(str(output_path))
    return output_path


# ── Public API ────────────────────────────────────────────────────────────


def generate_documents(
    transcript_segments: List[dict],
    *,
    title: str,
    formats: list[str],
    output_dir: Optional[Path] = None,
) -> dict:
    """Generate the requested formats. Returns a dict of {fmt: file_path}."""
    if output_dir is None:
        output_dir = settings.generated_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    outline = generate_outline(transcript_segments, fallback_title=title)
    base = f"insighted-{uuid.uuid4().hex[:10]}"

    written: dict = {"outline": outline.to_dict(), "files": {}}
    for fmt in formats:
        fmt = (fmt or "").lower().strip()
        if fmt == "pdf":
            path = output_dir / f"{base}.pdf"
            render_pdf(outline, output_path=path)
            written["files"]["pdf"] = path
        elif fmt == "pptx":
            path = output_dir / f"{base}.pptx"
            render_pptx(outline, output_path=path)
            written["files"]["pptx"] = path
        else:
            raise ValueError(f"Unsupported format: {fmt}")
    return written
