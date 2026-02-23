"""Pipeline Runner — orchestrates the full signal computation pipeline.

Runs in sequence:
  1. compute_all_signals()       → signal_snapshots
  2. detect_all_anomalies()      → anomaly_alerts
  3. analyze_all_pairs()         → cross_series_alerts
  4. compute_all_scorecards()    → domain_scorecards
  5. Log signal_run with timing
"""

import logging
import time
from datetime import datetime, timezone

from app.core.database import get_session_factory
from app.models.signals import SignalRun
from app.services.quant.trend import compute_all_signals
from app.services.quant.anomaly import detect_all_anomalies
from app.services.quant.cross_series import analyze_all_pairs
from app.services.quant.scorecard import compute_all_scorecards

logger = logging.getLogger(__name__)


async def run_signal_pipeline() -> dict:
    """Master pipeline — runs everything in sequence.

    1. Query series_catalog for all series with >= 12 observations
    2. For each: compute_series_signals()     → writes signal_snapshots
    3. For each: detect_series_anomalies()    → writes anomaly_alerts
    4. Run analyze_all_pairs()                → writes cross_series_alerts
    5. Run compute_all_scorecards()           → writes domain_scorecards
    6. Log signal_run with timing + counts

    Returns:
        {
            "series_processed": int,
            "signals_written": int,
            "anomalies_found": int,
            "divergences_found": int,
            "scorecards": [...],
            "duration_ms": int,
        }
    """
    t0 = time.time()
    logger.info("🔄 Signal pipeline starting...")

    # Create signal run record
    factory = await get_session_factory()
    session = factory()
    run = SignalRun(status="running")
    session.add(run)
    await session.commit()
    run_id = run.id
    await session.close()

    try:
        # Step 1: Compute signals for all series
        logger.info("  Step 1/4: Computing trend signals...")
        signal_counts = await compute_all_signals()
        series_processed = len(signal_counts)
        signals_written = sum(signal_counts.values())
        logger.info(f"  ✅ Signals: {series_processed} series, {signals_written} snapshots")

        # Step 2: Detect anomalies
        logger.info("  Step 2/4: Detecting anomalies...")
        anomalies = await detect_all_anomalies()
        anomalies_found = len(anomalies)
        logger.info(f"  ✅ Anomalies: {anomalies_found} alerts")

        # Step 3: Cross-series analysis
        logger.info("  Step 3/4: Analyzing cross-series pairs...")
        pair_results = await analyze_all_pairs()
        divergences_found = sum(1 for r in pair_results if r.get("is_diverging"))
        logger.info(f"  ✅ Cross-series: {len(pair_results)} pairs, {divergences_found} divergences")

        # Step 4: Domain scorecards
        logger.info("  Step 4/4: Computing domain scorecards...")
        scorecards = await compute_all_scorecards()
        logger.info(f"  ✅ Scorecards: {len(scorecards)} domains")

        duration_ms = int((time.time() - t0) * 1000)

        # Update signal run record
        session = factory()
        try:
            from sqlalchemy import select
            result = await session.execute(
                select(SignalRun).where(SignalRun.id == run_id)
            )
            run = result.scalar()
            if run:
                run.status = "success"
                run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                run.series_processed = series_processed
                run.anomalies_found = anomalies_found
                run.divergences_found = divergences_found
                run.duration_ms = duration_ms
            await session.commit()
        finally:
            await session.close()

        result = {
            "series_processed": series_processed,
            "signals_written": signals_written,
            "anomalies_found": anomalies_found,
            "divergences_found": divergences_found,
            "scorecards": [
                {
                    "domain": c.get("domain"),
                    "label": c.get("label"),
                    "score": c.get("score"),
                    "direction": c.get("direction"),
                }
                for c in scorecards
            ],
            "duration_ms": duration_ms,
        }

        logger.info(
            f"✅ Signal pipeline complete: {series_processed} series, "
            f"{anomalies_found} anomalies, {divergences_found} divergences, "
            f"{duration_ms}ms"
        )
        return result

    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        logger.error(f"❌ Signal pipeline failed after {duration_ms}ms: {e}")

        # Update run as failed
        session = factory()
        try:
            from sqlalchemy import select
            result = await session.execute(
                select(SignalRun).where(SignalRun.id == run_id)
            )
            run = result.scalar()
            if run:
                run.status = "failed"
                run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
                run.duration_ms = duration_ms
                run.notes = str(e)[:500]
            await session.commit()
        except Exception:
            await session.rollback()
        finally:
            await session.close()

        raise



