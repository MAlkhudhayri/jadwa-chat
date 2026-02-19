from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ─── Chat ───────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    collection_name: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None


class Source(BaseModel):
    content: str
    metadata: dict
    score: float
    page: Optional[int] = None
    filename: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[Source]
    conversation_id: str
    collection_name: str


# ─── Documents ──────────────────────────────────────────

class DocumentUploadResponse(BaseModel):
    filename: str
    collection_name: str
    chunks_created: int
    status: str = "success"


class DocumentDeleteRequest(BaseModel):
    filename: str
    collection_name: str


# ─── Collections ────────────────────────────────────────

class CollectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    description: Optional[str] = None


class CollectionInfo(BaseModel):
    name: str
    document_count: int
    description: Optional[str] = None


class CollectionListResponse(BaseModel):
    collections: List[CollectionInfo]


# ─── Conversations ──────────────────────────────────────

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationMessage(BaseModel):
    role: MessageRole
    content: str
    timestamp: datetime
    sources: Optional[List[Source]] = None


class ConversationHistory(BaseModel):
    conversation_id: str
    messages: List[ConversationMessage]
    collection_name: str
    created_at: datetime
    updated_at: datetime


class ConversationListItem(BaseModel):
    conversation_id: str
    title: str
    collection_name: str
    message_count: int
    created_at: datetime
    updated_at: datetime


# ─── Health ─────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    qdrant_connected: bool
    db_connected: bool = False

