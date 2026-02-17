import json
import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Conversation, Message, get_session_factory
from app.models.schemas import (
    ConversationMessage,
    ConversationHistory,
    ConversationListItem,
    Source,
    MessageRole,
)

logger = logging.getLogger(__name__)


class HistoryService:
    """Manages conversation history in SQLite."""

    async def _get_session(self) -> AsyncSession:
        factory = await get_session_factory()
        return factory()

    async def create_conversation(
        self, collection_name: str, title: str = "New Conversation"
    ) -> str:
        """Create a new conversation and return its ID."""
        session = await self._get_session()
        try:
            conv_id = str(uuid4())
            conversation = Conversation(
                id=conv_id,
                title=title,
                collection_name=collection_name,
            )
            session.add(conversation)
            await session.commit()
            return conv_id
        finally:
            await session.close()

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources: Optional[List[dict]] = None,
    ) -> None:
        """Add a message to a conversation."""
        session = await self._get_session()
        try:
            sources_json = json.dumps(sources) if sources else None
            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                sources_json=sources_json,
            )
            session.add(message)

            # Update conversation timestamp and title if first user message
            stmt = select(func.count()).where(
                Message.conversation_id == conversation_id
            )
            result = await session.execute(stmt)
            count = result.scalar()

            if count == 0 and role == "user":
                # Set title from first user message
                title = content[:80] + ("..." if len(content) > 80 else "")
                stmt = (
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(title=title, updated_at=datetime.now(timezone.utc))
                )
                await session.execute(stmt)

            await session.commit()
        finally:
            await session.close()

    async def get_conversation_messages(
        self,
        conversation_id: str,
        limit: int = 20,
    ) -> List[ConversationMessage]:
        """Get recent messages from a conversation."""
        session = await self._get_session()
        try:
            stmt = (
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.timestamp.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            messages = result.scalars().all()

            return [
                ConversationMessage(
                    role=MessageRole(msg.role),
                    content=msg.content,
                    timestamp=msg.timestamp,
                    sources=(
                        [Source(**s) for s in json.loads(msg.sources_json)]
                        if msg.sources_json
                        else None
                    ),
                )
                for msg in reversed(messages)
            ]
        finally:
            await session.close()

    async def get_chat_history_for_llm(
        self,
        conversation_id: str,
        limit: int = 10,
    ) -> List[dict]:
        """Get conversation history formatted for the LLM."""
        messages = await self.get_conversation_messages(conversation_id, limit)
        return [
            {"role": msg.role.value, "content": msg.content}
            for msg in messages
        ]

    async def list_conversations(
        self,
        collection_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[ConversationListItem]:
        """List conversations, optionally filtered by collection."""
        session = await self._get_session()
        try:
            stmt = select(Conversation).order_by(Conversation.updated_at.desc())

            if collection_name:
                stmt = stmt.where(Conversation.collection_name == collection_name)

            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            conversations = result.scalars().all()

            items = []
            for conv in conversations:
                # Get message count
                count_stmt = select(func.count()).where(
                    Message.conversation_id == conv.id
                )
                count_result = await session.execute(count_stmt)
                msg_count = count_result.scalar()

                items.append(
                    ConversationListItem(
                        conversation_id=conv.id,
                        title=conv.title,
                        collection_name=conv.collection_name,
                        message_count=msg_count,
                        created_at=conv.created_at,
                        updated_at=conv.updated_at,
                    )
                )

            return items
        finally:
            await session.close()

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages."""
        session = await self._get_session()
        try:
            await session.execute(
                delete(Message).where(Message.conversation_id == conversation_id)
            )
            await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await session.commit()
            return True
        finally:
            await session.close()

    async def conversation_exists(self, conversation_id: str) -> bool:
        """Check if a conversation exists."""
        session = await self._get_session()
        try:
            stmt = select(Conversation).where(Conversation.id == conversation_id)
            result = await session.execute(stmt)
            return result.scalar() is not None
        finally:
            await session.close()

    async def get_conversation_collection(self, conversation_id: str) -> Optional[str]:
        """Get the collection name for a conversation."""
        session = await self._get_session()
        try:
            stmt = select(Conversation.collection_name).where(
                Conversation.id == conversation_id
            )
            result = await session.execute(stmt)
            return result.scalar()
        finally:
            await session.close()


# Singleton
_history_service: Optional[HistoryService] = None


def get_history_service() -> HistoryService:
    global _history_service
    if _history_service is None:
        _history_service = HistoryService()
    return _history_service

