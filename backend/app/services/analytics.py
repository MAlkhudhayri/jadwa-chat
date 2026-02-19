"""Analytics tool layer — safe, pre-defined functions for financial data."""

import json
import logging
import time
from datetime import date, datetime, timezone
from typing import Optional, List

from sqlalchemy import select, func, desc

from app.core.database import get_session_factory
from app.models.timeseries import Observation, SeriesCatalog, ToolCallLog

logger = logging.getLogger(__name__)


async def _log_tool_call(tool: str, series_id: str = "", params: dict = None,
                         result_summary: str = "", duration_ms: int = 0):
    factory = await get_session_factory()
    session = factory()
    try:
        log = ToolCallLog(
            tool_name=tool,
            series_id=series_id,
            params=json.dumps(params or {}),
            result_summary=result_summary[:500],
            duration_ms=duration_ms,
        )
        session.add(log)
        await session.commit()
    except Exception:
        pass
    finally:
        await session.close()


async def _get_series_meta(series_id: str) -> Optional[dict]:
    factory = await get_session_factory()
    session = factory()
    try:
        result = await session.execute(
            select(SeriesCatalog).where(SeriesCatalog.series_id == series_id)
        )
        s = result.scalar()
        if s:
            return {
                "series_id": s.series_id,
                "name": s.name,
                "unit": s.unit,
                "source": s.source,
                "source_url": s.source_url,
                "domain": s.domain,
            }
        return None
    finally:
        await session.close()


async def latest(series_id: str) -> dict:
    """Get the most recent observation for a series."""
    t0 = time.time()
    meta = await _get_series_meta(series_id)
    if not meta:
        return {"error": f"Series '{series_id}' not found in catalog"}

    factory = await get_session_factory()
    session = factory()
    try:
        result = await session.execute(
            select(Observation)
            .where(Observation.series_id == series_id)
            .order_by(desc(Observation.date))
            .limit(1)
        )
        obs = result.scalar()
        if not obs:
            return {"error": f"No data for series '{series_id}'", **meta}

        staleness = (date.today() - obs.date).days
        is_forecast = obs.date > date.today()

        result_data = {
            **meta,
            "date": obs.date.isoformat(),
            "value": obs.value,
            "is_forecast": is_forecast,
            "staleness_days": staleness,
        }

        duration_ms = int((time.time() - t0) * 1000)
        await _log_tool_call("latest", series_id, {}, str(result_data), duration_ms)
        return result_data
    finally:
        await session.close()


async def get_series(series_id: str, start: Optional[str] = None,
                     end: Optional[str] = None) -> dict:
    """Get time series data with optional date range."""
    t0 = time.time()
    meta = await _get_series_meta(series_id)
    if not meta:
        return {"error": f"Series '{series_id}' not found in catalog"}

    factory = await get_session_factory()
    session = factory()
    try:
        stmt = select(Observation).where(Observation.series_id == series_id)

        if start:
            stmt = stmt.where(Observation.date >= date.fromisoformat(start))
        if end:
            stmt = stmt.where(Observation.date <= date.fromisoformat(end))

        stmt = stmt.order_by(Observation.date)
        result = await session.execute(stmt)
        observations = result.scalars().all()

        obs_list = [
            {"date": o.date.isoformat(), "value": o.value}
            for o in observations
        ]

        staleness = (date.today() - observations[-1].date).days if observations else None

        result_data = {
            **meta,
            "observations": obs_list,
            "count": len(obs_list),
            "staleness_days": staleness,
        }

        duration_ms = int((time.time() - t0) * 1000)
        await _log_tool_call("get_series", series_id,
                             {"start": start, "end": end},
                             f"{len(obs_list)} observations", duration_ms)
        return result_data
    finally:
        await session.close()


async def change(series_id: str, method: str = "MoM") -> dict:
    """Calculate period-over-period change (MoM, YoY, QoQ)."""
    t0 = time.time()
    meta = await _get_series_meta(series_id)
    if not meta:
        return {"error": f"Series '{series_id}' not found"}

    offsets = {"MoM": 1, "QoQ": 3, "YoY": 12}
    offset = offsets.get(method, 1)

    factory = await get_session_factory()
    session = factory()
    try:
        result = await session.execute(
            select(Observation)
            .where(Observation.series_id == series_id)
            .order_by(desc(Observation.date))
            .limit(offset + 1)
        )
        obs = list(result.scalars().all())

        if len(obs) < offset + 1:
            return {"error": f"Not enough data for {method} calculation", **meta}

        current = obs[0]
        previous = obs[offset]

        change_abs = (current.value - previous.value) if current.value and previous.value else None
        change_pct = (change_abs / abs(previous.value) * 100) if change_abs and previous.value else None

        result_data = {
            **meta,
            "method": method,
            "current_date": current.date.isoformat(),
            "current_value": current.value,
            "previous_date": previous.date.isoformat(),
            "previous_value": previous.value,
            "change_absolute": round(change_abs, 4) if change_abs else None,
            "change_percent": round(change_pct, 2) if change_pct else None,
        }

        duration_ms = int((time.time() - t0) * 1000)
        await _log_tool_call("change", series_id, {"method": method},
                             str(result_data), duration_ms)
        return result_data
    finally:
        await session.close()


