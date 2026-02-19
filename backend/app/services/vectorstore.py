import asyncio
import logging
from typing import List, Optional, Dict, Any

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_core.documents import Document

from app.config import get_settings

logger = logging.getLogger(__name__)


class VectorStoreService:
    """Manages Qdrant collections and vector operations."""

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[QdrantClient] = None
        self._embeddings: Optional[OpenAIEmbeddings] = None

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(
                host=self.settings.QDRANT_HOST,
                port=self.settings.QDRANT_PORT,
                api_key=self.settings.QDRANT_API_KEY or None,
            )
        return self._client

    @property
    def embeddings(self) -> OpenAIEmbeddings:
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings(
                model=self.settings.EMBEDDING_MODEL,
                dimensions=self.settings.EMBEDDING_DIMENSIONS,
                openai_api_key=self.settings.OPENAI_API_KEY,
            )
        return self._embeddings

    def is_connected(self) -> bool:
        """Check if Qdrant is reachable."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def create_collection(self, collection_name: str) -> bool:
        """Create a new Qdrant collection if it doesn't exist."""
        try:
            collections = self.client.get_collections().collections
            existing = [c.name for c in collections]

            if collection_name in existing:
                logger.info(f"Collection '{collection_name}' already exists.")
                return True

            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=self.settings.EMBEDDING_DIMENSIONS,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(f"Created collection '{collection_name}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to create collection '{collection_name}': {e}")
            raise

    def delete_collection(self, collection_name: str) -> bool:
        """Delete a Qdrant collection."""
        try:
            self.client.delete_collection(collection_name)
            logger.info(f"Deleted collection '{collection_name}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete collection '{collection_name}': {e}")
            raise

    def list_collections(self) -> List[Dict[str, Any]]:
        """List all collections with their point counts."""
        try:
            collections = self.client.get_collections().collections
            result = []
            for col in collections:
                info = self.client.get_collection(col.name)
                result.append({
                    "name": col.name,
                    "document_count": info.points_count or 0,
                })
            return result
        except Exception as e:
            logger.error(f"Failed to list collections: {e}")
            raise

    def get_collection_info(self, collection_name: str) -> Dict[str, Any]:
        """Get info about a specific collection."""
        try:
            info = self.client.get_collection(collection_name)
            return {
                "name": collection_name,
                "document_count": info.points_count or 0,
            }
        except Exception as e:
            logger.error(f"Failed to get collection info: {e}")
            raise

    async def add_documents(
        self,
        collection_name: str,
        documents: List[Document],
    ) -> int:
        """Add documents to a Qdrant collection. Returns number of chunks added.
        Runs in a thread pool to avoid blocking the event loop during embedding generation.
        """
        self.create_collection(collection_name)

        store = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
            embedding=self.embeddings,
        )

        # Run in thread pool — embedding + Qdrant upsert is blocking I/O
        ids = await asyncio.to_thread(store.add_documents, documents)
        logger.info(f"Added {len(ids)} chunks to '{collection_name}'.")
        return len(ids)

    def get_retriever(self, collection_name: str, top_k: Optional[int] = None):
        """Get a LangChain retriever for a collection."""
        k = top_k or self.settings.TOP_K

        store = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
            embedding=self.embeddings,
        )

        return store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": k},
        )

    async def similarity_search(
        self,
        collection_name: str,
        query: str,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Perform similarity search and return results with scores.
        Runs in a thread pool to avoid blocking the event loop during embedding + search.
        """
        k = top_k or self.settings.TOP_K

        store = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
            embedding=self.embeddings,
        )

        # Blocking I/O: embedding generation + Qdrant query
        results = await asyncio.to_thread(
            store.similarity_search_with_score, query, k=k
        )

        return [
            {
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": score,
            }
            for doc, score in results
        ]

    # Internal collections that should be excluded from cross-collection search
    INTERNAL_COLLECTIONS = {"series_catalog_embeddings"}

    async def similarity_search_all(
        self,
        query: str,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Search across ALL user-facing Qdrant collections in parallel, merge & rank."""
        k = top_k or self.settings.TOP_K

        try:
            collections = self.list_collections()
        except Exception as e:
            logger.error(f"Failed to list collections for cross-search: {e}")
            return []

        # Filter to searchable collections
        searchable = [
            col for col in collections
            if col["name"] not in self.INTERNAL_COLLECTIONS
            and not col["name"].startswith("series_catalog_embeddings")
            and col.get("document_count", 0) > 0
        ]

        if not searchable:
            return []

        async def _search_one(name: str) -> List[Dict[str, Any]]:
            """Search a single collection (runs in thread pool)."""
            try:
                store = QdrantVectorStore(
                    client=self.client,
                    collection_name=name,
                    embedding=self.embeddings,
                )
                results = await asyncio.to_thread(
                    store.similarity_search_with_score, query, k=k
                )
                hits = []
                for doc, score in results:
                    meta = doc.metadata.copy()
                    meta["_collection_name"] = name
                    hits.append({
                        "content": doc.page_content,
                        "metadata": meta,
                        "score": score,
                    })
                return hits
            except Exception as e:
                logger.warning(f"Cross-search failed for '{name}': {e}")
                return []

        # Run all collection searches in parallel
        batch_results = await asyncio.gather(
            *[_search_one(col["name"]) for col in searchable]
        )

        all_results = [hit for hits in batch_results for hit in hits]

        # Sort by score (descending for cosine) and return top-k
        all_results.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"Cross-collection search: {len(all_results)} total results "
                    f"from {len(searchable)} collections (parallel), returning top {k}")
        return all_results[:k]

    async def delete_by_metadata(
        self,
        collection_name: str,
        metadata_key: str,
        metadata_value: str,
    ) -> bool:
        """Delete points matching a metadata filter."""
        try:
            self.client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key=f"metadata.{metadata_key}",
                                match=models.MatchValue(value=metadata_value),
                            )
                        ]
                    )
                ),
            )
            logger.info(
                f"Deleted documents with {metadata_key}={metadata_value} "
                f"from '{collection_name}'."
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete documents: {e}")
            raise


# Singleton
_vectorstore_service: Optional[VectorStoreService] = None


def get_vectorstore_service() -> VectorStoreService:
    global _vectorstore_service
    if _vectorstore_service is None:
        _vectorstore_service = VectorStoreService()
    return _vectorstore_service

