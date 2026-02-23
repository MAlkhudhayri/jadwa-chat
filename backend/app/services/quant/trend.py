"""Trend & Momentum — compute indicators and classify signals for each series.

Every public function is an async callable that returns a plain dict (agent-ready).
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional, List

from sqlalchemy import select, delete, func

from app.core.database import get_session_factory
from app.models.timeseries import Observation, SeriesCatalog
from app.models.signals import SignalSnapshot

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_div(num: float, denom: float) -> Optional[float]:
    """Divide with zero guard; returns None if denom is 0."""
    if denom == 0:
        return None
    return num / denom


def _pct_change(current: float, previous: float) -> Optional[float]:
    """Percentage change using abs(previous) as denominator."""
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def _mean(values: List[float]) -> float:
    return sum(values) / len(values)


def _std(values: List[float]) -> float:
    m = _mean(values)
    return (sum((x - m) ** 2 for x in values) / len(values)) ** 0.5


def _ols_slope_normalised(values: List[float]) -> Optional[float]:
    """OLS slope of values on [0..n-1], divided by mean(values)."""
    n = len(values)
    if n < 2:
        return None
    m = _mean(values)
    if m == 0:
        return None
    x_mean = (n - 1) / 2
    numer = sum((i - x_mean) * (v - m) for i, v in enumerate(values))
    denom = sum((i - x_mean) ** 2 for i in range(n))
    if denom == 0:
        return None
    slope = numer / denom
    return slope / abs(m)


def _percentile_rank(value: float, values: List[float]) -> float:
    """Rank of value within values, scaled 0–100."""
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    n = len(values)
    return (below + 0.5 * equal) / n * 100


def _classify_signal(
    mom_pct: Optional[float],
    yoy_pct: Optional[float],
    z_score: Optional[float],
) -> Optional[str]:
    """Classify signal — first match wins."""
    if mom_pct is None or yoy_pct is None or z_score is None:
        return None

    # 1. reversal_up
    if mom_pct > 0 and yoy_pct < -5:
        return "reversal_up"
    # 2. reversal_down
    if mom_pct < 0 and yoy_pct > 5:
        return "reversal_down"
    # 3. strong_up
    if z_score > 1.5 and mom_pct > 0 and yoy_pct > 5:
        return "strong_up"
    # 4. strong_down
    if z_score < -1.5 and mom_pct < 0 and yoy_pct < -5:
        return "strong_down"
    # 5. moderate_up
    if mom_pct > 0 and yoy_pct > 0:
        return "moderate_up"
    # 6. moderate_down
    if mom_pct < 0 and yoy_pct < 0:
        return "moderate_down"
    # 7. stable
    return "stable"


# ── Core computation ─────────────────────────────────────────────────────────

async def compute_series_signals(series_id: str) -> int:
    """Compute all indicators for one series. Write to signal_snapshots.

    Returns number of snapshots written.
    Idempotent: overwrites existing snapshots for same (series_id, date).
    """
    factory = await get_session_factory()
    session = factory()
    try:
        # Load observations sorted by date
        result = await session.execute(
            select(Observation)
            .where(Observation.series_id == series_id)
            .where(Observation.value.isnot(None))
            .order_by(Observation.date)
        )
        observations = list(result.scalars().all())

        if len(observations) < 2:
            return 0

        values = [o.value for o in observations]
        dates = [o.date for o in observations]
        n = len(values)

        # Delete existing snapshots for this series (idempotent)
        await session.execute(
            delete(SignalSnapshot).where(SignalSnapshot.series_id == series_id)
        )

        snapshots_written = 0

        for i in range(n):
            v = values[i]
            d = dates[i]

            # MoM %
            mom = _pct_change(v, values[i - 1]) if i >= 1 else None
            # QoQ %
            qoq = _pct_change(v, values[i - 3]) if i >= 3 else None
            # YoY %
            yoy = _pct_change(v, values[i - 12]) if i >= 12 else None

            # Z-score (12m)
            z_score = None
            if i >= 11:
                window = values[i - 11: i + 1]
                s = _std(window)
                if s > 0:
                    z_score = (v - _mean(window)) / s

            # Percentile (36m)
            pct_36 = None
            if i >= 11:
                lookback = max(0, i - 35)
                window_36 = values[lookback: i + 1]
                pct_36 = _percentile_rank(v, window_36)

            # SMA-6
            sma6 = _mean(values[i - 5: i + 1]) if i >= 5 else None

            # SMA-12
            sma12 = _mean(values[i - 11: i + 1]) if i >= 11 else None

            # Trend slope (12m)
            slope = None
            if i >= 11:
                slope = _ols_slope_normalised(values[i - 11: i + 1])

            # Signal classification
            signal = _classify_signal(mom, yoy, z_score)

            snap = SignalSnapshot(
                series_id=series_id,
                date=d,
                value=v,
                mom_pct=round(mom, 4) if mom is not None else None,
                qoq_pct=round(qoq, 4) if qoq is not None else None,
                yoy_pct=round(yoy, 4) if yoy is not None else None,
                z_score_12m=round(z_score, 4) if z_score is not None else None,
                percentile_36m=round(pct_36, 2) if pct_36 is not None else None,
                sma_6=round(sma6, 4) if sma6 is not None else None,
                sma_12=round(sma12, 4) if sma12 is not None else None,
                trend_slope=round(slope, 6) if slope is not None else None,
                signal=signal,
            )
            session.add(snap)
            snapshots_written += 1

        await session.commit()
        return snapshots_written

    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def compute_all_signals() -> dict:
    """Run compute_series_signals for every series with >= 12 observations.

    Returns:
        Dict mapping series_id → number of snapshots written.
    """
    factory = await get_session_factory()
    session = factory()
    try:
        # Find series with >= 12 observations
        result = await session.execute(
            select(Observation.series_id, func.count().label("cnt"))
            .where(Observation.value.isnot(None))
            .group_by(Observation.series_id)
            .having(func.count() >= 12)
        )
        series_list = [row[0] for row in result.all()]
    finally:
        await session.close()

    counts = {}
    for sid in series_list:
        try:
            count = await compute_series_signals(sid)
            counts[sid] = count
        except Exception as e:
            logger.warning(f"Signal computation failed for {sid}: {e}")
            counts[sid] = 0

    logger.info(f"Computed signals for {len(counts)} series")
    return counts


# ── Query functions (agent-callable) ─────────────────────────────────────────

async def get_series_signal(series_id: str) -> dict:
    """Get the full signal analysis for a specific series.

    Args:
        series_id: The series identifier.

    Returns:
        Dict with current value, MoM/QoQ/YoY change, z-score, percentile,
        signal classification, trend_slope, and last 24 months of history.
    """
    factory = await get_session_factory()
    session = factory()
    try:
        # Get series metadata
        meta_result = await session.execute(
            select(SeriesCatalog).where(SeriesCatalog.series_id == series_id)
        )
        meta = meta_result.scalar()
        if not meta:
            return {"error": f"Series '{series_id}' not found"}

        # Get latest 24 snapshots
        result = await session.execute(
            select(SignalSnapshot)
            .where(SignalSnapshot.series_id == series_id)
            .order_by(SignalSnapshot.date.desc())
            .limit(24)
        )
        snapshots = list(result.scalars().all())

        if not snapshots:
            return {
                "series_id": series_id,
                "name": meta.name,
                "unit": meta.unit,
                "error": "No signal data computed yet",
            }

        latest = snapshots[0]

        return {
            "series_id": series_id,
            "name": meta.name,
            "domain": meta.domain,
            "unit": meta.unit,
            "source": meta.source,
            "latest": {
                "date": latest.date.isoformat(),
                "value": latest.value,
                "signal": latest.signal,
                "mom_pct": latest.mom_pct,
                "qoq_pct": latest.qoq_pct,
                "yoy_pct": latest.yoy_pct,
                "z_score_12m": latest.z_score_12m,
                "percentile_36m": latest.percentile_36m,
                "sma_6": latest.sma_6,
                "sma_12": latest.sma_12,
                "trend_slope": latest.trend_slope,
            },
            "history": [
                {
                    "date": s.date.isoformat(),
                    "value": s.value,
                    "signal": s.signal,
                    "mom_pct": s.mom_pct,
                    "yoy_pct": s.yoy_pct,
                    "z_score_12m": s.z_score_12m,
                }
                for s in reversed(snapshots)
            ],
        }
    finally:
        await session.close()


async def get_latest_signal(series_id: str) -> dict:
    """Get only the latest signal snapshot for a series.

    Args:
        series_id: The series identifier.

    Returns:
        Dict with the latest signal snapshot data.
    """
    factory = await get_session_factory()
    session = factory()
    try:
        result = await session.execute(
            select(SignalSnapshot)
            .where(SignalSnapshot.series_id == series_id)
            .order_by(SignalSnapshot.date.desc())
            .limit(1)
        )
        snap = result.scalar()
        if not snap:
            return {"error": f"No signal data for '{series_id}'"}

        return {
            "series_id": series_id,
            "date": snap.date.isoformat(),
            "value": snap.value,
            "signal": snap.signal,
            "mom_pct": snap.mom_pct,
            "qoq_pct": snap.qoq_pct,
            "yoy_pct": snap.yoy_pct,
            "z_score_12m": snap.z_score_12m,
            "percentile_36m": snap.percentile_36m,
            "sma_6": snap.sma_6,
            "sma_12": snap.sma_12,
            "trend_slope": snap.trend_slope,
        }
    finally:
        await session.close()



