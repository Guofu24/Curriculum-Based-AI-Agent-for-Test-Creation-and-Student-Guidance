"""SerpAPI wrapper for web search — used by Builder Agent for van_dung_cao questions (G4)."""

import asyncio
import os
from typing import Any

from app.core.config import get_settings

settings = get_settings()


def _get_serpapi_key() -> str | None:
    """Get SerpAPI key from environment or settings."""
    key = os.environ.get("SERPAPI_KEY") or getattr(settings, "SERPAPI_KEY", None)
    return key if key and key != "your-serpapi-key" else None


async def search_similar_problems(
    query: str,
    subject: str = "physics",
    num_results: int = 5,
) -> list[dict]:
    """
    Search for similar problems using SerpAPI Google search.

    G4: Called by Builder Agent when generating van_dung_cao questions
    to find real-world / exam-style reference problems.

    Args:
        query: Search query (e.g. "vật trượt trên mặt phẳng nghiêng bài toán hay")
        subject: Subject name for context (used in query refinement)
        num_results: Number of results to return (default 5)

    Returns:
        List of dicts with keys: {title, snippet, url}
    """
    serpapi_key = _get_serpapi_key()

    if not serpapi_key:
        return _mock_results(query, num_results)

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            _blocking_search,
            query,
            subject,
            num_results,
            serpapi_key,
        )
        return result
    except Exception:
        return _mock_results(query, num_results)


def _blocking_search(
    query: str,
    subject: str,
    num_results: int,
    serpapi_key: str,
) -> list[dict]:
    """
    Synchronous SerpAPI call — MUST be run in an executor.
    Uses google-search-results library.
    """
    try:
        from serpapi import GoogleSearch

        params = {
            "q": query,
            "hl": "vi",
            "gl": "vn",
            "num": num_results,
            "api_key": serpapi_key,
        }

        search = GoogleSearch(params)
        results = search.get_dict()

        organic = results.get("organic_results", [])
        parsed = []
        for item in organic[:num_results]:
            parsed.append({
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "url": item.get("link", ""),
            })

        return parsed

    except ImportError:
        return _mock_results(query, num_results)
    except Exception:
        return _mock_results(query, num_results)


def _mock_results(query: str, num_results: int) -> list[dict]:
    """
    Fallback when SerpAPI key is not configured or call fails.
    Returns empty results (Builder Agent will proceed without web context).
    """
    return []