async def rolling(series_id: str, window: int = 12,
                   method: str = "mean") -> dict:
    """Calculate rolling statistics for a series.

    Args:
        series_id: The series to analyze.
        window: Number of periods for the rolling window (default 12 months).
        method: One of 'mean', 'std', 'min', 'max'.
    """
    t0 = time.time()
    meta = await _get_series_meta(series_id)
    if not meta:
        return {"error": f"Series '{series_id}' not found in catalog"}

    if method not in ("mean", "std", "min", "max"):
        return {"error": f"Invalid method '{method}'. Use: mean, std, min, max"}

    factory = await get_session_factory()
    session = factory()
    try:
        result = await session.execute(
            select(Observation)
            .where(Observation.series_id == series_id)
            .order_by(Observation.date)
        )
        observations = list(result.scalars().all())

        if len(observations) < window:
            return {
                "error": f"Not enough data for {window}-period rolling window "
                         f"(have {len(observations)} observations)",
                **meta,
            }

        # Compute rolling statistic
        values = [o.value for o in observations]
        rolling_values = []
        for i in range(window - 1, len(values)):
            w = values[i - window + 1:i + 1]
            w_clean = [v for v in w if v is not None]
            if not w_clean:
                rolling_values.append({"date": observations[i].date.isoformat(), "value": None})
                continue
            if method == "mean":
                stat = sum(w_clean) / len(w_clean)
            elif method == "std":
                m = sum(w_clean) / len(w_clean)
                stat = (sum((x - m) ** 2 for x in w_clean) / len(w_clean)) ** 0.5
            elif method == "min":
                stat = min(w_clean)
            elif method == "max":
                stat = max(w_clean)
            rolling_values.append({
                "date": observations[i].date.isoformat(),
                "value": round(stat, 4),
            })

        current = rolling_values[-1]["value"] if rolling_values else None
        latest_raw = values[-1]

        result_data = {
            **meta,
            "method": method,
            "window": window,
            "current_rolling_value": current,
            "current_raw_value": latest_raw,
            "latest_date": observations[-1].date.isoformat(),
            "observations": rolling_values[-24:],  # Last 24 data points
            "total_points": len(rolling_values),
        }

        duration_ms = int((time.time() - t0) * 1000)
        await _log_tool_call("rolling", series_id,
                             {"window": window, "method": method},
                             f"rolling {method} = {current}", duration_ms)
        return result_data
    finally:
        await session.close()


