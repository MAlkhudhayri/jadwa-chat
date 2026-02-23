"""Isolation Forest anomaly scorer on engineered features.

Trains on cross-series engineered features (returns, rolling z-scores,
volatility, trend slope) and scores each observation for anomaly likelihood.
CPU-only, fast, works well on small macro datasets.
"""

import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def load_isolation_forest() -> Any:
    """Validate sklearn is available and return a factory config."""
    try:
        from sklearn.ensemble import IsolationForest  # noqa: F401
        return {"engine": "sklearn", "contamination": 0.05, "n_estimators": 100}
    except ImportError:
        raise ImportError("scikit-learn is required: pip install scikit-learn")


def train_and_score(
    feature_matrix: np.ndarray,
    series_ids: List[str],
    contamination: float = 0.05,
) -> Dict[str, Any]:
    """Train IsolationForest on feature matrix and return anomaly scores.

    Args:
        feature_matrix: 2D array (n_observations, n_features).
        series_ids: Parallel list of series identifiers per row.
        contamination: Expected proportion of anomalies.

    Returns:
        Dict with ``scores`` (per-row anomaly score, lower = more anomalous),
        ``labels`` (-1 = anomaly, 1 = normal), and ``anomaly_indices``.
    """
    from sklearn.ensemble import IsolationForest
    from app.services.models.registry import get_registry

    t0 = time.time()

    if feature_matrix.shape[0] < 10:
        return {"scores": [], "labels": [], "anomaly_indices": [], "series_anomalies": {}}

    # Replace NaN with column medians
    col_medians = np.nanmedian(feature_matrix, axis=0)
    for col in range(feature_matrix.shape[1]):
        mask = np.isnan(feature_matrix[:, col])
        feature_matrix[mask, col] = col_medians[col]

    model = IsolationForest(
        n_estimators=100,
        contamination=contamination,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(feature_matrix)

    scores = model.decision_function(feature_matrix)
    labels = model.predict(feature_matrix)

    anomaly_indices = [i for i, l in enumerate(labels) if l == -1]
    series_anomalies: Dict[str, List[int]] = {}
    for idx in anomaly_indices:
        sid = series_ids[idx] if idx < len(series_ids) else "unknown"
        series_anomalies.setdefault(sid, []).append(idx)

    elapsed = int((time.time() - t0) * 1000)
    get_registry().record_run("isolation_forest", elapsed)
    logger.info(
        f"IsolationForest: {feature_matrix.shape[0]} rows, "
        f"{len(anomaly_indices)} anomalies in {elapsed}ms"
    )

    return {
        "scores": scores.tolist(),
        "labels": labels.tolist(),
        "anomaly_indices": anomaly_indices,
        "series_anomalies": series_anomalies,
        "n_total": feature_matrix.shape[0],
        "n_anomalies": len(anomaly_indices),
    }


def build_feature_matrix(
    series_data: Dict[str, List[float]],
) -> tuple:
    """Build an engineered feature matrix from raw series values.

    Features per observation: [value, mom_return, 3m_rolling_mean,
    3m_rolling_std, z_score, trend_slope_proxy].

    Returns:
        (feature_matrix: np.ndarray, series_ids: List[str])
    """
    rows = []
    ids = []

    for sid, values in series_data.items():
        if len(values) < 6:
            continue
        arr = np.array(values, dtype=float)
        for i in range(3, len(arr)):
            val = arr[i]
            mom = (arr[i] - arr[i - 1]) / abs(arr[i - 1]) if arr[i - 1] != 0 else 0
            window = arr[max(0, i - 3): i]
            rmean = float(np.mean(window))
            rstd = float(np.std(window)) if len(window) > 1 else 0
            z = (val - rmean) / rstd if rstd > 0 else 0
            slope = (arr[i] - arr[max(0, i - 3)]) / 3.0

            rows.append([val, mom, rmean, rstd, z, slope])
            ids.append(sid)

    if not rows:
        return np.empty((0, 6)), []

    return np.array(rows, dtype=float), ids
