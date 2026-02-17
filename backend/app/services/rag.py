import logging
from typing import List, Optional, AsyncGenerator

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document

from app.config import get_settings
from app.services.vectorstore import get_vectorstore_service
from app.services.history import get_history_service
from app.models.schemas import Source

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are JadwaChat, an intelligent AI assistant created for Jadwa Investment.
Your role is to help users find and understand information from the company's document databases.

Instructions:
- Answer questions accurately based ONLY on the provided context from retrieved documents.
- If the context doesn't contain enough information to answer, say so clearly. Do not make up information.
- Always be professional, concise, and helpful.
- When citing information, reference the source document name and page if available.
- Support both English and Arabic queries naturally.
- Format your responses with markdown for readability when appropriate.
- If asked about something outside the provided context, politely explain that you can only answer based on the available documents.

Context from retrieved documents:
{context}
"""


class RAGService:
    """Core RAG pipeline orchestrator."""

    def __init__(self):
        self.settings = get_settings()
        self.vectorstore = get_vectorstore_service()
        self.history = get_history_service()
        self._llm: Optional[ChatOpenAI] = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=self.settings.LLM_MODEL,
                temperature=self.settings.TEMPERATURE,
                openai_api_key=self.settings.OPENAI_API_KEY,
                streaming=True,
                request_timeout=60,
            )
        return self._llm

    def _build_prompt(self) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}"),
        ])

    def _format_context(self, documents: List[dict]) -> str:
        """Format retrieved documents into context string."""
        if not documents:
            return "No relevant documents found."

        parts = []
        for i, doc in enumerate(documents, 1):
            source = doc.get("metadata", {}).get("source", "Unknown")
            page = doc.get("metadata", {}).get("page", "N/A")
            parts.append(
                f"[Document {i}] (Source: {source}, Page: {page})\n{doc['content']}"
            )
        return "\n\n---\n\n".join(parts)

    def _format_sources(self, documents: List[dict]) -> List[Source]:
        """Convert retrieved documents to Source objects."""
        sources = []
        for doc in documents:
            metadata = doc.get("metadata", {})
            sources.append(Source(
                content=doc["content"][:500],
                metadata=metadata,
                score=doc.get("score", 0.0),
                page=metadata.get("page"),
                filename=metadata.get("source"),
            ))
        return sources

    def _convert_history(self, history: List[dict]) -> list:
        """Convert history dicts to LangChain message objects."""
        messages = []
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        return messages

    async def chat(
        self,
        question: str,
        collection_name: str,
        conversation_id: Optional[str] = None,
    ) -> dict:
        """Full RAG chat: retrieve → augment → generate."""

        # 1. Create or validate conversation
        if conversation_id and await self.history.conversation_exists(conversation_id):
            pass
        else:
            conversation_id = await self.history.create_conversation(
                collection_name=collection_name,
                title=question[:80],
            )

        # 2. Get chat history
        chat_history = await self.history.get_chat_history_for_llm(conversation_id)

        # 3. Retrieve relevant documents
        retrieved_docs = await self.vectorstore.similarity_search(
            collection_name=collection_name,
            query=question,
        )

        # 4. Build context
        context = self._format_context(retrieved_docs)
        history_messages = self._convert_history(chat_history)

        # 5. Generate response
        prompt = self._build_prompt()
        chain = prompt | self.llm | StrOutputParser()

        answer = await chain.ainvoke({
            "context": context,
            "chat_history": history_messages,
            "question": question,
        })

        # 6. Save messages to history
        sources_dicts = [s.model_dump() for s in self._format_sources(retrieved_docs)]
        await self.history.add_message(conversation_id, "user", question)
        await self.history.add_message(
            conversation_id, "assistant", answer, sources=sources_dicts
        )

        return {
            "answer": answer,
            "sources": self._format_sources(retrieved_docs),
            "conversation_id": conversation_id,
            "collection_name": collection_name,
        }

    async def chat_stream(
        self,
        question: str,
        collection_name: str,
        conversation_id: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """Streaming RAG chat: yields tokens as they come."""

        # 1. Create or validate conversation
        if conversation_id and await self.history.conversation_exists(conversation_id):
            pass
        else:
            conversation_id = await self.history.create_conversation(
                collection_name=collection_name,
                title=question[:80],
            )

        # 2. Get chat history
        chat_history = await self.history.get_chat_history_for_llm(conversation_id)

        # 3. Retrieve relevant documents
        retrieved_docs = await self.vectorstore.similarity_search(
            collection_name=collection_name,
            query=question,
        )

        # 4. Build context
        context = self._format_context(retrieved_docs)
        history_messages = self._convert_history(chat_history)
        sources = self._format_sources(retrieved_docs)

        # Yield sources first
        yield {
            "type": "sources",
            "sources": [s.model_dump() for s in sources],
            "conversation_id": conversation_id,
        }

        # 5. Stream response
        prompt = self._build_prompt()
        chain = prompt | self.llm | StrOutputParser()

        full_response = ""
        async for token in chain.astream({
            "context": context,
            "chat_history": history_messages,
            "question": question,
        }):
            if token:
                full_response += token
                yield {"type": "token", "content": token}

        # 6. Save messages to history
        sources_dicts = [s.model_dump() for s in sources]
        await self.history.add_message(conversation_id, "user", question)
        await self.history.add_message(
            conversation_id, "assistant", full_response, sources=sources_dicts
        )

        # Final event
        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "collection_name": collection_name,
        }


# Singleton
_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service

