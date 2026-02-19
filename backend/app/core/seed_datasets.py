"""Seed SAMA/EIA CSV datasets into PostgreSQL on startup.

Reads CSVs shipped in data/raw/sama/ and data/raw/eia/ and upserts them
into the series_catalog + observation tables so they appear as queryable
collections in the sidebar without any manual upload.

Idempotent: skips rows that already exist (based on series_id + date).
"""

import csv
import json
import logging
import os
import re
from datetime import date

from sqlalchemy import select, func, text

from app.core.database import get_session_factory
from app.models.timeseries import SeriesCatalog, Observation

logger = logging.getLogger(__name__)

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw")

# ── CSV file -> collection mapping ────────────────────────────────────────────
# Collection name MUST match what the user sees in the sidebar / Qdrant.
DATASETS = [
    # SAMA — collection "SAMA" matches the existing Qdrant collection
    ("sama/sama_reserve_assets.csv",              "SAMA",             "SAMA"),
    ("sama/sama_money_supply.csv",                "SAMA",             "SAMA"),
    ("sama/sama_financial_soundness.csv",          "SAMA",             "SAMA"),
    ("sama/sama_bank_deposits.csv",               "SAMA",             "SAMA"),
    ("sama/sama_bank_claims.csv",                 "SAMA",             "SAMA"),
    ("sama/sama_banking_ratios.csv",              "SAMA",             "SAMA"),
    ("sama/sama_saibor_rates.csv",                "SAMA",             "SAMA"),
    ("sama/sama_rate_differentials.csv",           "SAMA",             "SAMA"),
    ("sama/sama_foreign_assets_liabilities.csv",   "SAMA",             "SAMA"),
    ("sama/sama_cpi.csv",                         "SAMA",             "SAMA"),
    ("sama/sama_monetary_ratios.csv",             "SAMA",             "SAMA"),
    ("sama/sama_balance_of_payments.csv",         "SAMA",             "SAMA"),
    # EIA
    ("eia/steo/2026-02-12/eia_brent_price.csv",           "Oil Markets",        "EIA"),
    ("eia/steo/2026-02-12/eia_wti_price.csv",             "Oil Markets",        "EIA"),
    ("eia/steo/2026-02-12/eia_global_oil_demand.csv",     "Oil Markets",        "EIA"),
    ("eia/steo/2026-02-12/eia_global_oil_supply.csv",     "Oil Markets",        "EIA"),
    ("eia/steo/2026-02-12/eia_ksa_crude_production.csv",  "KSA Oil Production", "EIA"),
    ("eia/steo/2026-02-12/eia_ksa_total_liquids.csv",     "KSA Oil Production", "EIA"),
    ("eia/steo/2026-02-12/eia_ksa_spare_capacity.csv",    "KSA Oil Production", "EIA"),
    ("eia/steo/2026-02-12/eia_opec_crude_production.csv", "Oil Markets",        "EIA"),
]


def _slugify(txt: str) -> str:
    s = txt.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


# ── Human readable name + unit extraction ─────────────────────────────────────
UNIT_MAP = {
    "mn_sar":     "mn SAR",
    "mn_usd":     "mn USD",
    "mn_bbl_day": "mn bbl/day",
    "usd_bbl":    "USD/bbl",
    "pct":        "%",
    "bps":        "bps",
}


def _parse_column(col: str) -> tuple:
    """Return (human_name, unit) from a CSV column name slug."""
    for suffix, unit in sorted(UNIT_MAP.items(), key=lambda x: -len(x[0])):
        if col.endswith(f"_{suffix}"):
            name_part = col[: -(len(suffix) + 1)]
            pretty = name_part.replace("_", " ").title()
            return pretty, unit
    pretty = col.replace("_", " ").title()
    return pretty, ""


