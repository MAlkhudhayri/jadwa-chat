"""Unified ask endpoint — routes through the orchestrator."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings
from app.services.orchestrator import get_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask", tags=["Ask"])
limiter = Limiter(key_func=get_remote_address)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=10000)
    collection_name: Optional[str] = None
    conversation_id: Optional[str] = None


@router.post("/")
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def ask_question(request: Request, body: AskRequest):
    """Ask JadwaChat a question — routes to the right pipeline automatically."""
    try:
        orchestrator = get_orchestrator()
        result = await orchestrator.ask(
            question=body.question,
            collection_name=body.collection_name,
            conversation_id=body.conversation_id,
        )
        return result
    except Exception as e:
        logger.error(f"Ask error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def ask_question_stream(request: Request, body: AskRequest):
    """Streaming version of /ask — returns SSE events with token-by-token output.

    Event types:
      metadata  — intent, tools_called, series_used
      sources   — retrieved document sources
      token     — each LLM token as it arrives
      done      — final event with conversation_id and citations
      error     — if something went wrong
    """

    async def event_generator():
        try:
            orchestrator = get_orchestrator()
            async for event in orchestrator.ask_stream(
                question=body.question,
                collection_name=body.collection_name,
                conversation_id=body.conversation_id,
            ):
                yield {
                    "event": event["type"],
                    "data": json.dumps(event),
                }
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": str(e)}),
            }

    return EventSourceResponse(event_generator())

