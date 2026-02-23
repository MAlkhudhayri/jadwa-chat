"""Model compute pipeline — runs change-point, isolation forest, and drivers
on the latest signal data. Called via POST /signals/models/compute or
automatically after the signal pipeline finishes.
"""

import logging
import time
from typing import Dict, Any, List

import numpy as np
from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.timeseries import Observation

logger = logging.getLogger(__name__)


async def _fetch_series_values() -> Dict[str, List[float]]:
    """Fetch ordered observation values for all series with enough data."""
    from sqlalchemy import func as sqlfunc

    factory = await get_session_factory()
    session = factory()
    try:
        # Find series with >= 12 observations via GROUP BY
        count_rows = await session.execute(
            select(Observation.series_id, sqlfunc.count(Observation.value))
            .where(Observation.value.isnot(None))
            .group_by(Observation.series_id)
            .having(sqlfunc.count(Observation.value) >= 12)
        )
        series_ids = [r[0] for r in count_rows]

        series_data: Dict[str, List[float]] = {}
        for sid in series_ids:
            rows = await session.execute(
                select(Observation.value)
                .where(Observation.series_id == sid, Observation.value.isnot(None))
                .order_by(Observation.date.asc())
            )
            values = [r[0] for r in rows]
            if len(values) >= 12:
                series_data[sid] = values

        return series_data
    finally:
        await session.close()


async def _fetch_domain_data() -> Dict[str, Any]:
    """Fetch scorecard domain targets and component features for driver analysis."""
    from app.services.quant.scorecard import get_all_scorecards
    scorecards = await get_all_scorecards()

    return scorecards


async def run_model_compute() -> Dict[str, Any]:
    """Run all ML model computations on latest data."""
    from app.services.models.registry import get_registry

    t0 = time.time()
    registry = get_registry()
    results: Dict[str, Any] = {}

    # Fetch data once
    series_data = await _fetch_series_values()
    logger.info(f"Model compute: fetched {len(series_data)} series")

    # 1. Change-point detection
    try:
        registry.get_model("changepoint")
        from app.services.models.changepoint import detect_changepoints_batch
        cp_results = detect_changepoints_batch(series_data)
        series_with_changes = sum(1 for r in cp_results.values() if r.get("n_segments", 1) > 1)
        results["changepoint"] = {
            "status": "success",
            "series_analyzed": len(cp_results),
            "series_with_changepoints": series_with_changes,
        }
    except Exception as e:
        logger.warning(f"Change-point compute failed: {e}")
        results["changepoint"] = {"status": "error", "error": str(e)[:200]}

    # 2. Isolation Forest
    try:
        registry.get_model("isolation_forest")
        from app.services.models.isolation_forest import build_feature_matrix, train_and_score
        feature_matrix, series_ids = build_feature_matrix(series_data)
        if feature_matrix.shape[0] > 0:
            iso_results = train_and_score(feature_matrix, series_ids)
            results["isolation_forest"] = {
                "status": "success",
                "rows_analyzed": iso_results["n_total"],
                "anomalies_detected": iso_results["n_anomalies"],
                "series_affected": len(iso_results["series_anomalies"]),
            }
        else:
            results["isolation_forest"] = {"status": "skipped", "reason": "No features built"}
    except Exception as e:
        logger.warning(f"Isolation Forest compute failed: {e}")
        results["isolation_forest"] = {"status": "error", "error": str(e)[:200]}

    # 3. Elastic Net drivers (per-domain if possible)
    try:
        registry.get_model("elastic_net")
        from app.services.models.drivers import compute_drivers

        # Build a simple proxy: use each series' latest values as features,
        # predict aggregate score trend from component series
        all_sids = list(series_data.keys())
        if len(all_sids) >= 5:
            min_len = min(len(v) for v in series_data.values())
            min_len = min(min_len, 36)  # cap at 36 months
            feature_names = all_sids[:20]  # top 20 series
            features = np.column_stack([
                np.array(series_data[sid][-min_len:]) for sid in feature_names
            ])
            # Use mean of all series as proxy target
            target = np.mean(features, axis=1)

            driver_result = compute_drivers(target, features, feature_names)
            results["elastic_net"] = {
                "status": "success",
                "top_drivers": driver_result.get("drivers", [])[:5],
                "r_squared": driver_result.get("r_squared"),
            }
        else:
            results["elastic_net"] = {"status": "skipped", "reason": "Too few series"}
    except Exception as e:
        logger.warning(f"Elastic Net compute failed: {e}")
        results["elastic_net"] = {"status": "error", "error": str(e)[:200]}

    elapsed = int((time.time() - t0) * 1000)
    results["duration_ms"] = elapsed
    results["series_count"] = len(series_data)
    logger.info(f"Model compute pipeline finished in {elapsed}ms")

    return results
