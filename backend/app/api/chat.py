import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationHistory,
    ConversationListItem,
)
from app.services.rag import get_rag_service
from app.services.history import get_history_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a message and get a complete response."""
    try:
        rag = get_rag_service()
        result = await rag.chat(
            question=request.message,
            collection_name=request.collection_name,
            conversation_id=request.conversation_id,
        )
        return ChatResponse(**result)
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """Send a message and get a streaming response via SSE."""

    async def event_generator():
        try:
            rag = get_rag_service()
            async for event in rag.chat_stream(
                question=request.message,
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


# ─── Conversation Management ─────────────────────────────

@router.get("/conversations", response_model=list[ConversationListItem])
async def list_conversations(
    collection_name: Optional[str] = Query(None),
):
    """List all conversations, optionally filtered by collection."""
    try:
        history = get_history_service()
        return await history.list_conversations(collection_name=collection_name)
    except Exception as e:
        logger.error(f"List conversations error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get messages from a specific conversation."""
    try:
        history = get_history_service()
        exists = await history.conversation_exists(conversation_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = await history.get_conversation_messages(conversation_id)
        collection = await history.get_conversation_collection(conversation_id)

        return {
            "conversation_id": conversation_id,
            "collection_name": collection,
            "messages": [m.model_dump() for m in messages],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get conversation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation and all its messages."""
    try:
        history = get_history_service()
        exists = await history.conversation_exists(conversation_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Conversation not found")

        await history.delete_conversation(conversation_id)
        return {"status": "deleted", "conversation_id": conversation_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete conversation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

