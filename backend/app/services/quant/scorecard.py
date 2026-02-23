"""Domain Scorecards — compute composite scores for 5 macro domains.

Every public function is an async callable that returns a plain dict (agent-ready).
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional, List

from sqlalchemy import select, func

from app.core.database import get_session_factory
from app.models.timeseries import SeriesCatalog
from app.models.signals import SignalSnapshot, DomainScorecard, AnomalyAlert

logger = logging.getLogger(__name__)


# ── Domain Configuration ─────────────────────────────────────────────────────

DOMAIN_CONFIG = {
    "oil": {
        "label": "Oil & Energy",
        "weight": 0.30,
        "series": {
            "oil_markets__brent_price_usd_bbl": 0.25,
            "oil_markets__wti_price_usd_bbl": 0.10,
            "ksa_oil_production__ksa_crude_production_mn_bbl_day": 0.20,
            "oil_markets__global_oil_demand_mn_bbl_day": 0.15,
            "oil_markets__global_oil_supply_mn_bbl_day": 0.10,
            "oil_markets__opec_crude_production_mn_bbl_day": 0.10,
            "ksa_oil_production__ksa_spare_capacity_mn_bbl_day": 0.10,
        },
    },
    "monetary": {
        "label": "Monetary & Reserves",
        "weight": 0.25,
        "series": {
            "sama__total_reserves_mn_sar": 0.20,
            "sama__m1_mn_sar": 0.12,
            "sama__m2_mn_sar": 0.12,
            "sama__other_quasi_money_mn_sar": 0.10,
            "sama__saibor_3m": 0.12,
            "sama__repo_rate": 0.10,
            "sama__foreign_currency_deposits_mn_sar": 0.12,
            "sama__reserves_to_deposits_pct": 0.12,
        },
    },
    "banking": {
        "label": "Banking Sector",
        "weight": 0.20,
        "series": {
            "sama__total_credit_mn_sar": 0.18,
            "sama__demand_deposits_mn_sar": 0.14,
            "sama__time_savings_mn_sar": 0.10,
            "sama__npl_to_total_loans_pct": 0.18,
            "sama__return_on_equity_pct": 0.14,
            "sama__capital_adequacy_ratio_pct": 0.14,
            "sama__private_claims_to_deposits_pct": 0.12,
        },
    },
    "bop": {
        "label": "Balance of Payments",
        "weight": 0.15,
        "series": {
            "sama__current_account_mn_usd": 0.40,
            "sama__goods_mn_usd": 0.25,
            "sama__services_net_mn_usd": 0.20,
            "sama__total_foreign_assets_mn_sar": 0.15,
        },
    },
    "inflation": {
        "label": "Inflation & Prices",
        "weight": 0.10,
        "series": {
            "sama__general_cpi": 0.40,
            "sama__food_beverages_cpi": 0.20,
            "sama__housing_utilities_cpi": 0.25,
            "sama__transport_cpi": 0.15,
        },
    },
}

SIGNAL_SCORES = {
    "strong_up": +100,
    "moderate_up": +50,
    "stable": 0,
    "moderate_down": -50,
    "strong_down": -100,
    "reversal_up": +30,
    "reversal_down": -30,
}

# Series where DOWN = GOOD (inverted scoring)
INVERTED_SERIES = {
    "sama__npl_to_total_loans_pct",
}


# ── Core Computation ─────────────────────────────────────────────────────────

async def compute_domain_scorecard(domain: str, report_date: Optional[date] = None) -> dict:
    """Compute the scorecard for a single domain.

    Args:
        domain: One of 'oil', 'monetary', 'banking', 'bop', 'inflation'.
        report_date: Date to compute for (default: latest available).

    Returns:
        Scorecard dict with score, direction, components.
    """
    if domain not in DOMAIN_CONFIG:
        return {"error": f"Unknown domain: {domain}. Available: {list(DOMAIN_CONFIG.keys())}"}

    config = DOMAIN_CONFIG[domain]
    factory = await get_session_factory()
    session = factory()

    try:
        components = {}
        weighted_score = 0.0
        total_weight = 0.0

        for series_id, weight in config["series"].items():
            # Get the latest signal snapshot for this series
            stmt = (
                select(SignalSnapshot)
                .where(SignalSnapshot.series_id == series_id)
            )
            if report_date:
                stmt = stmt.where(SignalSnapshot.date <= report_date)
            stmt = stmt.order_by(SignalSnapshot.date.desc()).limit(1)

            result = await session.execute(stmt)
            snap = result.scalar()

            if not snap or not snap.signal:
                components[series_id] = {
                    "signal": None,
                    "score": 0,
                    "value": None,
                    "weight": weight,
                    "available": False,
                }
                continue

            # Get series name
            meta_result = await session.execute(
                select(SeriesCatalog).where(SeriesCatalog.series_id == series_id)
            )
            meta = meta_result.scalar()
            name = meta.name if meta else series_id
            unit = meta.unit if meta else ""

            raw_score = SIGNAL_SCORES.get(snap.signal, 0)

            # Invert if needed
            if series_id in INVERTED_SERIES:
                raw_score = -raw_score

            weighted_score += raw_score * weight
            total_weight += weight

            components[series_id] = {
                "name": name,
                "signal": snap.signal,
                "score": raw_score,
                "value": snap.value,
                "unit": unit,
                "date": snap.date.isoformat(),
                "mom_pct": snap.mom_pct,
                "yoy_pct": snap.yoy_pct,
                "z_score": snap.z_score_12m,
                "weight": weight,
                "available": True,
            }

        # Normalize score by available weight
        domain_score = weighted_score / total_weight if total_weight > 0 else 0.0

        # Get prior month's score for direction
        prior_score = None
        direction = "stable"
        if report_date:
            prior_date = report_date - timedelta(days=35)
        else:
            prior_date = date.today() - timedelta(days=35)

        prior_result = await session.execute(
            select(DomainScorecard)
            .where(DomainScorecard.domain == domain)
            .where(DomainScorecard.date < (report_date or date.today()))
            .order_by(DomainScorecard.date.desc())
            .limit(1)
        )
        prior_card = prior_result.scalar()
        if prior_card:
            prior_score = prior_card.score
            diff = domain_score - prior_score
            if diff > 5:
                direction = "improving"
            elif diff < -5:
                direction = "deteriorating"
            else:
                direction = "stable"

        # Count active anomalies for series in this domain
        series_ids = list(config["series"].keys())
        alert_result = await session.execute(
            select(func.count())
            .select_from(AnomalyAlert)
            .where(AnomalyAlert.series_id.in_(series_ids))
            .where(AnomalyAlert.is_active == True)
        )
        alert_count = alert_result.scalar() or 0

        # Determine report_date from components
        actual_date = report_date or date.today()
        component_dates = [
            c.get("date") for c in components.values()
            if c.get("available") and c.get("date")
        ]
        if component_dates:
            actual_date = date.fromisoformat(max(component_dates))

        scorecard = {
            "domain": domain,
            "label": config["label"],
            "score": round(domain_score, 1),
            "direction": direction,
            "prior_score": round(prior_score, 1) if prior_score is not None else None,
            "date": actual_date.isoformat(),
            "alert_count": alert_count,
            "series_count": len(config["series"]),
            "available_count": sum(1 for c in components.values() if c.get("available")),
            "components": components,
        }

        # Save to DB
        # Delete existing for this domain+date
        existing = await session.execute(
            select(DomainScorecard)
            .where(DomainScorecard.domain == domain)
            .where(DomainScorecard.date == actual_date)
        )
        old = existing.scalar()
        if old:
            old.score = scorecard["score"]
            old.direction = direction
            old.prior_score = prior_score
            old.component_json = json.dumps(components)
            old.alert_count = alert_count
            old.computed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            new_card = DomainScorecard(
                domain=domain,
                date=actual_date,
                score=scorecard["score"],
                direction=direction,
                prior_score=prior_score,
                component_json=json.dumps(components),
                alert_count=alert_count,
            )
            session.add(new_card)

        await session.commit()
        return scorecard

    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def compute_all_scorecards(report_date: Optional[date] = None) -> List[dict]:
    """Compute all 5 domain scorecards + aggregate.

    Args:
        report_date: Date to compute for (default: latest available).

    Returns:
        List of scorecard dicts including an 'aggregate' entry.
    """
    scorecards = []
    for domain in DOMAIN_CONFIG:
        try:
            card = await compute_domain_scorecard(domain, report_date)
            scorecards.append(card)
        except Exception as e:
            logger.warning(f"Scorecard computation failed for {domain}: {e}")
            scorecards.append({
                "domain": domain,
                "label": DOMAIN_CONFIG[domain]["label"],
                "score": 0,
                "direction": "stable",
                "error": str(e),
            })

    # Compute aggregate
    aggregate_score = sum(
        card["score"] * DOMAIN_CONFIG.get(card["domain"], {}).get("weight", 0)
        for card in scorecards
        if "error" not in card
    )

    logger.info(f"All scorecards computed. Aggregate: {aggregate_score:.1f}")
    return scorecards


# ── Query functions (agent-callable) ─────────────────────────────────────────

async def get_scorecard(domain: str) -> dict:
    """Get the signal scorecard for a domain.

    Args:
        domain: One of 'oil', 'monetary', 'banking', 'bop', 'inflation', or 'all'.

    Returns:
        Dict with score (-100 to +100), direction, component signals, and alerts.
    """
    if domain == "all":
        return await get_all_scorecards()

    factory = await get_session_factory()
    session = factory()
    try:
        # Get latest scorecard from DB
        result = await session.execute(
            select(DomainScorecard)
            .where(DomainScorecard.domain == domain)
            .order_by(DomainScorecard.date.desc())
            .limit(1)
        )
        card = result.scalar()

        if not card:
            return {"error": f"No scorecard data for domain '{domain}'. Run signal pipeline first."}

        components = {}
        if card.component_json:
            try:
                components = json.loads(card.component_json)
            except json.JSONDecodeError:
                pass

        config = DOMAIN_CONFIG.get(domain, {})

        return {
            "domain": domain,
            "label": config.get("label", domain),
            "score": card.score,
            "direction": card.direction,
            "prior_score": card.prior_score,
            "date": card.date.isoformat(),
            "alert_count": card.alert_count,
            "components": components,
            "computed_at": card.computed_at.isoformat() if card.computed_at else None,
        }
    finally:
        await session.close()


async def get_all_scorecards() -> dict:
    """Get all domain scorecards plus aggregate score.

    Returns:
        Dict with all domain scorecards, aggregate score, and direction.
    """
    factory = await get_session_factory()
    session = factory()
    try:
        scorecards = []
        aggregate_score = 0.0

        for domain, config in DOMAIN_CONFIG.items():
            result = await session.execute(
                select(DomainScorecard)
                .where(DomainScorecard.domain == domain)
                .order_by(DomainScorecard.date.desc())
                .limit(1)
            )
            card = result.scalar()

            if card:
                components = {}
                if card.component_json:
                    try:
                        components = json.loads(card.component_json)
                    except json.JSONDecodeError:
                        pass

                card_dict = {
                    "domain": domain,
                    "label": config["label"],
                    "score": card.score,
                    "direction": card.direction,
                    "prior_score": card.prior_score,
                    "date": card.date.isoformat(),
                    "alert_count": card.alert_count,
                    "components": components,
                }
                scorecards.append(card_dict)
                aggregate_score += card.score * config["weight"]
            else:
                scorecards.append({
                    "domain": domain,
                    "label": config["label"],
                    "score": 0,
                    "direction": "stable",
                    "components": {},
                })

        # Determine aggregate direction
        # Get prior aggregate (sum of prior_scores * weights)
        prior_agg = sum(
            (c.get("prior_score") or 0) * DOMAIN_CONFIG[c["domain"]]["weight"]
            for c in scorecards
            if c.get("prior_score") is not None
        )

        agg_diff = aggregate_score - prior_agg
        if agg_diff > 5:
            agg_direction = "improving"
        elif agg_diff < -5:
            agg_direction = "deteriorating"
        else:
            agg_direction = "stable"

        return {
            "aggregate_score": round(aggregate_score, 1),
            "aggregate_direction": agg_direction,
            "scorecards": scorecards,
            "domain_count": len(scorecards),
        }
    finally:
        await session.close()


async def get_aggregate_score() -> dict:
    """Get just the aggregate score across all domains.

    Returns:
        Dict with aggregate score and direction.
    """
    full = await get_all_scorecards()
    return {
        "aggregate_score": full["aggregate_score"],
        "aggregate_direction": full["aggregate_direction"],
    }

