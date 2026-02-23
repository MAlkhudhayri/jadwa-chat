"""Anomaly Detection — 4 detectors: bollinger_break, trend_break, streak, level_shift.

Every public function is an async callable that returns a plain dict (agent-ready).
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional, List

from sqlalchemy import select, func, update

from app.core.database import get_session_factory
from app.models.timeseries import Observation, SeriesCatalog
from app.models.signals import SignalSnapshot, AnomalyAlert

logger = logging.getLogger(__name__)


# ── Domain-aware Bollinger width ──────────────────────────────────────────────

def _get_bollinger_width(series_id: str) -> float:
    """Return domain-aware Bollinger band width."""
    sid = series_id.lower()
    if sid.startswith("oil_markets__") or sid.startswith("ksa_oil_production__"):
        return 2.5
    if sid.startswith("sama__") and sid.endswith("_pct"):
        return 1.5
    return 2.0


def _severity_from_z(z: float, band_width: float) -> Optional[str]:
    """Determine severity from z-score relative to band width."""
    abs_z = abs(z)
    if abs_z > 3.0:
        return "critical"
    if abs_z > band_width:
        return "warning"
    return None


def _mean(values: List[float]) -> float:
    return sum(values) / len(values)


def _std(values: List[float]) -> float:
    m = _mean(values)
    return (sum((x - m) ** 2 for x in values) / len(values)) ** 0.5


# ── Detector 1: Bollinger Band Break ─────────────────────────────────────────

async def _detect_bollinger_break(
    series_id: str,
    series_name: str,
    unit: str,
    values: List[float],
    dates: List[date],
) -> Optional[dict]:
    """Check if latest value is outside Bollinger Bands."""
    if len(values) < 20:
        return None

    window = values[-20:]
    sma = _mean(window)
    std = _std(window)
    if std == 0:
        return None

    latest = values[-1]
    latest_date = dates[-1]
    width = _get_bollinger_width(series_id)

    upper = sma + width * std
    lower = sma - width * std

    if latest <= upper and latest >= lower:
        return None

    z = (latest - sma) / std
    severity = _severity_from_z(z, width)
    if not severity:
        return None

    direction = "above" if latest > upper else "below"

    # Find last breach date
    last_breach = None
    for i in range(len(values) - 2, -1, -1):
        v = values[i]
        if (direction == "above" and v > upper) or (direction == "below" and v < lower):
            last_breach = dates[i]
            break

    breach_note = f"This level hasn't been seen since {last_breach.isoformat()}." if last_breach else ""

    description = (
        f"{series_name} broke {direction} the {width}σ Bollinger Band. "
        f"Current: {latest} {unit}. Band: [{lower:.2f}, {upper:.2f}]. "
        f"Z-score: {z:.1f}. {breach_note}"
    )

    return {
        "series_id": series_id,
        "date": latest_date,
        "alert_type": "bollinger_break",
        "severity": severity,
        "z_score": round(z, 2),
        "description": description.strip(),
    }


# ── Detector 2: Trend Break (SMA-12 crossover) ──────────────────────────────

async def _detect_trend_break(
    series_id: str,
    series_name: str,
    unit: str,
    values: List[float],
    dates: List[date],
) -> Optional[dict]:
    """Check if value just crossed SMA-12 after 6+ months on one side."""
    if len(values) < 13:
        return None

    # Compute SMA-12 for the latest point and previous points
    sma12_current = _mean(values[-12:])
    sma12_prev = _mean(values[-13:-1])

    current = values[-1]
    previous = values[-2]

    # Check if a crossover just happened
    current_above = current > sma12_current
    prev_above = previous > sma12_prev

    if current_above == prev_above:
        return None  # No crossover

    # Count consecutive months on one side
    streak = 0
    for i in range(len(values) - 2, max(len(values) - 50, 11), -1):
        sma12_i = _mean(values[i - 11: i + 1])
        if (values[i] > sma12_i) == prev_above:
            streak += 1
        else:
            break

    if streak < 6:
        return None

    direction = "above" if current_above else "below"
    prior_side = "upper" if prev_above else "lower"

    description = (
        f"{series_name} crossed {direction} its 12-month moving average "
        f"after {streak} months on the {prior_side} side. "
        f"SMA-12: {sma12_current:.2f}, Current: {current:.2f}."
    )

    return {
        "series_id": series_id,
        "date": dates[-1],
        "alert_type": "trend_break",
        "severity": "warning",
        "z_score": None,
        "description": description,
    }


# ── Detector 3: Streak (consecutive same-direction MoM) ─────────────────────

async def _detect_streak(
    series_id: str,
    series_name: str,
    unit: str,
    values: List[float],
    dates: List[date],
) -> Optional[dict]:
    """Check for 6+ consecutive months of same-direction MoM change."""
    if len(values) < 7:
        return None

    # Compute MoM changes
    changes = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev == 0:
            changes.append(0)
        else:
            changes.append((values[i] - prev) / abs(prev) * 100)

    # Count consecutive same-sign changes from the end
    if not changes:
        return None

    last_sign = 1 if changes[-1] > 0 else (-1 if changes[-1] < 0 else 0)
    if last_sign == 0:
        return None

    streak = 0
    for c in reversed(changes):
        sign = 1 if c > 0 else (-1 if c < 0 else 0)
        if sign == last_sign:
            streak += 1
        else:
            break

    if streak < 6:
        return None

    # Total change over the streak period
    start_val = values[-(streak + 1)]
    end_val = values[-1]
    total_pct = ((end_val - start_val) / abs(start_val) * 100) if start_val != 0 else 0

    direction = "risen" if last_sign > 0 else "fallen"
    severity = "warning" if streak >= 9 else "watch"

    description = (
        f"{series_name} has {direction} for {streak} consecutive months. "
        f"Total change over streak: {total_pct:+.1f}%."
    )

    return {
        "series_id": series_id,
        "date": dates[-1],
        "alert_type": "streak",
        "severity": severity,
        "z_score": None,
        "description": description,
    }


# ── Detector 4: Level Shift (unusual MoM magnitude) ─────────────────────────

async def _detect_level_shift(
    series_id: str,
    series_name: str,
    unit: str,
    values: List[float],
    dates: List[date],
) -> Optional[dict]:
    """Check if latest |MoM%| > 3x the 24-month average |MoM%|."""
    if len(values) < 25:
        return None

    # Compute MoM changes for last 25 values (to get 24 changes)
    changes = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev == 0:
            changes.append(0)
        else:
            changes.append((values[i] - prev) / abs(prev) * 100)

    if len(changes) < 24:
        return None

    latest_mom = changes[-1]
    # Average absolute MoM over last 24 months (excluding latest)
    recent_abs = [abs(c) for c in changes[-25:-1]]
    avg_abs = _mean(recent_abs) if recent_abs else 0

    if avg_abs == 0:
        return None

    ratio = abs(latest_mom) / avg_abs

    if ratio < 3:
        return None

    severity = "critical" if ratio > 5 else "warning"

    description = (
        f"Unusual move in {series_name}: {latest_mom:+.1f}% MoM vs average |MoM| "
        f"of {avg_abs:.1f}%. This is a {ratio:.1f}x deviation from normal monthly variation."
    )

    return {
        "series_id": series_id,
        "date": dates[-1],
        "alert_type": "level_shift",
        "severity": severity,
        "z_score": round(ratio, 2),
        "description": description,
    }


# ── Main detection entry points ──────────────────────────────────────────────

async def detect_series_anomalies(series_id: str) -> List[dict]:
    """Run all 4 detectors on latest data for one series.

    Deactivates old alerts (is_active=False) if anomaly resolved.
    Writes new alerts to anomaly_alerts table.

    Returns:
        List of alert dicts.
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
            return []

        series_name = meta.name
        unit = meta.unit or ""

        # Load observations
        result = await session.execute(
            select(Observation)
            .where(Observation.series_id == series_id)
            .where(Observation.value.isnot(None))
            .order_by(Observation.date)
        )
        observations = list(result.scalars().all())
        if len(observations) < 7:
            return []

        values = [o.value for o in observations]
        dates = [o.date for o in observations]

        # Run all detectors
        alerts = []
        for detector in [
            _detect_bollinger_break,
            _detect_trend_break,
            _detect_streak,
            _detect_level_shift,
        ]:
            alert_data = await detector(series_id, series_name, unit, values, dates)
            if alert_data:
                alerts.append(alert_data)

        # Deactivate old alerts for this series that aren't in new alerts
        new_types = {a["alert_type"] for a in alerts}
        await session.execute(
            update(AnomalyAlert)
            .where(AnomalyAlert.series_id == series_id)
            .where(AnomalyAlert.is_active == True)
            .where(AnomalyAlert.alert_type.notin_(new_types) if new_types else AnomalyAlert.is_active == True)
            .values(
                is_active=False,
                resolved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

        # Write new alerts (deactivate then re-insert for active types)
        for alert_data in alerts:
            # Deactivate existing of same type
            await session.execute(
                update(AnomalyAlert)
                .where(AnomalyAlert.series_id == series_id)
                .where(AnomalyAlert.alert_type == alert_data["alert_type"])
                .where(AnomalyAlert.is_active == True)
                .values(
                    is_active=False,
                    resolved_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )

            # Insert fresh alert
            new_alert = AnomalyAlert(
                series_id=alert_data["series_id"],
                date=alert_data["date"],
                alert_type=alert_data["alert_type"],
                severity=alert_data["severity"],
                z_score=alert_data.get("z_score"),
                description=alert_data["description"],
                is_active=True,
            )
            session.add(new_alert)

        await session.commit()
        return alerts

    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def detect_all_anomalies() -> List[dict]:
    """Run anomaly detection across all series with sufficient data.

    Returns:
        All alerts sorted by severity (critical > warning > watch).
    """
    factory = await get_session_factory()
    session = factory()
    try:
        result = await session.execute(
            select(Observation.series_id, func.count().label("cnt"))
            .where(Observation.value.isnot(None))
            .group_by(Observation.series_id)
            .having(func.count() >= 7)
        )
        series_list = [row[0] for row in result.all()]
    finally:
        await session.close()

    all_alerts = []
    for sid in series_list:
        try:
            alerts = await detect_series_anomalies(sid)
            all_alerts.extend(alerts)
        except Exception as e:
            logger.warning(f"Anomaly detection failed for {sid}: {e}")

    # Sort by severity
    severity_order = {"critical": 0, "warning": 1, "watch": 2}
    all_alerts.sort(key=lambda a: severity_order.get(a.get("severity", "watch"), 3))

    logger.info(f"Anomaly detection complete: {len(all_alerts)} alerts from {len(series_list)} series")
    return all_alerts


# ── Query functions (agent-callable) ─────────────────────────────────────────

async def get_active_anomalies(severity: str = "all") -> dict:
    """Get active anomaly alerts across all series.

    Args:
        severity: Filter by severity level. One of 'all', 'critical', 'warning', 'watch'.

    Returns:
        Dict with list of active anomaly alerts sorted by severity.
    """
    factory = await get_session_factory()
    session = factory()
    try:
        stmt = (
            select(AnomalyAlert)
            .where(AnomalyAlert.is_active == True)
            .order_by(AnomalyAlert.created_at.desc())
        )
        if severity and severity != "all":
            stmt = stmt.where(AnomalyAlert.severity == severity)

        result = await session.execute(stmt)
        alerts = list(result.scalars().all())

        # Enrich with series names
        alert_dicts = []
        for a in alerts:
            meta_result = await session.execute(
                select(SeriesCatalog.name).where(SeriesCatalog.series_id == a.series_id)
            )
            name = meta_result.scalar() or a.series_id

            alert_dicts.append({
                "series_id": a.series_id,
                "series_name": name,
                "date": a.date.isoformat(),
                "alert_type": a.alert_type,
                "severity": a.severity,
                "z_score": a.z_score,
                "description": a.description,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            })

        severity_order = {"critical": 0, "warning": 1, "watch": 2}
        alert_dicts.sort(key=lambda x: severity_order.get(x["severity"], 3))

        return {
            "alerts": alert_dicts,
            "total": len(alert_dicts),
            "critical_count": sum(1 for a in alert_dicts if a["severity"] == "critical"),
            "warning_count": sum(1 for a in alert_dicts if a["severity"] == "warning"),
            "watch_count": sum(1 for a in alert_dicts if a["severity"] == "watch"),
        }
    finally:
        await session.close()


async def get_series_anomalies(series_id: str) -> dict:
    """Get anomaly alerts for a specific series.

    Args:
        series_id: The series identifier.

    Returns:
        Dict with active and historical anomaly alerts for the series.
    """
    factory = await get_session_factory()
    session = factory()
    try:
        result = await session.execute(
            select(AnomalyAlert)
            .where(AnomalyAlert.series_id == series_id)
            .order_by(AnomalyAlert.created_at.desc())
            .limit(20)
        )
        alerts = list(result.scalars().all())

        return {
            "series_id": series_id,
            "alerts": [
                {
                    "date": a.date.isoformat(),
                    "alert_type": a.alert_type,
                    "severity": a.severity,
                    "z_score": a.z_score,
                    "description": a.description,
                    "is_active": a.is_active,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
                }
                for a in alerts
            ],
            "active_count": sum(1 for a in alerts if a.is_active),
        }
    finally:
        await session.close()



