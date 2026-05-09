"""
LLM Engine Module
Handles Gemini API integration with strict prompt design and JSON validation.
"""

import json
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv(override=True)

# Gemini SDK
try:
    import google.generativeai as genai
except ImportError:
    raise ImportError(
        "google-generativeai package is not installed. Please install it."
    )

# Load API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment.")

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)

# =========================
# MODEL CONFIG
# =========================

# WORKING MODEL
DEFAULT_MODEL = "gemini-1.5-flash"

# Initialize model
model = genai.GenerativeModel(DEFAULT_MODEL)

# =========================
# Pydantic Models
# =========================

class MatchResult(BaseModel):
    type: str = Field(description="Must be 'slide' or 'pdf'")
    id: int = Field(description="The ID of the matched document/slide")
    reason: str = Field(
        description="Short explanation of why this is the best match"
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0"
    )


class ConceptAnnotation(BaseModel):
    concept: str = Field(description="The name of the concept extracted")
    explanation: str = Field(
        description="Clear and concise explanation of the concept"
    )
    importance: str = Field(
        description="Importance level: high, medium, or low"
    )


class AnnotationResult(BaseModel):
    concepts: List[ConceptAnnotation] = Field(
        description="List of extracted concepts"
    )


# =========================
# Prompt Builders
# =========================

def build_matching_prompt(
    segment_text: str,
    candidates: List[Dict[str, Any]],
) -> str:
    """
    Build prompt for matching transcript segment to slide/document.
    """

    lines = [
        "You are an AI system that links lecture video content to slides or PDF pages.",
        "",
        "Video transcript segment:",
        segment_text.strip(),
        "",
        "Candidates:",
    ]

    for idx, candidate in enumerate(candidates, start=1):
        doc_type = candidate.get("type", "unknown")
        doc_id = candidate.get("id", "?")
        doc_text = candidate.get("text", "").strip()

        lines.append(
            f"{idx}. ({doc_type} {doc_id}): {doc_text[:300]}"
        )

    lines.extend([
        "",
        "Select the BEST matching candidate.",
        "",
        "Return ONLY valid JSON in this exact format:",
        """
{
  "type": "slide",
  "id": 1,
  "reason": "why this matches",
  "confidence": 0.95
}
"""
    ])

    return "\n".join(lines)


# =========================
# Utilities
# =========================

def clean_json_response(text: str) -> Dict[str, Any]:
    """
    Clean Gemini response and parse JSON safely.
    """

    text = text.strip()

    # Remove markdown wrappers if present
    if text.startswith("```json"):
        text = text.replace("```json", "").replace("```", "").strip()

    elif text.startswith("```"):
        text = text.replace("```", "").strip()

    return json.loads(text)


# =========================
# Matching Engine
# =========================

def match_segment_to_document(
    segment_text: str,
    candidates: List[Dict[str, Any]],
    model_name: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """
    Match transcript segment to best slide/document.
    """

    if not candidates:
        raise ValueError("No candidates provided")

    prompt = build_matching_prompt(segment_text, candidates)

    try:
        local_model = genai.GenerativeModel(model_name)

        response = local_model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.1,
            }
        )

        result = clean_json_response(response.text)

        # Validate result belongs to candidate list
        valid_match = False

        for candidate in candidates:
            if (
                candidate.get("type") == result.get("type")
                and candidate.get("id") == result.get("id")
            ):
                valid_match = True
                break

        # Fallback if invalid match
        if not valid_match:
            print(
                f"Warning: Invalid Gemini match "
                f"{result.get('type')} {result.get('id')}"
            )

            best = candidates[0]

            result = {
                "type": best.get("type", "unknown"),
                "id": best.get("id", 0),
                "reason": "Fallback to best semantic candidate.",
                "confidence": 0.5,
            }

        return result

    except Exception as e:
        print(f"Gemini matching failed: {e}")

        # Safe fallback
        best = candidates[0]

        return {
            "type": best.get("type", "unknown"),
            "id": best.get("id", 0),
            "reason": f"Fallback due to Gemini error: {str(e)}",
            "confidence": 0.0,
        }


# =========================
# Annotation Engine
# =========================

def generate_annotations(
    segment_text: str,
    model_name: str = DEFAULT_MODEL,
) -> List[Dict[str, Any]]:
    """
    Generate concept annotations from transcript segment.
    """

    if not segment_text.strip():
        return []

    prompt = f"""
Analyze the following lecture transcript segment and extract important concepts.

For each concept provide:
- concept
- explanation
- importance (high, medium, low)

Transcript:
{segment_text}

Return ONLY valid JSON in this format:

{{
  "concepts": [
    {{
      "concept": "Example Concept",
      "explanation": "Explanation here",
      "importance": "high"
    }}
  ]
}}
"""

    try:
        local_model = genai.GenerativeModel(model_name)

        response = local_model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.2,
            }
        )

        result = clean_json_response(response.text)

        return result.get("concepts", [])

    except Exception as e:
        print(f"Gemini annotation failed: {e}")
        return []