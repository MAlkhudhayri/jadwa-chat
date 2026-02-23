"""Cross-Series Intelligence — monitor 10 macro pairs for divergence.

Every public function is an async callable that returns a plain dict (agent-ready).
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional, List

from sqlalchemy import select, update

from app.core.database import get_session_factory
from app.models.timeseries import Observation, SeriesCatalog
from app.models.signals import CrossSeriesAlert

logger = logging.getLogger(__name__)


# ── Monitored Pairs ──────────────────────────────────────────────────────────

MONITORED_PAIRS = [
    {
        "name": "brent_vs_reserves",
        "a": "oil_markets__brent_price_usd_bbl",
        "b": "sama__total_reserves_mn_sar",
        "expected_sign": 1,
        "interpretation": (
            "Oil revenue should flow into SAMA reserves. "
            "Divergence may indicate fiscal drawdown or capital outflow."
        ),
    },
    {
        "name": "brent_vs_current_account",
        "a": "oil_markets__brent_price_usd_bbl",
        "b": "sama__current_account_mn_usd",
        "expected_sign": 1,
        "interpretation": (
            "Oil drives external balance. "
            "Divergence may signal rising imports or declining non-oil exports."
        ),
    },
    {
        "name": "credit_vs_deposits",
        "a": "sama__total_credit_mn_sar",
        "b": "sama__demand_deposits_mn_sar",
        "expected_sign": 1,
        "interpretation": (
            "Credit cycle health — divergence signals LDR stress."
        ),
    },
    {
        "name": "saibor_vs_repo",
        "a": "sama__saibor_3m",
        "b": "sama__repo_rate",
        "expected_sign": 1,
        "interpretation": (
            "SAIBOR follows policy rate — divergence signals liquidity stress."
        ),
    },
    {
        "name": "npl_vs_credit",
        "a": "sama__npl_to_total_loans_pct",
        "b": "sama__total_credit_mn_sar",
        "expected_sign": -1,
        "interpretation": (
            "Credit quality deteriorates when lending booms fade."
        ),
    },
    {
        "name": "reserves_vs_m1",
        "a": "sama__total_reserves_mn_sar",
        "b": "sama__m1_mn_sar",
        "expected_sign": 1,
        "interpretation": (
            "Reserve adequacy vs money creation."
        ),
    },
    {
        "name": "brent_vs_wti",
        "a": "oil_markets__brent_price_usd_bbl",
        "b": "oil_markets__wti_price_usd_bbl",
        "expected_sign": 1,
        "interpretation": (
            "Normally locked — spread widening signals market dislocation."
        ),
    },
    {
        "name": "demand_vs_supply",
        "a": "oil_markets__global_oil_demand_mn_bbl_day",
        "b": "oil_markets__global_oil_supply_mn_bbl_day",
        "expected_sign": 1,
        "interpretation": (
            "Demand-supply gap signals price pressure."
        ),
    },
    {
        "name": "ksa_prod_vs_opec",
        "a": "ksa_oil_production__ksa_crude_production_mn_bbl_day",
        "b": "oil_markets__opec_crude_production_mn_bbl_day",
        "expected_sign": 1,
        "interpretation": (
            "KSA as swing producer — divergence signals policy shift."
        ),
    },
    {
        "name": "cpi_vs_saibor",
        "a": "sama__general_cpi",
        "b": "sama__saibor_3m",
        "expected_sign": 1,
        "interpretation": (
            "Inflation-rate response — divergence signals real rate compression."
        ),
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pearson(x: List[float], y: List[float]) -> Optional[float]:
    """Pearson correlation coefficient."""
    n = len(x)
    if n < 3:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / n
    sx = (sum((v - mx) ** 2 for v in x) / n) ** 0.5
    sy = (sum((v - my) ** 2 for v in y) / n) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


async def _load_series_values(series_id: str) -> dict:
    """Load series as {date: value} dict."""
    factory = await get_session_factory()
    session = factory()
    try:
        result = await session.execute(
            select(Observation)
            .where(Observation.series_id == series_id)
            .where(Observation.value.isnot(None))
            .order_by(Observation.date)
        )
        return {o.date: o.value for o in result.scalars().all()}
    finally:
        await session.close()


# ── Core Analysis ────────────────────────────────────────────────────────────

async def analyze_pair(pair: dict) -> Optional[dict]:
    """Analyze a single pair for divergence.

    Args:
        pair: Dict with name, a, b, expected_sign, interpretation.

    Returns:
        Alert dict if divergence detected, else None.
    """
    vals_a = await _load_series_values(pair["a"])
    vals_b = await _load_series_values(pair["b"])

    # Align on overlapping dates
    common_dates = sorted(set(vals_a.keys()) & set(vals_b.keys()))
    if len(common_dates) < 24:
        return None

    aligned_a = [vals_a[d] for d in common_dates]
    aligned_b = [vals_b[d] for d in common_dates]

    # Long-run: 24-month rolling correlation (latest window)
    if len(common_dates) >= 24:
        long_a = aligned_a[-24:]
        long_b = aligned_b[-24:]
        long_run = _pearson(long_a, long_b)
    else:
        long_run = _pearson(aligned_a, aligned_b)

    # Recent: 6-month rolling correlation
    if len(common_dates) >= 6:
        recent_a = aligned_a[-6:]
        recent_b = aligned_b[-6:]
        recent = _pearson(recent_a, recent_b)
    else:
        recent = long_run

    if long_run is None or recent is None:
        return None

    divergence = abs(long_run - recent)

    result = {
        "pair_name": pair["name"],
        "series_a_id": pair["a"],
        "series_b_id": pair["b"],
        "date": common_dates[-1],
        "long_run_correlation": round(long_run, 3),
        "recent_correlation": round(recent, 3),
        "divergence": round(divergence, 3),
        "interpretation": pair["interpretation"],
        "overlapping_months": len(common_dates),
    }

    if divergence > 0.3:
        # Get series names
        factory = await get_session_factory()
        session = factory()
        try:
            name_a_result = await session.execute(
                select(SeriesCatalog.name).where(SeriesCatalog.series_id == pair["a"])
            )
            name_b_result = await session.execute(
                select(SeriesCatalog.name).where(SeriesCatalog.series_id == pair["b"])
            )
            name_a = name_a_result.scalar() or pair["a"]
            name_b = name_b_result.scalar() or pair["b"]
        finally:
            await session.close()

        severity = "critical" if divergence > 0.5 else "warning"

        description = (
            f"Divergence in {pair['name']}: {name_a} and {name_b} "
            f"historically correlate at r={long_run:.2f} but recent 6-month "
            f"correlation dropped to r={recent:.2f} (divergence: {divergence:.2f}). "
            f"{pair['interpretation']}"
        )

        result["is_diverging"] = True
        result["severity"] = severity
        result["description"] = description
    else:
        result["is_diverging"] = False

    return result


async def analyze_all_pairs() -> List[dict]:
    """Analyze all monitored pairs.

    Writes divergence alerts to cross_series_alerts table.

    Returns:
        List of all pair analysis results (diverging and non-diverging).
    """
    factory = await get_session_factory()
    session = factory()

    results = []
    divergences = []

    for pair in MONITORED_PAIRS:
        try:
            result = await analyze_pair(pair)
            if result:
                results.append(result)
                if result.get("is_diverging"):
                    divergences.append(result)
        except Exception as e:
            logger.warning(f"Cross-series analysis failed for {pair['name']}: {e}")

    # Write divergence alerts to DB
    try:
        # Deactivate old cross-series alerts
        await session.execute(
            update(CrossSeriesAlert)
            .where(CrossSeriesAlert.is_active == True)
            .values(is_active=False)
        )

        for div in divergences:
            alert = CrossSeriesAlert(
                pair_name=div["pair_name"],
                series_a_id=div["series_a_id"],
                series_b_id=div["series_b_id"],
                date=div["date"],
                long_run_correlation=div["long_run_correlation"],
                recent_correlation=div["recent_correlation"],
                divergence=div["divergence"],
                description=div.get("description"),
                is_active=True,
            )
            session.add(alert)

        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.warning(f"Failed to save cross-series alerts: {e}")
    finally:
        await session.close()

    logger.info(f"Cross-series analysis: {len(results)} pairs analysed, {len(divergences)} divergences")
    return results


# ── Query functions (agent-callable) ─────────────────────────────────────────

async def get_pair_analysis(pair_name: str) -> dict:
    """Get correlation analysis for a specific pair.

    Args:
        pair_name: Name of the pair (e.g. 'brent_vs_reserves').

    Returns:
        Dict with correlation data, divergence status, and interpretation.
    """
    pair = next((p for p in MONITORED_PAIRS if p["name"] == pair_name), None)
    if not pair:
        return {"error": f"Unknown pair: {pair_name}. Available: {[p['name'] for p in MONITORED_PAIRS]}"}

    result = await analyze_pair(pair)
    if not result:
        return {"error": f"Insufficient data to analyse pair '{pair_name}'"}

    return result


async def get_all_divergences(pair_name: Optional[str] = None) -> dict:
    """Get cross-series correlation analysis and divergence alerts.

    Args:
        pair_name: Optional specific pair to analyse. Omit for all pairs.

    Returns:
        Dict with all pair analyses and active divergence alerts.
    """
    if pair_name:
        result = await get_pair_analysis(pair_name)
        return {"pairs": [result] if "error" not in result else [], "error": result.get("error")}

    # Get active alerts from DB
    factory = await get_session_factory()
    session = factory()
    try:
        result = await session.execute(
            select(CrossSeriesAlert)
            .where(CrossSeriesAlert.is_active == True)
            .order_by(CrossSeriesAlert.divergence.desc())
        )
        alerts = list(result.scalars().all())

        alert_dicts = [
            {
                "pair_name": a.pair_name,
                "series_a_id": a.series_a_id,
                "series_b_id": a.series_b_id,
                "date": a.date.isoformat(),
                "long_run_correlation": a.long_run_correlation,
                "recent_correlation": a.recent_correlation,
                "divergence": a.divergence,
                "description": a.description,
            }
            for a in alerts
        ]

        # Also include all pair configs for reference
        pair_summaries = []
        for pair in MONITORED_PAIRS:
            pair_summaries.append({
                "name": pair["name"],
                "series_a": pair["a"],
                "series_b": pair["b"],
                "interpretation": pair["interpretation"],
            })

        return {
            "active_divergences": alert_dicts,
            "divergence_count": len(alert_dicts),
            "monitored_pairs": pair_summaries,
            "total_pairs": len(MONITORED_PAIRS),
        }
    finally:
        await session.close()



