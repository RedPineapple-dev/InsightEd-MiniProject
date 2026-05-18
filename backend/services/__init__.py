"""AI service layer.

The previous monolithic `llm_engine.py` mixed prompt building, JSON parsing,
fallbacks and Gemini calls. This package separates concerns:

  - llm.LLMClient        : retryable Gemini wrapper with structured-output validation
  - text_processing      : chunking, normalisation
  - topic_extraction     : NLP keywords (YAKE/KeyBERT) + LLM topic synthesis
  - resource_search      : real-source recommendations (Part 6)

`llm_engine.py` continues to expose its old functions; they now delegate here.
"""

from .domain_normalization import (
    extract_canonical_terms,
    normalize_segments,
    normalize_text,
)
from .llm import LLMClient, LLMError, get_llm
from .recommendations import gather_for_topics, gather_resources
from .structured_notes import (
    generate_note,
    generate_notes,
    select_publishable_notes,
)
from .text_processing import chunk_text, normalize_whitespace, top_segments
from .topic_extraction import extract_keywords, extract_topics
from .topic_segmentation import (
    fuse_chunk_context,
    overall_topic_signature,
    segment_transcript,
)

__all__ = [
    "LLMClient",
    "LLMError",
    "get_llm",
    "chunk_text",
    "normalize_whitespace",
    "top_segments",
    "extract_keywords",
    "extract_topics",
    "gather_resources",
    "gather_for_topics",
    "normalize_text",
    "normalize_segments",
    "extract_canonical_terms",
    "segment_transcript",
    "fuse_chunk_context",
    "overall_topic_signature",
    "generate_note",
    "generate_notes",
    "select_publishable_notes",
]
