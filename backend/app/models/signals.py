"""SQLAlchemy models for the Quant Signal Engine.

Tables:
  - signal_snapshots: Computed indicators per series per month
  - anomaly_alerts:   Detected anomaly events
  - domain_scorecards: Domain-level composite scores
  - cross_series_alerts: Pair divergence events
  - signal_runs:      Audit log for pipeline executions
"""

from sqlalchemy import (
    Column, String, Text, DateTime, Integer, Float, Date, Boolean, Index,
)

from app.core.database import Base, _utcnow


class SignalSnapshot(Base):
    __tablename__ = "signal_snapshots"
    __table_args__ = (
        Index("ix_signal_series_date", "series_id", "date", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    value = Column(Float, nullable=True)

    # ── Momentum indicators ──
    mom_pct = Column(Float, nullable=True)
    qoq_pct = Column(Float, nullable=True)
    yoy_pct = Column(Float, nullable=True)
    z_score_12m = Column(Float, nullable=True)
    percentile_36m = Column(Float, nullable=True)
    sma_6 = Column(Float, nullable=True)
    sma_12 = Column(Float, nullable=True)
    trend_slope = Column(Float, nullable=True)

    # ── Classification ──
    signal = Column(String, nullable=True)
    computed_at = Column(DateTime, default=_utcnow)


class AnomalyAlert(Base):
    __tablename__ = "anomaly_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    series_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    alert_type = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    z_score = Column(Float, nullable=True)
    description = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    resolved_at = Column(DateTime, nullable=True)


class DomainScorecard(Base):
    __tablename__ = "domain_scorecards"
    __table_args__ = (
        Index("ix_scorecard_domain_date", "domain", "date", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    score = Column(Float, nullable=False)
    direction = Column(String, nullable=True)
    prior_score = Column(Float, nullable=True)
    component_json = Column(Text, nullable=True)
    alert_count = Column(Integer, default=0)
    computed_at = Column(DateTime, default=_utcnow)


class CrossSeriesAlert(Base):
    __tablename__ = "cross_series_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pair_name = Column(String, nullable=False)
    series_a_id = Column(String, nullable=False)
    series_b_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    long_run_correlation = Column(Float, nullable=True)
    recent_correlation = Column(Float, nullable=True)
    divergence = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)


class SignalRun(Base):
    __tablename__ = "signal_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=_utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")
    series_processed = Column(Integer, default=0)
    anomalies_found = Column(Integer, default=0)
    divergences_found = Column(Integer, default=0)
    duration_ms = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)



