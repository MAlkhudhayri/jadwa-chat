import json
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


# ─── Auth ─────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ─── Chat ─────────────────────────────────────────────

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True)
    title = Column(String, default="New Conversation")
    collection_name = Column(String, nullable=False)
    user_id = Column(Integer, nullable=True)  # optional FK to users
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    sources_json = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CollectionMeta(Base):
    __tablename__ = "collection_meta"

    name = Column(String, primary_key=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ─── Engine & Session ──────────────────────────────────

_engine = None
_session_factory = None


def _normalize_db_url(url: str) -> str:
    """Auto-convert DATABASE_URL to async driver format.

    Railway/Heroku give postgresql://... but SQLAlchemy async needs
    postgresql+asyncpg://... — this handles the conversion automatically.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


async def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        db_url = _normalize_db_url(settings.DATABASE_URL)
        _engine = create_async_engine(db_url, echo=False)
    return _engine


async def get_session_factory():
    global _session_factory
    if _session_factory is None:
        engine = await get_engine()
        _session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory


async def init_db(retries: int = 5, delay: float = 3.0):
    """Create all tables. Retries on connection failure (DB may still be booting)."""
    import asyncio
    import logging

    logger = logging.getLogger(__name__)

    for attempt in range(1, retries + 1):
        try:
            engine = await get_engine()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("✅ Database tables created / verified")
            return
        except Exception as e:
            logger.warning(
                f"DB init attempt {attempt}/{retries} failed: {e}"
            )
            if attempt < retries:
                await asyncio.sleep(delay)
            else:
                logger.error("❌ Could not connect to database after all retries")
                raise


async def get_db_session() -> AsyncSession:
    factory = await get_session_factory()
    async with factory() as session:
        yield session

