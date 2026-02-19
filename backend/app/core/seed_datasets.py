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
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.timeseries import SeriesCatalog, Observation

logger = logging.getLogger(__name__)

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw")

# ── CSV file → collection mapping ────────────────────────────────────────────
DATASETS = [
    # SAMA
    ("sama/sama_reserve_assets.csv",             "SAMA Reserves",             "SAMA"),
    ("sama/sama_money_supply.csv",               "SAMA Money Supply",         "SAMA"),
    ("sama/sama_financial_soundness.csv",         "SAMA Banking Indicators",   "SAMA"),
    ("sama/sama_bank_deposits.csv",              "SAMA Bank Deposits",        "SAMA"),
    ("sama/sama_bank_claims.csv",                "SAMA Bank Claims",          "SAMA"),
    ("sama/sama_banking_ratios.csv",             "SAMA Banking Ratios",       "SAMA"),
    ("sama/sama_saibor_rates.csv",               "SAMA Interest Rates",       "SAMA"),
    ("sama/sama_rate_differentials.csv",          "SAMA Rate Differentials",   "SAMA"),
    ("sama/sama_foreign_assets_liabilities.csv",  "SAMA Foreign Assets",       "SAMA"),
    ("sama/sama_cpi.csv",                        "Saudi CPI",                 "SAMA"),
    ("sama/sama_monetary_ratios.csv",            "SAMA Monetary Ratios",      "SAMA"),
    ("sama/sama_balance_of_payments.csv",        "Saudi Balance of Payments",  "SAMA"),
    # EIA
    ("eia/steo/2026-02-12/eia_brent_price.csv",           "Oil Markets",       "EIA"),
    ("eia/steo/2026-02-12/eia_wti_price.csv",             "Oil Markets",       "EIA"),
    ("eia/steo/2026-02-12/eia_global_oil_demand.csv",     "Oil Markets",       "EIA"),
    ("eia/steo/2026-02-12/eia_global_oil_supply.csv",     "Oil Markets",       "EIA"),
    ("eia/steo/2026-02-12/eia_ksa_crude_production.csv",  "KSA Oil Production","EIA"),
    ("eia/steo/2026-02-12/eia_ksa_total_liquids.csv",     "KSA Oil Production","EIA"),
    ("eia/steo/2026-02-12/eia_ksa_spare_capacity.csv",    "KSA Oil Production","EIA"),
    ("eia/steo/2026-02-12/eia_opec_crude_production.csv", "Oil Markets",       "EIA"),
]


def _slugify(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


# ── Human-readable name + unit extraction ────────────────────────────────────
# Column names from CSVs look like: total_reserves_mn_sar, brent_price_usd_bbl
# We split them into a clean name and a unit string.

UNIT_MAP = {
    "mn_sar":     "mn SAR",
    "mn_usd":     "mn USD",
    "mn_bbl_day": "mn bbl/day",
    "usd_bbl":    "USD/bbl",
    "pct":        "%",
    "bps":        "bps",
}


def _parse_column(col: str) -> tuple[str, str]:
    """Return (human_name, unit) from a CSV column name slug."""
    # Try to find the longest matching unit suffix
    for suffix, unit in sorted(UNIT_MAP.items(), key=lambda x: -len(x[0])):
        if col.endswith(f"_{suffix}"):
            name_part = col[: -(len(suffix) + 1)]
            pretty = name_part.replace("_", " ").title()
            return pretty, unit

    # No unit suffix found
    pretty = col.replace("_", " ").title()
    return pretty, ""


async def seed_datasets():
    """Load all shipped CSVs into PostgreSQL (idempotent)."""
    factory = await get_session_factory()
    total_inserted = 0
    total_series = 0

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

                # ── Register series ────────────────────────────────
                for col in columns:
                    series_id = f"{_slugify(collection)}__{_slugify(col)}"

                    existing = await session.execute(
                        select(SeriesCatalog).where(
                            SeriesCatalog.series_id == series_id
                        )
                    )
                    pretty_name, unit = _parse_column(col)

                    existing_obj = existing.scalar()
                    if existing_obj:
                        # Update name/unit if they were previously blank
                        changed = False
                        if not existing_obj.unit and unit:
                            existing_obj.unit = unit
                            changed = True
                        if existing_obj.name != pretty_name:
                            existing_obj.name = pretty_name
                            changed = True
                        if changed:
                            await session.commit()
                    else:
                        session.add(
                            SeriesCatalog(
                                series_id=series_id,
                                name=pretty_name,
                                domain=collection,
                                source=source,
                                unit=unit or None,
                                description=f"{pretty_name} ({unit}) from {source}" if unit else f"{pretty_name} from {source}",
                                synonyms=json.dumps(
                                    [col.lower().replace("_", " "),
                                     pretty_name.lower(),
                                     series_id.replace("_", " ")]
                                ),
                                collection_name=collection,
                            )
                        )
                        total_series += 1
                        total_series += 1

                await session.commit()

                # ── Load observations (skip existing) ──────────────
                f.seek(0)
                reader = csv.DictReader(f)
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

                        series_id = f"{_slugify(collection)}__{_slugify(col)}"
                        batch.append((series_id, obs_date, value))

                # Bulk check existing
                if batch:
                    existing_keys = set()
                    for sid, d, _ in batch:
                        res = await session.execute(
                            select(Observation.id).where(
                                Observation.series_id == sid,
                                Observation.date == d,
                            )
                        )
                        if res.scalar():
                            existing_keys.add((sid, d))

                    new_obs = [
                        Observation(series_id=sid, date=d, value=v)
                        for sid, d, v in batch
                        if (sid, d) not in existing_keys
                    ]

                    if new_obs:
                        session.add_all(new_obs)
                        await session.commit()
                        total_inserted += len(new_obs)
                        logger.info(
                            f"  ✅ {filename} → \"{collection}\": "
                            f"{len(new_obs)} rows inserted"
                        )
                    else:
                        logger.info(
                            f"  ⏭️  {filename} → \"{collection}\": "
                            f"all {len(batch)} rows already exist"
                        )
                else:
                    logger.info(f"  ⚠️  {filename}: no valid data rows")

        except Exception as e:
            logger.warning(f"  ❌ {filename}: {e}")
            await session.rollback()
        finally:
            await session.close()

    logger.info(
        f"✅ Dataset seeding complete: {total_inserted} rows inserted, "
        f"{total_series} new series"
    )

