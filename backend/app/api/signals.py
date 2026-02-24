"""Signal Engine API endpoints.

Exposes the quant signal engine to the frontend and external consumers.

Read-only endpoints (GET) have no auth requirement — they display computed data.
Write endpoints (POST) use get_current_user (optional auth).
"""

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.database import get_session_factory
from app.models.signals import SignalRun

_security = HTTPBearer(auto_error=False)


async def _optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
):
    """Soft auth — returns user if token is valid, None otherwise. Never raises 401."""
    if credentials is None:
        return None
    try:
        from app.services.auth import decode_access_token
        from app.core.database import User
        from sqlalchemy import select

        payload = decode_access_token(credentials.credentials)
        if not payload:
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        factory = await get_session_factory()
        async with factory() as session:
            result = await session.execute(select(User).where(User.id == int(user_id)))
            return result.scalar_one_or_none()
    except Exception as exc:
        logging.getLogger(__name__).debug("Soft auth failed: %s", exc)
        return None
from app.services.quant.scorecard import get_scorecard, get_all_scorecards
from app.services.quant.anomaly import get_active_anomalies, get_series_anomalies
from app.services.quant.trend import get_series_signal
from app.services.quant.cross_series import get_all_divergences
from app.services.quant.runner import run_signal_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/signals", tags=["Signals"])


# ── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def signal_dashboard():
    """Full dashboard JSON — all scorecards + active anomalies + divergences."""
    try:
        scorecards_data = await get_all_scorecards()
        anomalies_data = await get_active_anomalies(severity="all")
        cross_data = await get_all_divergences()

        factory = await get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(SignalRun)
                .where(SignalRun.status == "success")
                .order_by(SignalRun.finished_at.desc())
                .limit(1)
            )
            last_run = result.scalar()
            last_run_info = {
                "finished_at": last_run.finished_at.isoformat() if last_run and last_run.finished_at else None,
                "series_processed": last_run.series_processed if last_run else 0,
                "duration_ms": last_run.duration_ms if last_run else None,
            }

        report_date = None
        for card in scorecards_data.get("scorecards", []):
            d = card.get("date")
            if d:
                if report_date is None or d > report_date:
                    report_date = d

        return {
            "report_date": report_date,
            "aggregate_score": scorecards_data.get("aggregate_score", 0),
            "aggregate_direction": scorecards_data.get("aggregate_direction", "stable"),
            "scorecards": scorecards_data.get("scorecards", []),
            "anomalies": anomalies_data.get("alerts", []),
            "anomaly_count": anomalies_data.get("total", 0),
            "cross_series_alerts": cross_data.get("active_divergences", []),
            "divergence_count": cross_data.get("divergence_count", 0),
            "last_run": last_run_info,
            "series_count": last_run_info.get("series_processed", 0),
        }
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        raise HTTPException(status_code=500, detail=f"Dashboard error: {str(e)}")


# ── Scorecards ───────────────────────────────────────────────────────────────

@router.get("/scorecards")
async def signal_scorecards():
    """List of 5 domain scorecards + aggregate."""
    try:
        return await get_all_scorecards()
    except Exception as e:
        logger.error(f"Scorecards error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/domain/{domain}")
async def signal_domain(domain: str):
    """Single domain detail with component-level signals."""
    valid = {"oil", "monetary", "banking", "bop", "inflation"}
    if domain not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid domain. Choose from: {valid}")
    try:
        result = await get_scorecard(domain)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Domain scorecard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Anomalies ────────────────────────────────────────────────────────────────

