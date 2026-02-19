"""Series discovery — maps natural language queries to series_id."""

import json
import logging
import re as _re
from typing import List, Optional, Tuple

from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.timeseries import SeriesCatalog

logger = logging.getLogger(__name__)

# ── Shared helpers ──────────────────────────────────────────────────────────
_STOP_WORDS = {
    "a", "an", "the", "is", "was", "were", "are", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "and", "but", "or", "nor", "not", "no",
    "so", "yet", "both", "either", "neither", "each", "every", "all",
    "any", "few", "more", "most", "other", "some", "such", "only",
    "own", "same", "than", "too", "very", "just", "because", "about",
    "between", "how", "what", "which", "who", "whom", "this", "that",
    "these", "those", "am", "it", "its", "they", "them", "their",
    "we", "our", "he", "she", "him", "her", "me", "my", "i", "you",
    "your", "if", "then", "up", "out", "off", "over", "under",
    "again", "further", "once", "here", "there", "when", "where",
    "why", "much", "many", "tell", "please", "give", "show", "latest",
    "current", "today", "now", "last", "recent",
}

_clean = lambda w: _re.sub(r"[^a-z0-9]", "", w.lower())

_DOMAIN_KEYWORDS = {
    "oil":       ["oil", "crude", "brent", "production", "barrel", "opec", "petroleum", "wti"],
    "bop":       ["balance", "payments", "current account", "services", "bop"],
    "fiscal":    ["revenue", "expenditure", "debt", "gdp", "fiscal", "budget", "spending"],
    "stability": ["reserves", "money supply", "saibor", "sofr", "foreign assets", "m3", "m1", "m2"],
    "banking":   ["banking", "bank", "loan", "deposit", "roe", "npl", "capital adequacy", "ldr"],
}


class SeriesDiscoveryService:
    async def search(self, query: str, top_k: int = 5,
                     collection_name: Optional[str] = None) -> List[dict]:
        """Search for matching series using text matching + synonym search.

        If collection_name is provided, only search series in that collection
        (plus pre-loaded series with no collection). If 'all-databases' or None, search all.
        """
        query_lower = query.lower().strip()
        factory = await get_session_factory()
        session = factory()

        try:
            stmt = select(SeriesCatalog)
            if collection_name and collection_name != "all-databases":
                stmt = stmt.where(
                    (SeriesCatalog.collection_name == collection_name) |
                    (SeriesCatalog.collection_name == None) |
                    (SeriesCatalog.collection_name == "")
                )
            result = await session.execute(stmt)
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
        """Score a series against the query using weighted text matching.

        Scoring layers (highest to lowest):
          1. Exact full-query match in name/synonyms        -> 20
          2. Multi-word phrase match (bigrams in name/sid)   -> 8 each
          3. Single-word overlap in name                     -> 3 each
          4. Synonym matching (best synonym)                 -> up to 8
          5. Description overlap                             -> 1 each
          6. Specificity bonus for short rare terms          -> 5 each
          7. Domain / collection affinity                    -> 2 each
          8. Penalty for irrelevant extra name words         -> -0.5 each
        """
        score = 0.0
        name_lower = series.name.lower()
        desc_lower = (series.description or "").lower()
        sid_lower = series.series_id.lower().replace("_", " ")
        collection_lower = (series.collection_name or "").lower()

        # Build word sets
        query_words = {_clean(w) for w in query.split()} - _STOP_WORDS - {""}
        name_words = {_clean(w) for w in name_lower.split()} - _STOP_WORDS - {""}
        desc_words = {_clean(w) for w in desc_lower.split()} - _STOP_WORDS - {""}

        if not query_words:
            return 0.0

        # ── 1. Exact full-query match ──────────────────────────────────
        # Normalize both to sorted content words for flexible matching
        q_content = " ".join(sorted(query_words))
        n_content = " ".join(sorted(name_words))
        if q_content and q_content == n_content:
            score += 20.0
        elif query in name_lower:
            score += 15.0
        elif query in sid_lower:
            score += 12.0

        # ── 2. Multi-word phrase matching (bigrams) ────────────────────
        q_list = [_clean(w) for w in query.split()
                  if _clean(w) not in _STOP_WORDS and _clean(w)]
        if len(q_list) >= 2:
            for i in range(len(q_list) - 1):
                bigram = f"{q_list[i]} {q_list[i+1]}"
                # Check name and series_id for this bigram
                if bigram in name_lower or bigram in sid_lower:
                    score += 8.0

        # ── 3. Single-word overlap in name ─────────────────────────────
        name_overlap = query_words & name_words
        score += len(name_overlap) * 3.0

        # ── 4. Synonym matching — take BEST synonym ────────────────────
        # Exact synonym match (full query = synonym) is a very strong signal (12pt).
        try:
            synonyms = json.loads(series.synonyms or "[]")
            best_syn_score = 0.0
            for syn in synonyms:
                syn_lower = syn.lower().strip()
                # Full query contained in synonym or vice versa
                if query in syn_lower or syn_lower in query:
                    best_syn_score = max(best_syn_score, 12.0)
                    break
                # Word overlap
                syn_words = {_clean(w) for w in syn_lower.split()} - _STOP_WORDS - {""}
                syn_overlap = query_words & syn_words
                if syn_overlap:
                    best_syn_score = max(best_syn_score, len(syn_overlap) * 4.0)
            score += best_syn_score
        except (json.JSONDecodeError, TypeError):
            pass

        # ── 5. Description word overlap ────────────────────────────────
        desc_overlap = query_words & desc_words
        score += len(desc_overlap) * 1.0

        # ── 6. Specificity bonus for known financial abbreviations ─────
        # Only specific alphanumeric codes get this bonus, NOT common words
        # like "oil", "bank", etc. that appear in many series.
        _SPECIFIC_TERMS = {
            "m1", "m2", "m3", "cpi", "gdp", "npl", "roe", "roa",
            "car", "ldr", "bop", "wti", "sdr", "sofr",
        }
        for qw in query_words:
            if qw in _SPECIFIC_TERMS and qw in name_words:
                score += 5.0

        # ── 7. Domain / collection affinity ────────────────────────────
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            is_match = (
                (series.domain or "").lower() == domain
                or domain in collection_lower
            )
            if is_match:
                for kw in keywords:
                    if kw in query:
                        score += 2.0

        # Also boost if query mentions collection name directly (e.g. "SAMA")
        if collection_lower and collection_lower != "all-databases":
            for cw in collection_lower.split():
                if len(cw) > 2 and cw in query:
                    score += 3.0

        # ── 8. Penalty for irrelevant extra name words ─────────────────
        # "Reserves To Deposits" matching query "reserves" should score lower
        # than "Total Reserves" because "deposits" is extra noise.
        extra_name_words = name_words - query_words
        if name_overlap and extra_name_words:
            score -= len(extra_name_words) * 0.5

        return max(score, 0.0)

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
