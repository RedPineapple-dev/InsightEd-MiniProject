"""
Annotation Engine
- Extracts key concepts from transcript segments
- Annotates video timeline with concepts + explanations
- Provides recommendation logic
"""

import re
from typing import List, Dict, Any, Optional
import numpy as np

from llm_engine import generate_annotations
from services.recommendations import gather_resources
from services.text_processing import join_segments
from services.topic_extraction import extract_topics


def resource_search_links(concept: str) -> List[Dict[str, Any]]:
    """Real-source recommendations (Part 6).

    Aggregates Wikipedia, YouTube, arXiv, GitHub and MDN concurrently and
    returns ranked `RecommendedResource`-shaped dicts.

    The function name is preserved for backwards compatibility with callers
    that already imported it.
    """
    if not concept:
        return []
    return gather_resources(concept, limit=12)


class AnnotationEngine:
    def __init__(self, embedding_engine=None):
        self.ee = embedding_engine

    def annotate_transcript(
        self,
        transcript: List[Dict[str, Any]],
        embeddings: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Annotate each transcript segment with concepts."""
        annotations = []
        
        # To avoid Gemini Free Tier rate limits, we group segments into larger chunks.
        # Chunking 100 segments (~5 minutes of video) at a time ensures we only make
        # ~5 requests total for a 30-minute video, staying well below any strict quotas.
        chunk_size = 100 # Group 100 segments at a time
        
        import time
        
        from services.llm import get_llm
        llm = get_llm()

        for i in range(0, len(transcript), chunk_size):
            chunk = transcript[i:i+chunk_size]
            combined_text = " ".join([s.get("text", "") for s in chunk])

            chunk_num = i // chunk_size + 1
            total_chunks = (len(transcript) + chunk_size - 1) // chunk_size
            print(f"[AnnotationEngine] Annotating chunk {chunk_num}/{total_chunks}...")

            # Fail fast if the LLM circuit is open — no point sleeping 4s per chunk
            # if every call short-circuits.
            if not llm.is_available():
                print(f"[AnnotationEngine] LLM unavailable; using empty annotations for remaining chunks.")
                concepts = []
            else:
                try:
                    concepts = generate_annotations(combined_text)
                    # Polite pacing only when we actually called the API.
                    # Skip sleep on cache hits and on the final chunk.
                    if chunk_num < total_chunks:
                        time.sleep(2)
                except Exception as e:
                    print(f"[AnnotationEngine] API limit/error reached: {e}")
                    concepts = []
            
            # Ensure concept is an array of dicts with concept, explanation, importance
            formatted_concepts = []
            for c in concepts:
                formatted_concepts.append({
                    "concept": c.get("concept", "General"),
                    "explanation": c.get("explanation", "Discussed in this segment."),
                    "importance": c.get("importance", "medium"),
                })
                
            if not formatted_concepts:
                 formatted_concepts = [{
                    "concept": "General Discussion",
                    "explanation": "No detailed annotations available due to API rate limits.",
                    "importance": "low"
                 }]
                 
            # Assign annotation to the middle of the chunk for timeline placement
            mid_idx = len(chunk) // 2
            target_seg = chunk[mid_idx]
                
            annotations.append({
                "id": target_seg.get("id", 0),
                "timestamp": target_seg.get("timestamp", "00:00"),
                "start": chunk[0].get("start", 0),
                "end": chunk[-1].get("end", 0),
                "text": combined_text,
                "concepts": formatted_concepts,
                "primary_concept": formatted_concepts[0]["concept"],
            })
            
        return annotations

    def recommend(
        self,
        concept: Optional[str],
        timestamp: Optional[float],
        transcript: List[Dict[str, Any]],
        slides: List[Dict[str, Any]],
        embeddings: Dict[str, Any],
        analytics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return recommended slides/segments for a given concept or timestamp.

        Shape: {"recommendations": [...], "resources": [...]}
        """
        results = []

        # Get difficult segments from analytics
        difficult = analytics.get("difficult_segments", [])

        if not concept and timestamp is not None:
            # Find the segment near timestamp
            for seg in transcript:
                if seg.get("start", 0) <= timestamp <= seg.get("end", 9999):
                    # We no longer have extract_keywords, so let's check generated concepts
                    # or just take a small chunk of text if no concepts exist.
                    # Wait, we can't easily extract a keyword instantly without LLM.
                    # Let's fallback to taking the first word or use LLM.
                    # Since this might be called frequently, we'll try to find an existing annotation.
                    # If we passed annotations, we could use them. We don't have them here.
                    # We will just use the first 2 words as a fallback concept.
                    words = [w for w in re.findall(r"\b[a-zA-Z]{3,}\b", seg["text"].lower())]
                    concept = words[0] if words else None
                    break

        if not concept:
            # Default to most difficult concept
            if difficult:
                concept = difficult[0].get("primary_concept", "")

        if not concept:
            return []

        query_emb = None
        if self.ee and embeddings.get("slides"):
            query_emb = self.ee.encode_single(concept)

        # Search slides
        for idx, slide in enumerate(slides):
            score = 0.5  # default
            if query_emb is not None and embeddings.get("slides"):
                s_embs = np.array(embeddings["slides"])
                if idx < len(s_embs):
                    score = self.ee.cosine_similarity(query_emb, s_embs[idx])

            if score > 0.3:
                results.append({
                    "type": "slide",
                    "id": slide["id"],
                    "title": slide["title"],
                    "score": round(float(score), 3),
                    "reason": f"Related to '{concept}'",
                })

        # Search transcript
        for idx, seg in enumerate(transcript):
            score = 0.5
            if query_emb is not None and embeddings.get("transcript"):
                t_embs = np.array(embeddings["transcript"])
                if idx < len(t_embs):
                    score = self.ee.cosine_similarity(query_emb, t_embs[idx])

            if score > 0.4:
                results.append({
                    "type": "transcript",
                    "id": seg.get("id", idx),
                    "timestamp": seg["timestamp"],
                    "start": seg.get("start", 0),
                    "text": seg["text"][:100] + "...",
                    "score": round(float(score), 3),
                    "reason": f"Related to '{concept}'",
                })

        # Sort by score and deduplicate
        results.sort(key=lambda x: x["score"], reverse=True)

        # Build a richer query: concept + a sampled snippet of the transcript
        # to bias topic searches toward the actual lecture context.
        snippet = join_segments(transcript[:6])[:300]
        topics = extract_topics(f"{concept}. {snippet}", fallback_keywords=True)
        if topics:
            primary = topics[0].get("summary") or topics[0].get("name") or concept
        else:
            primary = concept
        resources = gather_resources(primary, limit=12)

        return {"recommendations": results[:8], "resources": resources}
