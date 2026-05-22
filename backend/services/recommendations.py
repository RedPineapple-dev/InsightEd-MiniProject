"""Real-source learning resource recommendations (Part 6, simplified).

Three sources, ranked and merged in parallel:

  * arXiv          — research papers (via the `arxiv` library, no key)
  * YouTube        — Data API if YOUTUBE_API_KEY is set; otherwise a curated
                     search-URL fallback so the UI still gets *something*.
  * Wikipedia      — concept overview / documentation entry (REST API, no key)

Per the product brief, we deliberately dropped GitHub repos and MDN search
links — they were noisy for an educational learning workflow.

Each call is short-circuited on error and timed-out so a slow upstream cannot
stall a recommendation request.
"""

from __future__ import annotations

import concurrent.futures as cf
from typing import Callable, List
from urllib.parse import quote_plus

import requests

from config import settings


_TIMEOUT = 6  # seconds per upstream call


def _safe(fn: Callable[[], list]) -> list:
    try:
        return fn() or []
    except Exception as exc:
        print(f"[recs] {fn.__name__} failed: {exc}")
        return []


# ── Per-source fetchers ────────────────────────────────────────────────────


def _arxiv_papers(query: str, *, max_results: int = 4) -> list:
    try:
        import arxiv  # type: ignore
    except ImportError:
        return []

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    out = []
    for r in arxiv.Client(page_size=max_results, num_retries=1, delay_seconds=1).results(search):
        out.append(
            {
                "title": r.title.strip(),
                "url": r.entry_id,
                "category": "research_paper",
                "source": "arXiv",
                "description": (r.summary or "").strip().replace("\n", " ")[:240],
                "thumbnail_url": None,
                "tags": [c for c in (r.categories or [])[:3]],
                "relevance_score": 0.85,
            }
        )
    return out


def _github_repos(query: str, *, max_results: int = 4) -> list:
    url = "https://api.github.com/search/repositories"
    res = requests.get(
        url,
        params={"q": query, "sort": "stars", "order": "desc", "per_page": max_results},
        timeout=_TIMEOUT,
        headers={"Accept": "application/vnd.github+json"},
    )
    if not res.ok:
        return []
    out = []
    items = res.json().get("items") or []
    if not items:
        return []
    max_stars = max(it.get("stargazers_count") or 1 for it in items)
    for it in items:
        stars = it.get("stargazers_count") or 0
        out.append(
            {
                "title": it.get("full_name") or it.get("name"),
                "url": it.get("html_url"),
                "category": "github",
                "source": "GitHub",
                "description": (it.get("description") or "")[:200],
                "thumbnail_url": (it.get("owner") or {}).get("avatar_url"),
                "tags": [it.get("language") or "code"],
                "relevance_score": round(0.4 + 0.5 * (stars / max(max_stars, 1)), 3),
            }
        )
    return out


def _wikipedia_summary(query: str) -> list:
    res = requests.get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(query)}",
        timeout=_TIMEOUT,
        headers={"Accept": "application/json"},
    )
    if not res.ok:
        return []
    data = res.json()
    if not data.get("extract"):
        return []
    return [
        {
            "title": data.get("title") or query,
            "url": (data.get("content_urls") or {}).get("desktop", {}).get("page")
            or f"https://en.wikipedia.org/wiki/{quote_plus(query)}",
            "category": "documentation",
            "source": "Wikipedia",
            "description": (data.get("extract") or "")[:240],
            "thumbnail_url": (data.get("thumbnail") or {}).get("source"),
            "tags": ["overview"],
            "relevance_score": 0.8,
        }
    ]


def _youtube_videos(query: str, *, max_results: int = 4) -> list:
    key = settings.youtube_api_key
    if key:
        res = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": query,
                "maxResults": max_results,
                "type": "video",
                "videoEmbeddable": "true",
                "relevanceLanguage": "en",
                "key": key,
            },
            timeout=_TIMEOUT,
        )
        if not res.ok:
            return _youtube_fallback(query)
        out = []
        for it in res.json().get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            sn = it.get("snippet") or {}
            if not vid:
                continue
            out.append(
                {
                    "title": sn.get("title", "YouTube video"),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "category": "youtube",
                    "source": "YouTube",
                    "description": (sn.get("description") or "")[:200],
                    "thumbnail_url": (
                        (sn.get("thumbnails") or {}).get("medium")
                        or (sn.get("thumbnails") or {}).get("default")
                        or {}
                    ).get("url"),
                    "tags": [sn.get("channelTitle", "video")],
                    "relevance_score": 0.78,
                }
            )
        return out
    return _youtube_fallback(query)


def _youtube_fallback(query: str) -> list:
    return [
        {
            "title": f"YouTube — {query}",
            "url": f"https://www.youtube.com/results?search_query={quote_plus(query + ' tutorial')}",
            "category": "youtube",
            "source": "YouTube search",
            "description": "Curated educational tutorials on YouTube.",
            "thumbnail_url": None,
            "tags": ["search"],
            "relevance_score": 0.55,
        }
    ]


def _mdn_search(query: str) -> list:
    return [
        {
            "title": f"MDN Web Docs — {query}",
            "url": f"https://developer.mozilla.org/en-US/search?q={quote_plus(query)}",
            "category": "documentation",
            "source": "MDN",
            "description": "Mozilla's official documentation for the open web.",
            "thumbnail_url": None,
            "tags": ["docs"],
            "relevance_score": 0.5,
        }
    ]


# ── Aggregator ─────────────────────────────────────────────────────────────


def gather_resources(
    query: str,
    *,
    include_papers: bool = True,
    include_videos: bool = True,
    include_docs: bool = True,
    limit: int = 18,
    # Back-compat: callers may still pass the old flags; they're just ignored.
    include_repos: bool = False,
    include_articles: bool = False,
) -> List[dict]:
    """Fan out to enabled upstreams concurrently and merge results."""
    query = (query or "").strip()
    if not query:
        return []

    fetchers: list[Callable[[], list]] = []
    if include_videos:
        fetchers.append(lambda: _safe(lambda: _youtube_videos(query)))
    if include_papers:
        fetchers.append(lambda: _safe(lambda: _arxiv_papers(query)))
    if include_docs:
        fetchers.append(lambda: _safe(lambda: _wikipedia_summary(query)))

    results: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=len(fetchers) or 1) as pool:
        for batch in pool.map(lambda fn: fn(), fetchers):
            results.extend(batch)

    # De-dupe by URL, then sort by relevance
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in results:
        url = r.get("url") or ""
        if url in seen:
            continue
        seen.add(url)
        deduped.append(r)

    deduped.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)
    return deduped[:limit]


def gather_for_topics(topics: List[dict], *, limit_per_topic: int = 6) -> List[dict]:
    """Multi-topic recommendation. Each topic contributes a few resources."""
    seen_urls: set[str] = set()
    out: list[dict] = []
    for topic in topics:
        q = topic.get("summary") or topic.get("name") or ""
        for r in gather_resources(q, limit=limit_per_topic):
            if r.get("url") in seen_urls:
                continue
            seen_urls.add(r["url"])
            r = {**r, "tags": list({*(r.get("tags") or []), topic.get("name", "topic")})}
            out.append(r)
    return out
