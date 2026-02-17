"""Seed the series_catalog from YAML on startup."""

import json
import logging
import os

import yaml
from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.timeseries import SeriesCatalog

logger = logging.getLogger(__name__)

YAML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "dictionaries", "series_catalog.yaml"
)


async def seed_series_catalog():
    """Upsert series from YAML into series_catalog table."""
    if not os.path.exists(YAML_PATH):
        logger.warning(f"Series catalog YAML not found at {YAML_PATH}")
        return

    with open(YAML_PATH, "r") as f:
        data = yaml.safe_load(f)

    if not data or "series" not in data:
        logger.warning("Empty or malformed series_catalog.yaml")
        return

    factory = await get_session_factory()
    session = factory()

    try:
        inserted = 0
        updated = 0

        for entry in data["series"]:
            sid = entry["series_id"]
            stmt = select(SeriesCatalog).where(SeriesCatalog.series_id == sid)
            result = await session.execute(stmt)
            existing = result.scalar()

            synonyms_json = json.dumps(entry.get("synonyms", []))

            if existing:
                existing.name = entry["name"]
                existing.domain = entry["domain"]
                existing.source = entry["source"]
                existing.unit = entry.get("unit")
                existing.frequency = entry.get("frequency", "monthly")
                existing.source_url = entry.get("source_url")
                existing.description = entry.get("description")
                existing.synonyms = synonyms_json
                updated += 1
            else:
                new_series = SeriesCatalog(
                    series_id=sid,
                    name=entry["name"],
                    domain=entry["domain"],
                    source=entry["source"],
                    unit=entry.get("unit"),
                    frequency=entry.get("frequency", "monthly"),
                    source_url=entry.get("source_url"),
                    description=entry.get("description"),
                    synonyms=synonyms_json,
                )
                session.add(new_series)
                inserted += 1

        await session.commit()
        logger.info(f"✅ Series catalog seeded: {inserted} new, {updated} updated")
    except Exception as e:
        logger.error(f"Failed to seed series catalog: {e}")
        await session.rollback()
    finally:
        await session.close()

