"""SQLAlchemy models for structured time series data."""

from datetime import datetime, timezone, date
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Date, Index
from app.core.database import Base


class SeriesCatalog(Base):
    __tablename__ = "series_catalog"

    series_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    domain = Column(String, nullable=False)  # oil, bop, fiscal, stability, banking
    source = Column(String, nullable=False)  # JODI, EIA, SAMA, MoF, NDMC, Upload
    dataset = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    frequency = Column(String, default="monthly")
    source_url = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    synonyms = Column(Text, nullable=True)  # JSON array as text
    collection_name = Column(String, nullable=True)  # which database this belongs to
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_obs_series_date", "series_id", "date", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    value = Column(Float, nullable=True)
    as_of_date = Column(Date, nullable=True)
    ingest_run_id = Column(String, nullable=True)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id = Column(String, primary_key=True)
    source = Column(String, nullable=False)
    dataset = Column(String, nullable=True)
    status = Column(String, default="running")  # running, success, failed
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)
    rows_inserted = Column(Integer, default=0)
    rows_updated = Column(Integer, default=0)
    rows_skipped = Column(Integer, default=0)
    file_hash = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    notes = Column(Text, nullable=True)


class ToolCallLog(Base):
    __tablename__ = "tool_call_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tool_name = Column(String, nullable=False)
    series_id = Column(String, nullable=True)
    params = Column(Text, nullable=True)  # JSON
    result_summary = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    duration_ms = Column(Integer, nullable=True)