async def compare(series_a: str, series_b: str, window: int = 24) -> dict:
    """Compare two series: correlation, relative change, and recent trends.

    Args:
        series_a: First series ID.
        series_b: Second series ID.
        window: Number of overlapping periods to use (default 24 months).
    """
    t0 = time.time()
    meta_a = await _get_series_meta(series_a)
    meta_b = await _get_series_meta(series_b)
    if not meta_a:
        return {"error": f"Series '{series_a}' not found"}
    if not meta_b:
        return {"error": f"Series '{series_b}' not found"}

    factory = await get_session_factory()
    session = factory()
    try:
        # Get both series
        result_a = await session.execute(
            select(Observation)
            .where(Observation.series_id == series_a)
            .order_by(Observation.date)
        )
        obs_a = {o.date: o.value for o in result_a.scalars().all() if o.value is not None}

        result_b = await session.execute(
            select(Observation)
            .where(Observation.series_id == series_b)
            .order_by(Observation.date)
        )
        obs_b = {o.date: o.value for o in result_b.scalars().all() if o.value is not None}

        # Find overlapping dates
        common_dates = sorted(set(obs_a.keys()) & set(obs_b.keys()))
        if len(common_dates) < 3:
            return {
                "error": f"Not enough overlapping data (only {len(common_dates)} common dates)",
                "series_a": meta_a,
                "series_b": meta_b,
            }

        # Use last N overlapping points
        recent_dates = common_dates[-window:]
        vals_a = [obs_a[d] for d in recent_dates]
        vals_b = [obs_b[d] for d in recent_dates]

        # Pearson correlation
        n = len(vals_a)
        mean_a = sum(vals_a) / n
        mean_b = sum(vals_b) / n
        cov = sum((vals_a[i] - mean_a) * (vals_b[i] - mean_b) for i in range(n)) / n
        std_a = (sum((v - mean_a) ** 2 for v in vals_a) / n) ** 0.5
        std_b = (sum((v - mean_b) ** 2 for v in vals_b) / n) ** 0.5
        correlation = cov / (std_a * std_b) if std_a > 0 and std_b > 0 else 0.0

        # Direction labels
        def _direction(vals):
            if len(vals) < 2:
                return "stable"
            change = (vals[-1] - vals[0]) / abs(vals[0]) * 100 if vals[0] != 0 else 0
            if change > 5:
                return "increasing"
            elif change < -5:
                return "decreasing"
            return "stable"

        result_data = {
            "series_a": meta_a,
            "series_b": meta_b,
            "correlation": round(correlation, 3),
            "overlapping_periods": len(recent_dates),
            "date_range": {
                "start": recent_dates[0].isoformat(),
                "end": recent_dates[-1].isoformat(),
            },
            "series_a_trend": _direction(vals_a),
            "series_b_trend": _direction(vals_b),
            "series_a_latest": {"date": recent_dates[-1].isoformat(), "value": vals_a[-1]},
            "series_b_latest": {"date": recent_dates[-1].isoformat(), "value": vals_b[-1]},
        }

        # Interpret
        if abs(correlation) > 0.7:
            result_data["interpretation"] = f"Strong {'positive' if correlation > 0 else 'negative'} correlation ({correlation:.2f})"
        elif abs(correlation) > 0.4:
            result_data["interpretation"] = f"Moderate {'positive' if correlation > 0 else 'negative'} correlation ({correlation:.2f})"
        else:
            result_data["interpretation"] = f"Weak correlation ({correlation:.2f}) — these series move largely independently"

        duration_ms = int((time.time() - t0) * 1000)
        await _log_tool_call("compare", f"{series_a}:{series_b}",
                             {"window": window},
                             f"correlation={correlation:.3f}", duration_ms)
        return result_data
    finally:
        await session.close()


async def top_movers(domain: Optional[str] = None, period: str = "MoM",
                     limit: int = 5) -> dict:
    """Find the series with the biggest changes in a domain.

    Args:
        domain: Filter to a specific domain (oil, bop, fiscal, stability, banking).
                If None, checks all domains.
        period: 'MoM', 'QoQ', or 'YoY'.
        limit: Number of top movers to return.
    """
    t0 = time.time()
    factory = await get_session_factory()
    session = factory()
    try:
        # Get all series (optionally filtered by domain)
        stmt = select(SeriesCatalog)
        if domain:
            stmt = stmt.where(SeriesCatalog.domain == domain.lower())
        result = await session.execute(stmt)
        all_series = result.scalars().all()

        movers = []
        for s in all_series:
            change_result = await change(s.series_id, method=period)
            if "error" not in change_result and change_result.get("change_percent") is not None:
                movers.append({
                    "series_id": s.series_id,
                    "name": s.name,
                    "domain": s.domain,
                    "unit": s.unit,
                    "change_percent": change_result["change_percent"],
                    "change_absolute": change_result.get("change_absolute"),
                    "current_value": change_result["current_value"],
                    "current_date": change_result["current_date"],
                })

        # Sort by absolute percentage change
        movers.sort(key=lambda x: abs(x["change_percent"]), reverse=True)
        top = movers[:limit]

        result_data = {
            "domain": domain or "all",
            "period": period,
            "movers": top,
            "total_series_checked": len(all_series),
        }

        duration_ms = int((time.time() - t0) * 1000)
        await _log_tool_call("top_movers", domain or "all",
                             {"period": period, "limit": limit},
                             f"{len(top)} movers found", duration_ms)
        return result_data
    finally:
        await session.close()


async def freshness() -> List[dict]:
    """Check data freshness for all series with data."""
    factory = await get_session_factory()
    session = factory()
    try:
        result = await session.execute(
            select(
                Observation.series_id,
                func.max(Observation.date).label("latest_date"),
                func.count().label("obs_count"),
            ).group_by(Observation.series_id)
        )
        rows = result.all()

        items = []
        for row in rows:
            meta = await _get_series_meta(row.series_id)
            staleness = (date.today() - row.latest_date).days
            items.append({
                "series_id": row.series_id,
                "name": meta["name"] if meta else row.series_id,
                "latest_date": row.latest_date.isoformat(),
                "observation_count": row.obs_count,
                "staleness_days": staleness,
                "source": meta["source"] if meta else "unknown",
            })

        items.sort(key=lambda x: x["staleness_days"])
        return items
    finally:
        await session.close()

