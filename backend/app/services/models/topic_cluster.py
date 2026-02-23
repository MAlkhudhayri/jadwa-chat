"""TF-IDF + KMeans topic clustering for document taxonomy.

Auto-tags uploaded document chunks into topic clusters (e.g. "monetary",
"oil", "banking") for better navigation and retrieval filtering.
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def load_topic_cluster() -> Dict[str, Any]:
    """Validate sklearn is available."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401
        from sklearn.cluster import KMeans  # noqa: F401
        return {"engine": "sklearn", "n_clusters": "auto", "max_features": 5000}
    except ImportError:
        raise ImportError("scikit-learn is required: pip install scikit-learn")


def cluster_documents(
    texts: List[str],
    n_clusters: Optional[int] = None,
    max_features: int = 5000,
) -> Dict[str, Any]:
    """Cluster a list of document texts into topic groups.

    Args:
        texts: List of document/chunk text strings.
        n_clusters: Number of clusters. If None, auto-selects (min(8, n//10)).
        max_features: Max TF-IDF vocabulary size.

    Returns:
        Dict with ``clusters`` (label per text), ``n_clusters``,
        ``cluster_keywords`` (top terms per cluster), ``cluster_sizes``.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.cluster import KMeans
    import numpy as np
    from app.services.models.registry import get_registry

    t0 = time.time()

    if len(texts) < 5:
        return {"clusters": [0] * len(texts), "n_clusters": 1, "cluster_keywords": {}, "error": "Too few documents"}

    if n_clusters is None:
        n_clusters = max(2, min(8, len(texts) // 10))

    n_clusters = min(n_clusters, len(texts))

    vectorizer = TfidfVectorizer(
        max_features=max_features,
        stop_words="english",
        min_df=2,
        max_df=0.95,
    )
    tfidf_matrix = vectorizer.fit_transform(texts)

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10, max_iter=300)
    labels = kmeans.fit_predict(tfidf_matrix)

    feature_names = vectorizer.get_feature_names_out()
    cluster_keywords = {}
    cluster_sizes = {}

    for cluster_id in range(n_clusters):
        center = kmeans.cluster_centers_[cluster_id]
        top_indices = center.argsort()[-8:][::-1]
        keywords = [feature_names[i] for i in top_indices if center[i] > 0]
        cluster_keywords[str(cluster_id)] = keywords
        cluster_sizes[str(cluster_id)] = int(np.sum(labels == cluster_id))

    elapsed = int((time.time() - t0) * 1000)
    get_registry().record_run("topic_cluster", elapsed)
    logger.info(f"Topic clustering: {len(texts)} docs → {n_clusters} clusters in {elapsed}ms")

    return {
        "clusters": labels.tolist(),
        "n_clusters": n_clusters,
        "cluster_keywords": cluster_keywords,
        "cluster_sizes": cluster_sizes,
    }
