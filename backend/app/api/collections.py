import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from app.models.schemas import CollectionCreate, CollectionInfo, CollectionListResponse
from app.services.vectorstore import get_vectorstore_service
from app.core.database import CollectionMeta, get_session_factory
from app.models.timeseries import SeriesCatalog, Observation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collections", tags=["Collections"])


async def _get_description(name: str) -> Optional[str]:
    """Get collection description from metadata DB."""
    factory = await get_session_factory()
    async with factory() as session:
        stmt = select(CollectionMeta.description).where(CollectionMeta.name == name)
        result = await session.execute(stmt)
        return result.scalar()


async def _save_description(name: str, description: Optional[str]) -> None:
    """Save collection description to metadata DB."""
    factory = await get_session_factory()
    async with factory() as session:
        existing = await session.get(CollectionMeta, name)
        if existing:
            existing.description = description
        else:
            session.add(CollectionMeta(name=name, description=description))
        await session.commit()


async def _get_ts_count(collection_name: str) -> int:
    """Count time series observations for a collection."""
    try:
        factory = await get_session_factory()
        session = factory()
        try:
            result = await session.execute(
                select(func.count(Observation.id))
                .join(SeriesCatalog, Observation.series_id == SeriesCatalog.series_id)
                .where(SeriesCatalog.collection_name == collection_name)
            )
            return result.scalar() or 0
        finally:
            await session.close()
    except Exception:
        return 0


@router.get("/", response_model=CollectionListResponse)
async def list_collections():
    """List all available collections (Qdrant + virtual All Databases)."""
    try:
        vs = get_vectorstore_service()
        collections = vs.list_collections()

        result = []
        total_docs = 0

        for col in collections:
            desc = await _get_description(col["name"])
            ts_count = await _get_ts_count(col["name"])
            doc_count = col["document_count"] + ts_count
            total_docs += doc_count
            result.append(CollectionInfo(
                name=col["name"],
                document_count=doc_count,
                description=desc,
            ))

        # Also count time series with no collection (pre-loaded data)
        factory = await get_session_factory()
        session = factory()
        try:
            preloaded = await session.execute(
                select(func.count(Observation.id))
                .join(SeriesCatalog, Observation.series_id == SeriesCatalog.series_id)
                .where(
                    (SeriesCatalog.collection_name == None) |
                    (SeriesCatalog.collection_name == "")
                )
            )
            preloaded_count = preloaded.scalar() or 0
            total_docs += preloaded_count
        finally:
            await session.close()

        # Add "All Databases" virtual entry at the top
        result.insert(0, CollectionInfo(
            name="all-databases",
            document_count=total_docs,
            description="Query across all databases and pre-loaded data",
        ))

        return CollectionListResponse(collections=result)
    except Exception as e:
        logger.error(f"List collections error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=CollectionInfo)
async def create_collection(request: CollectionCreate):
    """Create a new collection."""
    try:
        vs = get_vectorstore_service()
        vs.create_collection(request.name)
        await _save_description(request.name, request.description)

        return CollectionInfo(
            name=request.name,
            document_count=0,
            description=request.description,
        )
    except Exception as e:
        logger.error(f"Create collection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{collection_name}", response_model=CollectionInfo)
async def get_collection(collection_name: str):
    """Get info about a specific collection."""
    try:
        vs = get_vectorstore_service()
        info = vs.get_collection_info(collection_name)
        desc = await _get_description(collection_name)

        return CollectionInfo(
            name=info["name"],
            document_count=info["document_count"],
            description=desc,
        )
    except Exception as e:
        logger.error(f"Get collection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{collection_name}")
async def delete_collection(collection_name: str):
    """Delete a collection and all its documents."""
    try:
        vs = get_vectorstore_service()
        vs.delete_collection(collection_name)

        # Clean up metadata
        factory = await get_session_factory()
        async with factory() as session:
            existing = await session.get(CollectionMeta, collection_name)
            if existing:
                await session.delete(existing)
                await session.commit()

        return {"status": "deleted", "collection_name": collection_name}
    except Exception as e:
        logger.error(f"Delete collection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

