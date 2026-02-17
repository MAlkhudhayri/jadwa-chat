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

