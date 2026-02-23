"""Cross-encoder reranker for RAG top-k reranking.

Uses sentence-transformers cross-encoder (MiniLM-L-6, ~22 MB) to rerank
the top-N chunks retrieved from Qdrant, giving a large quality lift with
minimal compute overhead.
"""

import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_model = None


def load_reranker() -> Any:
    """Load the cross-encoder model. Called once at startup."""
    global _model
    try:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", max_length=512)
        logger.info("Reranker loaded: cross-encoder/ms-marco-MiniLM-L-6-v2")
        return _model
    except ImportError:
        logger.warning("sentence-transformers not installed — reranker unavailable")
        raise
    except Exception as e:
        logger.error(f"Reranker load failed: {e}")
        raise


def rerank(query: str, documents: List[Dict], top_k: int = 10) -> List[Dict]:
    """Rerank retrieved documents using the cross-encoder.

    Args:
        query: The user's search query.
        documents: List of dicts with at least a ``content`` key.
        top_k: Number of top results to return after reranking.

    Returns:
        Reranked list (highest relevance first), trimmed to ``top_k``.
    """
    from app.services.models.registry import get_registry

    if not documents:
        return documents

    registry = get_registry()
    model = registry.get_model("reranker")

    t0 = time.time()

    pairs = [(query, doc.get("content", "")[:512]) for doc in documents]
    scores = model.predict(pairs)

    for doc, score in zip(documents, scores):
        doc["rerank_score"] = float(score)

    reranked = sorted(documents, key=lambda d: d.get("rerank_score", 0), reverse=True)

    elapsed = int((time.time() - t0) * 1000)
    registry.record_run("reranker", elapsed)
    logger.debug(f"Reranked {len(documents)} docs in {elapsed}ms, returning top {top_k}")

    return reranked[:top_k]
