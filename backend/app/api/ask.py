"""Unified ask endpoint — routes through the orchestrator."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.services.orchestrator import get_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask", tags=["Ask"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=10000)
    collection_name: Optional[str] = None
    conversation_id: Optional[str] = None


@router.post("/")
async def ask_question(request: AskRequest):
    """Ask JadwaChat a question — routes to the right pipeline automatically."""
    try:
        orchestrator = get_orchestrator()
        result = await orchestrator.ask(
            question=request.question,
            collection_name=request.collection_name,
            conversation_id=request.conversation_id,
        )
        return result
    except Exception as e:
        logger.error(f"Ask error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def ask_question_stream(request: AskRequest):
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
                question=request.question,
                collection_name=request.collection_name,
                conversation_id=request.conversation_id,
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

