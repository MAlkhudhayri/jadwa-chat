"""Series discovery — maps natural language queries to series_id."""

import json
import logging
from typing import List, Optional, Tuple

from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.timeseries import SeriesCatalog

logger = logging.getLogger(__name__)


class SeriesDiscoveryService:
    async def search(self, query: str, top_k: int = 5) -> List[dict]:
        """Search for matching series using text matching + synonym search."""
        query_lower = query.lower().strip()
        factory = await get_session_factory()
        session = factory()

        try:
            result = await session.execute(select(SeriesCatalog))
            all_series = result.scalars().all()

            scored = []
            for s in all_series:
                score = self._score(query_lower, s)
                if score > 0:
                    scored.append((score, s))

            scored.sort(key=lambda x: x[0], reverse=True)

            return [
                {
                    "series_id": s.series_id,
                    "name": s.name,
                    "domain": s.domain,
                    "source": s.source,
                    "unit": s.unit,
                    "score": score,
                    "description": s.description,
                }
                for score, s in scored[:top_k]
            ]
        finally:
            await session.close()

    def _score(self, query: str, series: SeriesCatalog) -> float:
        """Score a series against the query using weighted text matching."""
        score = 0.0
        name_lower = series.name.lower()
        desc_lower = (series.description or "").lower()
        sid_lower = series.series_id.lower().replace("_", " ")

        # Exact name match
        if query in name_lower:
            score += 10.0
        # Series ID match
        if query in sid_lower:
            score += 8.0
        # Description match
        if query in desc_lower:
            score += 3.0

        # Word-level matching
        query_words = set(query.split())
        name_words = set(name_lower.split())
        desc_words = set(desc_lower.split())

        # Name word overlap
        name_overlap = query_words & name_words
        score += len(name_overlap) * 3.0

        # Description word overlap
        desc_overlap = query_words & desc_words
        score += len(desc_overlap) * 1.0

        # Synonym matching
        try:
            synonyms = json.loads(series.synonyms or "[]")
            for syn in synonyms:
                syn_lower = syn.lower()
                if query in syn_lower or syn_lower in query:
                    score += 8.0
                    break
                syn_words = set(syn_lower.split())
                syn_overlap = query_words & syn_words
                if syn_overlap:
                    score += len(syn_overlap) * 4.0
        except (json.JSONDecodeError, TypeError):
            pass

        # Domain matching (boost if domain mentioned)
        domain_keywords = {
            "oil": ["oil", "crude", "brent", "production", "barrel", "opec", "petroleum"],
            "bop": ["balance", "payments", "current account", "services", "reserves"],
            "fiscal": ["revenue", "expenditure", "debt", "gdp", "fiscal", "budget", "spending"],
            "stability": ["reserves", "money supply", "saibor", "sofr", "foreign assets", "m3"],
            "banking": ["bank", "loan", "deposit", "roe", "npl", "capital adequacy", "ldr"],
        }
        for domain, keywords in domain_keywords.items():
            if series.domain == domain:
                for kw in keywords:
                    if kw in query:
                        score += 2.0

        return score

    async def get_all_series(self) -> List[dict]:
        """Get all series from catalog."""
        factory = await get_session_factory()
        session = factory()
        try:
            result = await session.execute(select(SeriesCatalog))
            return [
                {
                    "series_id": s.series_id,
                    "name": s.name,
                    "domain": s.domain,
                    "source": s.source,
                    "unit": s.unit,
                }
                for s in result.scalars().all()
            ]
        finally:
            await session.close()


_discovery_service: Optional[SeriesDiscoveryService] = None


def get_discovery_service() -> SeriesDiscoveryService:
    global _discovery_service
    if _discovery_service is None:
        _discovery_service = SeriesDiscoveryService()
    return _discovery_service

