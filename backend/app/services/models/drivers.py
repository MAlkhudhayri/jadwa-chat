"""Elastic Net driver attribution for scorecard domains.

Identifies the top drivers (most influential series) for each domain
scorecard using Elastic Net regularisation. Produces stable coefficients
and a ranked list of "what moves this domain score".
"""

import logging
import time
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)


def load_elastic_net() -> Any:
    """Validate sklearn is available."""
    try:
        from sklearn.linear_model import ElasticNetCV  # noqa: F401
        return {"engine": "sklearn", "l1_ratio": [0.1, 0.5, 0.7, 0.9, 0.95]}
    except ImportError:
        raise ImportError("scikit-learn is required: pip install scikit-learn")


def compute_drivers(
    target: np.ndarray,
    features: np.ndarray,
    feature_names: List[str],
    top_k: int = 5,
) -> Dict[str, Any]:
    """Fit Elastic Net and return top-k driver attributions.

    Args:
        target: 1D array — the domain score over time.
        features: 2D array (n_time, n_features) — component series values.
        feature_names: Names corresponding to feature columns.
        top_k: Number of top drivers to return.

    Returns:
        Dict with ``drivers`` (ranked list), ``r_squared``, ``coefficients``.
    """
    from sklearn.linear_model import ElasticNetCV
    from sklearn.preprocessing import StandardScaler
    from app.services.models.registry import get_registry

    t0 = time.time()

    if len(target) < 12 or features.shape[0] < 12:
        return {"drivers": [], "r_squared": None, "error": "Insufficient data (need 12+ observations)"}

    # Standardise
    scaler = StandardScaler()
    X = scaler.fit_transform(features)
    y = target.copy()

    # Handle NaN
    mask = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
    X, y = X[mask], y[mask]

    if len(y) < 10:
        return {"drivers": [], "r_squared": None, "error": "Too few valid observations"}

    model = ElasticNetCV(
        l1_ratio=[0.1, 0.5, 0.7, 0.9, 0.95],
        cv=min(5, len(y)),
        max_iter=5000,
        random_state=42,
    )
    model.fit(X, y)

    coefs = model.coef_
    r2 = float(model.score(X, y))

    # Rank by absolute coefficient
    abs_coefs = np.abs(coefs)
    ranked_indices = np.argsort(abs_coefs)[::-1]

    drivers = []
    for idx in ranked_indices[:top_k]:
        if abs_coefs[idx] < 1e-6:
            break
        drivers.append({
            "feature": feature_names[idx] if idx < len(feature_names) else f"feat_{idx}",
            "coefficient": float(coefs[idx]),
            "abs_importance": float(abs_coefs[idx]),
            "direction": "positive" if coefs[idx] > 0 else "negative",
        })

    elapsed = int((time.time() - t0) * 1000)
    get_registry().record_run("elastic_net", elapsed)
    logger.info(f"ElasticNet drivers: R²={r2:.3f}, top {len(drivers)} features in {elapsed}ms")

    return {
        "drivers": drivers,
        "r_squared": r2,
        "alpha": float(model.alpha_),
        "l1_ratio": float(model.l1_ratio_),
        "n_features": len(feature_names),
        "n_observations": int(len(y)),
    }