@router.get("/anomalies")
async def signal_anomalies(severity: Optional[str] = "all"):
    """Active anomaly alerts, sorted by severity."""
    try:
        return await get_active_anomalies(severity=severity or "all")
    except Exception as e:
        logger.error(f"Anomalies error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Series Detail ────────────────────────────────────────────────────────────

@router.get("/series/{series_id:path}")
async def signal_series(series_id: str):
    """Signal history for one series (last 24 months)."""
    try:
        result = await get_series_signal(series_id)
        if "error" in result and "not found" in result["error"].lower():
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Series signal error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Cross-Series ─────────────────────────────────────────────────────────────

@router.get("/cross-series")
async def signal_cross_series(pair_name: Optional[str] = None):
    """All cross-series pair correlations + active divergence alerts."""
    try:
        return await get_all_divergences(pair_name=pair_name)
    except Exception as e:
        logger.error(f"Cross-series error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── IC Memo Autopilot ─────────────────────────────────────────────────────────

@router.post("/memo")
async def signal_memo(body: dict, user=Depends(_optional_user)):
    """Generate an IC-style memo for any topic using signal engine data.

    Body: {"topic": "Saudi banking liquidity outlook"}
    """
    topic = (body or {}).get("topic", "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
    try:
        from app.services.quant.memo import generate_ic_memo
        return await generate_ic_memo(topic)
    except Exception as e:
        logger.error(f"IC Memo error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Pipeline Refresh ─────────────────────────────────────────────────────────

@router.post("/refresh")
async def signal_refresh(user=Depends(_optional_user)):
    """Trigger pipeline re-run. Returns summary."""
    try:
        result = await run_signal_pipeline()
        return result
    except Exception as e:
        logger.error(f"Signal refresh error: {e}")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")


# ── Agent Debate ──────────────────────────────────────────────────────────────

@router.get("/debate/agents")
async def debate_agents():
    """List available agent personas."""
    from app.services.quant.debate import get_available_agents
    return {"agents": get_available_agents()}


@router.post("/debate")
async def debate_start(body: dict = None, user=Depends(_optional_user)):
    """Start a new debate session. Optionally provide a topic."""
    try:
        from app.services.quant.debate import start_debate
        topic = (body or {}).get("topic", "").strip() or None
        return await start_debate(topic=topic)
    except Exception as e:
        logger.error(f"Debate start error: {e}")
        raise HTTPException(status_code=500, detail=f"Debate error: {str(e)}")


@router.get("/debate/{session_id}")
async def debate_state(session_id: str):
    """Get the full state of a debate session."""
    try:
        from app.services.quant.debate import get_session_state
        return get_session_state(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/debate/{session_id}/user")
async def debate_user_message(session_id: str, body: dict, user=Depends(_optional_user)):
    """User injects a message. Agents respond in the next round automatically."""
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    try:
        from app.services.quant.debate import add_user_message
        return await add_user_message(session_id, message)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Debate user message error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/debate/{session_id}/round")
async def debate_next_round(session_id: str, user=Depends(_optional_user)):
    """Run the next round — agents debate among themselves."""
    try:
        from app.services.quant.debate import run_next_round
        return await run_next_round(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Debate round error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/debate/{session_id}/scenario")
async def debate_scenario(session_id: str, body: dict, user=Depends(_optional_user)):
    """Inject a what-if scenario. Agents react in a new round."""
    scenario_id = body.get("scenario_id", "").strip()
    if not scenario_id:
        raise HTTPException(status_code=400, detail="scenario_id is required")
    try:
        from app.services.quant.debate import inject_scenario
        return await inject_scenario(session_id, scenario_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Debate scenario error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/debate/{session_id}/memo")
async def debate_memo(session_id: str, user=Depends(_optional_user)):
    """Generate an Investment Committee memo summarizing the debate."""
    try:
        from app.services.quant.debate import generate_memo
        return await generate_memo(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Debate memo error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Context Menu (for chat integration) ──────────────────────────────────────

@router.get("/context-menu")
async def signal_context_menu():
    """Lightweight summary of what signal data is available to pin as chat context."""
    try:
        scorecards_data = await get_all_scorecards()
        anomalies_data = await get_active_anomalies(severity="all")
        cross_data = await get_all_divergences()

        domains = []
        for card in scorecards_data.get("scorecards", []):
            domains.append({
                "domain": card.get("domain"),
                "label": card.get("label", card.get("domain", "")),
                "score": card.get("score", 0),
                "direction": card.get("direction", "stable"),
                "alert_count": card.get("alert_count", 0),
            })

        return {
            "domains": domains,
            "aggregate_score": scorecards_data.get("aggregate_score", 0),
            "aggregate_direction": scorecards_data.get("aggregate_direction", "stable"),
            "anomaly_count": anomalies_data.get("total", 0),
            "anomaly_critical": anomalies_data.get("critical_count", 0),
            "anomaly_warning": anomalies_data.get("warning_count", 0),
            "divergence_count": cross_data.get("divergence_count", 0),
            "total_pairs": cross_data.get("total_pairs", 0),
        }
    except Exception as e:
        logger.error(f"Context menu error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Health ───────────────────────────────────────────────────────────────────

@router.get("/health")
async def signal_health():
    """Last signal_run timestamp + status. No auth required."""
    factory = await get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(SignalRun)
            .order_by(SignalRun.started_at.desc())
            .limit(1)
        )
        run = result.scalar()

        if not run:
            return {
                "status": "no_runs",
                "last_run": None,
                "message": "Signal pipeline has not run yet.",
            }

        return {
            "status": run.status,
            "last_run": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "series_processed": run.series_processed,
            "anomalies_found": run.anomalies_found,
            "divergences_found": run.divergences_found,
            "duration_ms": run.duration_ms,
        }


# ── ML Models ─────────────────────────────────────────────────────────────────

@router.get("/models/status")
async def models_status():
    """Return the status of all loaded ML models."""
    try:
        from app.services.models.registry import get_registry
        return get_registry().status()
    except Exception as e:
        logger.error(f"Models status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/warm")
async def models_warm(body: dict = None, user=Depends(_optional_user)):
    """Load (warm) one or all models. Body: {\"model\": \"reranker\"} or omit for all."""
    try:
        from app.services.models.registry import get_registry
        registry = get_registry()
        model_name = (body or {}).get("model")
        if model_name:
            status = registry.warm(model_name)
            return {"model": model_name, "status": status}
        else:
            results = registry.warm_all()
            return {"results": results}
    except Exception as e:
        logger.error(f"Models warm error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/compute")
async def models_compute(body: dict = None, user=Depends(_optional_user)):
    """Run compute pipeline for ML models (change-point, isolation forest, drivers).

    This pre-computes anomaly and attribution results from the latest signal data.
    """
    try:
        from app.services.models.compute import run_model_compute
        result = await run_model_compute()
        return result
    except Exception as e:
        logger.error(f"Models compute error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