# ── Rich synonyms for key series ──────────────────────────────────────────
# Maps series_id → extra synonyms to add (on top of auto-generated ones).
# This drastically improves discovery for common analyst queries.
EXTRA_SYNONYMS = {
    "sama__total_reserves_mn_sar": [
        "SAMA reserves", "central bank reserves", "total reserves",
        "Saudi reserves", "SAMA total reserves", "reserve assets",
    ],
    "sama__m1_mn_sar": [
        "M1 money supply", "money supply M1", "M1", "narrow money",
    ],
    "sama__m2_mn_sar": [
        "M2 money supply", "money supply M2", "M2", "broad money M2",
    ],
    "sama__other_quasi_money_mn_sar": [
        "M3 money supply", "money supply M3", "M3", "broad money",
    ],
    "sama__general_cpi": [
        "CPI", "consumer price index", "Saudi CPI", "general CPI",
        "inflation rate", "price index",
    ],
    "sama__food_beverages_cpi": [
        "food CPI", "food price index", "food inflation",
    ],
    "sama__housing_utilities_cpi": [
        "housing CPI", "rent index", "housing inflation",
    ],
    "sama__transport_cpi": [
        "transport CPI", "transportation inflation",
    ],
    "sama__clothing_cpi": [
        "clothing CPI", "apparel inflation",
    ],
    "sama__demand_deposits_mn_sar": [
        "bank deposits", "commercial bank deposits", "demand deposits",
        "total deposits", "banking deposits",
    ],
    "sama__time_savings_mn_sar": [
        "time deposits", "savings deposits", "term deposits",
    ],
    "sama__total_credit_mn_sar": [
        "bank credit", "total bank credit", "bank lending",
        "commercial bank loans", "total loans",
    ],
    "sama__capital_adequacy_ratio_pct": [
        "capital adequacy", "CAR", "bank capital ratio",
    ],
    "sama__return_on_equity_pct": [
        "bank ROE", "banking ROE", "return on equity",
    ],
    "sama__return_on_assets_pct": [
        "bank ROA", "banking ROA", "return on assets",
    ],
    "sama__npl_to_total_loans_pct": [
        "NPL ratio", "nonperforming loans", "bad loans ratio",
    ],
    "sama__saibor_3m": [
        "SAIBOR", "SAIBOR 3M", "SAIBOR 3 month", "interbank rate",
        "Saudi interbank rate",
    ],
    "sama__repo_rate": [
        "repo rate", "SAMA repo", "reverse repo",
    ],
    "sama__current_account_mn_usd": [
        "current account", "current account balance",
        "balance of payments current account", "BOP current account",
    ],
    "sama__total_foreign_assets_mn_sar": [
        "bank foreign assets", "foreign assets banks",
        "net foreign assets",
    ],
    "oil_markets__brent_price_usd_bbl": [
        "Brent", "Brent price", "Brent crude", "Brent oil price",
        "oil price", "crude oil price",
    ],
    "oil_markets__wti_price_usd_bbl": [
        "WTI", "WTI price", "WTI crude", "West Texas Intermediate",
    ],
    "oil_markets__global_oil_demand_mn_bbl_day": [
        "global oil demand", "world oil demand", "oil demand",
        "world oil consumption",
    ],
    "oil_markets__global_oil_supply_mn_bbl_day": [
        "global oil supply", "world oil supply", "oil supply",
        "world oil production total",
    ],
    "oil_markets__opec_crude_production_mn_bbl_day": [
        "OPEC production", "OPEC crude", "OPEC output",
    ],
    "ksa_oil_production__ksa_crude_production_mn_bbl_day": [
        "KSA crude production", "Saudi oil production",
        "Saudi crude output", "KSA oil output",
    ],
    "ksa_oil_production__ksa_total_liquids_mn_bbl_day": [
        "KSA total liquids", "Saudi total liquids",
    ],
    "ksa_oil_production__ksa_spare_capacity_mn_bbl_day": [
        "KSA spare capacity", "Saudi spare capacity",
        "OPEC spare capacity Saudi",
    ],
}


# Old prefixes from previous seed runs with wrong collection slugs
_STALE_PREFIXES = [
    "sama_reserves__",
    "sama_money_supply__",
    "sama_banking_indicators__",
    "sama_bank_deposits__",
    "sama_bank_claims__",
    "sama_banking_ratios__",
    "sama_interest_rates__",
    "sama_rate_differentials__",
    "sama_foreign_assets__",
    "saudi_cpi__",
    "sama_monetary_ratios__",
    "saudi_balance_of_payments__",
]

# Exact IDs from the old YAML catalog that have ZERO observations
_STALE_EXACT_IDS = [
    "ksa_crude_production", "ksa_oil_exports", "global_oil_demand",
    "global_oil_supply", "brent_price", "current_account", "net_services",
    "net_change_reserves", "govt_revenues", "govt_expenditure", "govt_debt",
    "debt_to_gdp", "gdp_growth", "sama_reserves", "nfa_banks",
    "govt_deposits_sama", "reserve_m3_ratio", "money_supply_m3",
    "saibor_sofr_3m_spread", "saibor_sofr_12m_spread",
    "capital_adequacy_ratio", "simple_ldr", "demand_deposits_pct",
    "commercial_bank_deposits", "commercial_bank_loans", "banking_roe",
    "npl_ratio",
]


async def _cleanup_stale_series(factory):
    """Remove placeholder/stale series that have no observations."""
    session = factory()
    removed = 0
    try:
        # 1. Remove series matching stale prefixes
        for prefix in _STALE_PREFIXES:
            stale = await session.execute(
                select(SeriesCatalog).where(
                    SeriesCatalog.series_id.like(f"{prefix}%")
                )
            )
            for row in stale.scalars().all():
                await session.execute(
                    text("DELETE FROM observations WHERE series_id = :sid"),
                    {"sid": row.series_id},
                )
                await session.delete(row)
                removed += 1

        # 2. Remove exact YAML placeholder IDs (zero observations)
        for sid in _STALE_EXACT_IDS:
            existing = await session.execute(
                select(SeriesCatalog).where(SeriesCatalog.series_id == sid)
            )
            row = existing.scalar()
            if row:
                # Only delete if it has no observations
                cnt = await session.execute(
                    select(func.count(Observation.id)).where(
                        Observation.series_id == sid
                    )
                )
                if (cnt.scalar() or 0) == 0:
                    await session.delete(row)
                    removed += 1

        if removed:
            await session.commit()
            logger.info(f"  Cleaned up {removed} stale/placeholder series")
    except Exception as e:
        logger.warning(f"  Stale cleanup warning: {e}")
        await session.rollback()
    finally:
        await session.close()


