"""
Video Processing Module
- Extracts audio from video using moviepy/ffmpeg
- Transcribes with Whisper (local)
- Falls back to mock transcript if neither is available
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Any


class VideoProcessor:
    def __init__(self):
        self.whisper_model = None
        self._has_ffmpeg = self._check_ffmpeg()
        self._load_whisper()

    def _check_ffmpeg(self) -> bool:
        import subprocess
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    def _load_whisper(self):
        try:
            import whisper
            self.whisper_model = whisper.load_model("base")
            print("[VideoProcessor] Whisper model loaded: base")
        except Exception:
            print("[VideoProcessor] Whisper not available — using mock transcript.")
            self.whisper_model = None

    def extract_audio(self, video_path: str) -> str:
        """Extract audio from video. Returns audio path or raises."""
        audio_path = str(Path(video_path).with_suffix(".wav"))

        # Try moviepy
        try:
            from moviepy.editor import VideoFileClip
            clip = VideoFileClip(video_path)
            clip.audio.write_audiofile(audio_path, verbose=False, logger=None)
            clip.close()
            print("[VideoProcessor] Audio extracted via moviepy")
            return audio_path
        except Exception as e:
            print(f"[VideoProcessor] moviepy failed: {e}")

        # Try ffmpeg via subprocess
        if self._has_ffmpeg:
            try:
                import subprocess
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", audio_path],
                    capture_output=True, text=True, timeout=300
                )
                if result.returncode == 0:
                    print("[VideoProcessor] Audio extracted via ffmpeg")
                    return audio_path
            except Exception as e:
                print(f"[VideoProcessor] ffmpeg failed: {e}")

        return None  # Signal to use mock

    def transcribe(self, audio_path: str) -> List[Dict[str, Any]]:
        if self.whisper_model is None or audio_path is None:
            return None
        # Pinned `openai-whisper==20231117` is known to hit
        # "size of tensor a (N) must match tensor b (3)" on newer torch builds
        # for certain audio shapes. The retry below uses safer decoding flags
        # (no fp16, single temperature, no previous-text conditioning) which
        # avoid the failing code path for most clips.
        for attempt, kwargs in enumerate((
            {"word_timestamps": False, "fp16": False, "language": "en"},
            {"word_timestamps": False, "fp16": False, "language": "en",
             "temperature": 0.0, "condition_on_previous_text": False},
        )):
            try:
                result = self.whisper_model.transcribe(audio_path, **kwargs)
                segments = []
                for seg in result.get("segments", []):
                    segments.append({
                        "timestamp": self._format_ts(seg["start"]),
                        "start": round(seg["start"], 2),
                        "end": round(seg["end"], 2),
                        "text": seg["text"].strip(),
                        "id": seg["id"],
                    })
                if segments:
                    return segments
            except Exception as e:
                print(f"[VideoProcessor] Transcription attempt {attempt + 1} failed: {e}")
        return None

    def process(self, video_path: str) -> List[Dict[str, Any]]:
        print(f"[VideoProcessor] Processing: {video_path}")

        # Try real transcription
        print("[VideoProcessor] Starting audio extraction (this might take a minute)...")
        audio_path = self.extract_audio(video_path)
        if audio_path:
            print("[VideoProcessor] Audio extracted successfully. Starting Whisper transcription (this can take SEVERAL MINUTES on a CPU, please wait)...")
            transcript = self.transcribe(audio_path)
            # Clean up temp audio
            try:
                if audio_path != video_path and os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception:
                pass
            if transcript:
                print(f"[VideoProcessor] Got {len(transcript)} real segments")
                return transcript

        # Fallback: generate mock transcript scaled to video duration
        print("[VideoProcessor] Using mock transcript (install ffmpeg + whisper for real transcription)")
        return self._mock_transcript(video_path)

    @staticmethod
    def _format_ts(seconds: float) -> str:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def _mock_transcript(self, video_path: str) -> List[Dict[str, Any]]:
        """Neutral placeholder for when transcription is unavailable.

        Returns one obvious-failure segment so downstream stages can run
        without crashing, but the user sees clearly that transcription
        failed instead of being shown plausible-looking but unrelated text.
        """
        duration = self._get_duration(video_path) or 60.0
        return [{
            "id": 0,
            "timestamp": "00:00",
            "start": 0.0,
            "end": round(duration, 2),
            "text": (
                "Transcription unavailable — Whisper could not process the audio "
                "for this video. Please retry the upload."
            ),
        }]

    def _get_duration(self, video_path: str) -> float:
        """Try to get video duration in seconds."""
        # Try ffmpeg probe
        if self._has_ffmpeg:
            try:
                import subprocess, json
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_format", video_path],
                    capture_output=True, text=True, timeout=15
                )
                if result.returncode == 0:
                    info = json.loads(result.stdout)
                    return float(info["format"]["duration"])
            except Exception:
                pass

        # Try moviepy
        try:
            from moviepy.editor import VideoFileClip
            clip = VideoFileClip(video_path)
            d = clip.duration
            clip.close()
            return d
        except Exception:
            pass

        return 200.0  # Default 200s
