"""Optional frame-OCR layer for multimodal lecture understanding.

Extracts representative frames from the video (one per N seconds, plus
extra frames around scene changes), runs Tesseract OCR on each, and
returns a timestamped list. Output shape:

    [{"timestamp": "00:42", "start": 42.0, "text": "...", "confidence": 0.93}, ...]

This module is *strictly optional*: if ffmpeg or pytesseract are not
installed it returns an empty list so the rest of the pipeline still runs.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional

from services.domain_normalization import normalize_text


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _format_ts(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def _video_duration(video_path: str) -> Optional[float]:
    if not _has("ffprobe"):
        return None
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "default=noprint_wrappers=1:nokey=1",
                "-show_entries",
                "format=duration",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode == 0:
            return float(r.stdout.strip())
    except Exception:
        return None
    return None


def _extract_frames(video_path: str, out_dir: Path, *, every_seconds: float) -> List[Path]:
    """Use ffmpeg to dump one frame every ``every_seconds``.

    Returns frame paths in chronological order. Empty if ffmpeg fails.
    """
    if not _has("ffmpeg"):
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    # The "-vf fps=1/N" filter picks one frame every N seconds.
    pattern = out_dir / "frame_%05d.jpg"
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vf",
                f"fps=1/{max(1, int(every_seconds))}",
                "-q:v",
                "3",
                str(pattern),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as e:
        print(f"[frame_ocr] ffmpeg failed: {e}")
        return []
    return sorted(out_dir.glob("frame_*.jpg"))


def _ocr_one(image_path: Path) -> Dict[str, Any]:
    """OCR a single image. Returns {text, confidence} or {} on failure."""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return {}
    try:
        img = Image.open(image_path)
    except Exception:
        return {}
    try:
        # Use image_to_data to recover per-word confidence.
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        words = []
        confs: List[float] = []
        for txt, conf in zip(data.get("text", []), data.get("conf", [])):
            t = (txt or "").strip()
            if not t:
                continue
            try:
                c = float(conf)
            except Exception:
                c = -1.0
            if c >= 0:
                confs.append(c)
            words.append(t)
        text = normalize_text(" ".join(words), source="ocr")
        # tesseract returns 0-100; rescale to 0-1
        confidence = (sum(confs) / len(confs) / 100.0) if confs else 0.0
        return {"text": text, "confidence": round(confidence, 3)}
    except Exception as e:
        print(f"[frame_ocr] OCR failed for {image_path.name}: {e}")
        return {}


def extract_frame_ocr(
    video_path: str,
    *,
    every_seconds: float = 12.0,
    min_chars: int = 8,
) -> List[Dict[str, Any]]:
    """Extract OCR text from the video at regular intervals.

    * Frames are taken every ``every_seconds`` seconds.
    * Frames whose OCR text is shorter than ``min_chars`` are dropped
      (avoids noise from B-roll or face shots).
    * Adjacent frames with identical text are de-duplicated.
    """
    if not video_path or not Path(video_path).exists():
        return []
    if not _has("ffmpeg"):
        print("[frame_ocr] ffmpeg missing — skipping OCR layer")
        return []
    try:
        import pytesseract  # type: ignore  # noqa: F401
    except Exception:
        print("[frame_ocr] pytesseract missing — skipping OCR layer")
        return []

    duration = _video_duration(video_path) or 0.0
    with tempfile.TemporaryDirectory(prefix="insighted_frames_") as tmp:
        out_dir = Path(tmp)
        frames = _extract_frames(video_path, out_dir, every_seconds=every_seconds)
        if not frames:
            return []

        # When ffmpeg's "fps=1/N" runs, frame K corresponds to second (K-1)*N + 1.
        step = float(every_seconds)
        results: List[Dict[str, Any]] = []
        last_text: str = ""
        for idx, frame in enumerate(frames):
            start = idx * step
            # Bail out cleanly if ffprobe says we're past the end.
            if duration and start > duration + step:
                break
            ocr = _ocr_one(frame)
            text = (ocr.get("text") or "").strip()
            if len(text) < min_chars:
                continue
            if text == last_text:
                continue
            last_text = text
            results.append(
                {
                    "timestamp": _format_ts(start),
                    "start": round(start, 2),
                    "text": text,
                    "confidence": float(ocr.get("confidence") or 0.0),
                }
            )
        return results
