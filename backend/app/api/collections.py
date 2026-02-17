import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.models.schemas import CollectionCreate, CollectionInfo, CollectionListResponse
from app.services.vectorstore import get_vectorstore_service
from app.core.database import CollectionMeta, get_session_factory

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


@router.get("/", response_model=CollectionListResponse)
async def list_collections():
    """List all available collections."""
    try:
        vs = get_vectorstore_service()
        collections = vs.list_collections()

        result = []
        for col in collections:
            desc = await _get_description(col["name"])
            result.append(CollectionInfo(
                name=col["name"],
                document_count=col["document_count"],
                description=desc,
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

