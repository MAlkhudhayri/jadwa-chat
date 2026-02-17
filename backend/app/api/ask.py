"""Unified ask endpoint — routes through the orchestrator."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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

