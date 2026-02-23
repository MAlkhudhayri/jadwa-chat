"""Change-point detection using PELT (ruptures).

Detects structural regime shifts in time series — often more valuable
than point forecasts for PE analysts ("something fundamental changed").
"""

import logging
import time
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


def load_changepoint() -> Dict[str, Any]:
    """Validate that ruptures is available. Returns config dict."""
    try:
        import ruptures  # noqa: F401
        return {"engine": "ruptures", "method": "Pelt", "penalty": "bic"}
    except ImportError:
        raise ImportError("ruptures package is required: pip install ruptures")


def detect_changepoints(
    values: List[float],
    min_size: int = 6,
    penalty: str = "bic",
) -> Dict[str, Any]:
    """Run PELT change-point detection on a single time series.

    Args:
        values: Ordered numeric observations (oldest first).
        min_size: Minimum segment length.
        penalty: Penalty method — "bic", "aic", or a float.

    Returns:
        Dict with ``changepoints`` (list of indices), ``n_segments``,
        ``segments`` (start/end/mean per segment).
    """
    import ruptures

    if len(values) < min_size * 2:
        return {"changepoints": [], "n_segments": 1, "segments": []}

    signal = np.array(values, dtype=float)

    algo = ruptures.Pelt(model="rbf", min_size=min_size).fit(signal)
    breakpoints = algo.predict(pen=_resolve_penalty(penalty, signal))

    # ruptures returns breakpoint indices (1-indexed end of segment)
    # Last element is always len(signal), remove it
    if breakpoints and breakpoints[-1] == len(signal):
        breakpoints = breakpoints[:-1]

    segments = []
    prev = 0
    for bp in breakpoints + [len(signal)]:
        seg_values = values[prev:bp]
        if seg_values:
            segments.append({
                "start_idx": prev,
                "end_idx": bp - 1,
                "length": len(seg_values),
                "mean": float(np.mean(seg_values)),
                "std": float(np.std(seg_values)),
            })
        prev = bp

    return {
        "changepoints": breakpoints,
        "n_segments": len(segments),
        "segments": segments,
    }


def detect_changepoints_batch(
    series_map: Dict[str, List[float]],
    min_size: int = 6,
) -> Dict[str, Dict]:
    """Run change-point detection on multiple series.

    Args:
        series_map: {series_id: [values]}.

    Returns:
        {series_id: changepoint_result}.
    """
    from app.services.models.registry import get_registry
    t0 = time.time()

    results = {}
    for sid, values in series_map.items():
        try:
            results[sid] = detect_changepoints(values, min_size=min_size)
        except Exception as e:
            logger.warning(f"Changepoint failed for {sid}: {e}")
            results[sid] = {"changepoints": [], "n_segments": 1, "segments": [], "error": str(e)}

    elapsed = int((time.time() - t0) * 1000)
    get_registry().record_run("changepoint", elapsed)
    logger.info(f"Changepoint detection: {len(series_map)} series in {elapsed}ms")
    return results


def _resolve_penalty(penalty: str, signal: np.ndarray) -> float:
    """Convert penalty name to numeric value."""
    n = len(signal)
    if penalty == "bic":
        return np.log(n) * signal.var()
    elif penalty == "aic":
        return 2 * signal.var()
    else:
        try:
            return float(penalty)
        except ValueError:
            return np.log(n) * signal.var()
