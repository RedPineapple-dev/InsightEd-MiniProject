"""AI service layer.

The previous monolithic `llm_engine.py` mixed prompt building, JSON parsing,
fallbacks and Gemini calls. This package separates concerns:

  - llm.LLMClient        : retryable Gemini wrapper with structured-output validation
  - text_processing      : chunking, normalisation
  - topic_extraction     : NLP keywords (YAKE/KeyBERT) + LLM topic synthesis
  - resource_search      : real-source recommendations (Part 6)

`llm_engine.py` continues to expose its old functions; they now delegate here.
"""

from .llm import LLMClient, LLMError, get_llm
from .recommendations import gather_for_topics, gather_resources
from .text_processing import chunk_text, normalize_whitespace, top_segments
from .topic_extraction import extract_keywords, extract_topics

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
]