async def seed_datasets():
    """Load all shipped CSVs into PostgreSQL (idempotent)."""
    factory = await get_session_factory()
    total_inserted = 0
    total_series = 0

    # First: remove series from old seed runs with wrong collection slugs
    await _cleanup_stale_series(factory)

    for rel_path, collection, source in DATASETS:
        csv_path = os.path.join(BASE_DIR, rel_path)
        if not os.path.exists(csv_path):
            continue

        filename = os.path.basename(rel_path)
        session = factory()
        try:
            with open(csv_path, newline="") as f:
                reader = csv.DictReader(f)
                columns = [c for c in reader.fieldnames if c != "date"]

                # ── 1. Register / update series catalog ───────────────
                for col in columns:
                    series_id = f"{_slugify(collection)}__{_slugify(col)}"
                    pretty_name, unit = _parse_column(col)

                    # Build synonyms: auto-generated + rich extras
                    auto_syns = [
                        col.lower().replace("_", " "),
                        pretty_name.lower(),
                        re.sub(r"_+", " ", series_id).strip(),  # no double spaces
                    ]
                    extra = EXTRA_SYNONYMS.get(series_id, [])
                    all_syns = list(dict.fromkeys(
                        auto_syns + [s.lower() for s in extra]
                    ))  # deduplicate preserving order
                    syns_json = json.dumps(all_syns)

                    desc_text = (
                        f"{pretty_name} ({unit}) from {source}"
                        if unit else f"{pretty_name} from {source}"
                    )

                    existing = await session.execute(
                        select(SeriesCatalog).where(
                            SeriesCatalog.series_id == series_id
                        )
                    )
                    existing_obj = existing.scalar()

                    if existing_obj:
                        # Always update synonyms, description, name, unit
                        existing_obj.name = pretty_name
                        existing_obj.unit = unit or existing_obj.unit
                        existing_obj.collection_name = collection
                        existing_obj.synonyms = syns_json
                        existing_obj.description = desc_text
                        await session.commit()
                    else:
                        session.add(SeriesCatalog(
                            series_id=series_id,
                            name=pretty_name,
                            domain=collection,
                            source=source,
                            unit=unit or None,
                            description=desc_text,
                            synonyms=syns_json,
                            collection_name=collection,
                        ))
                        total_series += 1

                await session.commit()

                # ── 2. Quick check: already seeded? ───────────────────
                first_sid = f"{_slugify(collection)}__{_slugify(columns[0])}"
                cnt_result = await session.execute(
                    select(func.count(Observation.id)).where(
                        Observation.series_id == first_sid
                    )
                )
                if (cnt_result.scalar() or 0) > 0:
                    logger.info(
                        f"  >> {filename} -> \"{collection}\": already seeded"
                    )
                    continue

                # ── 3. Build deduplicated batch ───────────────────────
                f.seek(0)
                reader = csv.DictReader(f)
                seen = set()
                batch = []
                for row in reader:
                    raw_date = row.get("date", "")
                    if not re.match(r"^\d{4}-\d{2}-\d{2}$", raw_date):
                        continue
                    obs_date = date.fromisoformat(raw_date)

                    for col in columns:
                        val = row.get(col)
                        if not val:
                            continue
                        try:
                            value = float(val)
                        except (ValueError, TypeError):
                            continue

                        sid = f"{_slugify(collection)}__{_slugify(col)}"
                        key = (sid, obs_date)
                        if key in seen:
                            continue
                        seen.add(key)
                        batch.append((sid, obs_date, value))

                if not batch:
                    logger.info(f"  !! {filename}: no valid data rows")
                    continue

                # ── 4. Bulk insert in chunks (safe) ───────────────────
                CHUNK = 500
                inserted = 0
                for i in range(0, len(batch), CHUNK):
                    chunk = batch[i : i + CHUNK]
                    obs_list = [
                        Observation(series_id=sid, date=d, value=v)
                        for sid, d, v in chunk
                    ]
                    session.add_all(obs_list)
                    try:
                        await session.commit()
                        inserted += len(obs_list)
                    except Exception:
                        await session.rollback()
                        # Fallback: insert one by one, skip duplicates
                        for obs in obs_list:
                            try:
                                session.add(obs)
                                await session.commit()
                                inserted += 1
                            except Exception:
                                await session.rollback()

                total_inserted += inserted
                logger.info(
                    f"  OK {filename} -> \"{collection}\": "
                    f"{inserted} rows inserted"
                )

        except Exception as e:
            logger.warning(f"  !! {filename}: {e}")
            await session.rollback()
        finally:
            await session.close()

    logger.info(
        f"Dataset seeding complete: {total_inserted} rows inserted, "
        f"{total_series} new series"
    )
