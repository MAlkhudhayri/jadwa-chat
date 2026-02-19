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


async def _cleanup_stale_series(factory):
    """Remove series from old seed runs that used wrong collection names."""
    session = factory()
    try:
        for prefix in _STALE_PREFIXES:
            stale = await session.execute(
                select(SeriesCatalog).where(
                    SeriesCatalog.series_id.like(f"{prefix}%")
                )
            )
            stale_rows = stale.scalars().all()
            if stale_rows:
                for row in stale_rows:
                    # Delete observations first
                    await session.execute(
                        text("DELETE FROM observations WHERE series_id = :sid"),
                        {"sid": row.series_id},
                    )
                    await session.delete(row)
                await session.commit()
                logger.info(
                    f"  Cleaned up {len(stale_rows)} stale series "
                    f"with prefix '{prefix}'"
                )
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

                    existing = await session.execute(
                        select(SeriesCatalog).where(
                            SeriesCatalog.series_id == series_id
                        )
                    )
                    existing_obj = existing.scalar()

                    if existing_obj:
                        changed = False
                        if unit and existing_obj.unit != unit:
                            existing_obj.unit = unit
                            changed = True
                        if existing_obj.name != pretty_name:
                            existing_obj.name = pretty_name
                            changed = True
                        if existing_obj.collection_name != collection:
                            existing_obj.collection_name = collection
                            changed = True
                        if changed:
                            await session.commit()
                    else:
                        session.add(SeriesCatalog(
                            series_id=series_id,
                            name=pretty_name,
                            domain=collection,
                            source=source,
                            unit=unit or None,
                            description=(
                                f"{pretty_name} ({unit}) from {source}"
                                if unit else f"{pretty_name} from {source}"
                            ),
                            synonyms=json.dumps([
                                col.lower().replace("_", " "),
                                pretty_name.lower(),
                                series_id.replace("_", " "),
                            ]),
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
