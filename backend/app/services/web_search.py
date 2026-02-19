"""
Web search fallback — uses DuckDuckGo (free, no API key required).

Used when:
  1. Qdrant/SQLite have no relevant context for the user's question
  2. The question is about current events, general knowledge, or external topics
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single web search result."""
    title: str
    snippet: str
    url: str


class WebSearchService:
    """DuckDuckGo-based web search for fallback answers."""

    def __init__(self, max_results: int = 5):
        self.max_results = max_results

    async def search(self, query: str, max_results: Optional[int] = None) -> List[SearchResult]:
        """Search the web and return top results.
        
        Runs in a thread pool since ddgs is synchronous.
        """
        k = max_results or self.max_results
        try:
            results = await asyncio.to_thread(self._search_sync, query, k)
            return results
        except Exception as e:
            logger.warning(f"Web search failed for '{query[:50]}': {e}")
            return []

    def _search_sync(self, query: str, max_results: int) -> List[SearchResult]:
        """Synchronous DuckDuckGo search using the ddgs package."""
        from ddgs import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(SearchResult(
                    title=r.get("title", ""),
                    snippet=r.get("body", ""),
                    url=r.get("href", ""),
                ))

        logger.info(f"Web search for '{query[:50]}': {len(results)} results")
        return results

    def format_context(self, results: List[SearchResult]) -> str:
        """Format search results into context for the LLM."""
        if not results:
            return ""

        parts = []
        for i, r in enumerate(results, 1):
            parts.append(
                f"[Web Result {i}] {r.title}\n"
                f"{r.snippet}\n"
                f"Source: {r.url}"
            )
        return "\n\n".join(parts)

    def format_citations(self, results: List[SearchResult]) -> List[str]:
        """Build citation strings for web results."""
        citations = []
        for r in results:
            citations.append(f"🌐 [{r.title}]({r.url})")
        return citations


# ──────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────

_web_search: Optional[WebSearchService] = None


def get_web_search_service() -> WebSearchService:
    global _web_search
    if _web_search is None:
        _web_search = WebSearchService()
    return _web_search
