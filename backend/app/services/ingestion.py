"""Ingestion service — loads parsed observations into SQLite."""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import select

from app.core.database import get_session_factory
from app.models.timeseries import Observation, IngestionRun
from app.services.connectors.base import ParsedObservation

logger = logging.getLogger(__name__)


class IngestionService:
    async def _create_run(self, source: str, dataset: str = "") -> str:
        run_id = str(uuid4())
        factory = await get_session_factory()
        session = factory()
        try:
            run = IngestionRun(id=run_id, source=source, dataset=dataset)
            session.add(run)
            await session.commit()
            return run_id
        finally:
            await session.close()

    async def _finish_run(self, run_id: str, status: str = "success",
                          rows_inserted: int = 0, rows_updated: int = 0,
                          rows_skipped: int = 0, file_path: str = "", notes: str = ""):
        factory = await get_session_factory()
        session = factory()
        try:
            result = await session.execute(
                select(IngestionRun).where(IngestionRun.id == run_id)
            )
            run = result.scalar()
            if run:
                run.status = status
                run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                run.rows_inserted = rows_inserted
                run.rows_updated = rows_updated
                run.rows_skipped = rows_skipped
                run.file_path = file_path
                run.notes = notes
                await session.commit()
        finally:
            await session.close()

    async def load_observations(self, observations: List[ParsedObservation],
                                run_id: Optional[str] = None) -> dict:
        factory = await get_session_factory()
        session = factory()
        inserted = 0
        updated = 0
        skipped = 0

        try:
            for obs in observations:
                if obs.value is None:
                    skipped += 1
                    continue

                stmt = select(Observation).where(
                    Observation.series_id == obs.series_id,
                    Observation.date == obs.date,
                )
                result = await session.execute(stmt)
                existing = result.scalar()

                if existing:
                    if existing.value != obs.value:
                        existing.value = obs.value
                        existing.as_of_date = obs.as_of_date
                        existing.ingest_run_id = run_id
                        updated += 1
                    else:
                        skipped += 1
                else:
                    new_obs = Observation(
                        series_id=obs.series_id,
                        date=obs.date,
                        value=obs.value,
                        as_of_date=obs.as_of_date,
                        ingest_run_id=run_id,
                    )
                    session.add(new_obs)
                    inserted += 1

            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Ingestion error: {e}")
            raise
        finally:
            await session.close()

        return {
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "total": inserted + updated + skipped,
        }


_ingestion_service: Optional[IngestionService] = None


def get_ingestion_service() -> IngestionService:
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = IngestionService()
    return _ingestion_service

