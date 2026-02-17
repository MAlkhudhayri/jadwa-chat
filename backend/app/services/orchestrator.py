"""
Orchestrator — routes user queries to the right pipeline:
  - Numeric/data questions → series discovery → analytics tools
  - Document/definition questions → document RAG (Qdrant)
  - Mixed questions → both pipelines
"""

import json
import logging
import re
from datetime import date
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.config import get_settings
from app.services.series_discovery import get_discovery_service
from app.services import analytics
from app.services.rag import get_rag_service

logger = logging.getLogger(__name__)

INTENT_KEYWORDS_DATA = {
    "how much", "what is the", "what was", "price", "production", "volume",
    "rate", "ratio", "growth", "change", "trend", "compare", "latest",
    "current", "historical", "data", "number", "figure", "value",
    "increase", "decrease", "decline", "rise", "fell", "grew",
    "brent", "oil", "crude", "gdp", "debt", "reserve", "deposit",
    "loan", "export", "import", "supply", "demand", "revenue",
    "expenditure", "saibor", "sofr", "npl", "roe", "ldr",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "2005", "2006", "2007", "2008", "2009", "2010", "2011", "2012",
    "2013", "2014", "2015", "2016", "2017", "2018", "2019", "2020",
    "2021", "2022", "2023", "2024", "2025", "2026",
    "mn bbl", "sar", "usd", "bps", "percent",
}


def classify_intent(question: str) -> str:
    """Classify question intent: 'data', 'document', or 'mixed'."""
    q_lower = question.lower()

    data_score = 0
    for kw in INTENT_KEYWORDS_DATA:
        if kw in q_lower:
            data_score += 1

    if data_score >= 2:
        return "data"
    elif data_score == 1:
        return "mixed"
    return "document"


def _extract_date_range(question: str) -> tuple:
    """Extract date hints from the question."""
    q_lower = question.lower()
    months = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "jun": "06", "jul": "07", "aug": "08", "sep": "09",
        "oct": "10", "nov": "11", "dec": "12",
    }

    year_match = re.search(r"(20\d{2})", q_lower)
    month_match = None
    for name, num in months.items():
        if name in q_lower:
            month_match = num
            break

    if year_match and month_match:
        y = year_match.group(1)
        start = f"{y}-{month_match}-01"
        # End of month
        m = int(month_match)
        if m == 12:
            end = f"{int(y)+1}-01-01"
        else:
            end = f"{y}-{int(month_match)+1:02d}-01"
        return start, end
    elif year_match:
        y = year_match.group(1)
        return f"{y}-01-01", f"{y}-12-31"

    return None, None


class Orchestrator:
    def __init__(self):
        self.settings = get_settings()
        self._llm = None
        self.discovery = get_discovery_service()

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=self.settings.LLM_MODEL,
                temperature=self.settings.TEMPERATURE,
                openai_api_key=self.settings.OPENAI_API_KEY,
                request_timeout=60,
            )
        return self._llm

    async def ask(self, question: str, collection_name: Optional[str] = None,
                  conversation_id: Optional[str] = None) -> dict:
        """Main entry point — classify, discover, execute, assemble."""
        intent = classify_intent(question)
        logger.info(f"Intent: {intent} for: {question[:80]}")

        series_used = []
        tools_called = []
        data_context = ""
        citations = []
        doc_sources = []

        if intent in ("data", "mixed"):
            data_context, series_used, tools_called, citations = await self._handle_data(
                question, collection_name=collection_name
            )

        # For document/mixed intent with a collection, also query document RAG
        if intent in ("document", "mixed") and collection_name:
            try:
                rag = get_rag_service()
                rag_result = await rag.chat(question, collection_name, conversation_id)
                if intent == "document":
                    # Pure document query — return RAG result directly
                    return {
                        "answer": rag_result["answer"],
                        "intent": intent,
                        "series_used": [],
                        "tools_called": ["document_rag"],
                        "conversation_id": rag_result.get("conversation_id", ""),
                        "citations": "",
                        "sources": rag_result.get("sources", []),
                    }
                else:
                    # Mixed — combine document context with data
                    doc_sources = rag_result.get("sources", [])
                    conversation_id = rag_result.get("conversation_id", conversation_id)
            except Exception as e:
                logger.warning(f"Document RAG failed: {e}")

        # Generate answer using LLM (for data and mixed intents)
        answer = await self._generate_answer(question, data_context, intent)

        # Build citation text
        citation_text = "\n".join(citations) if citations else ""

        return {
            "answer": answer,
            "intent": intent,
            "series_used": series_used,
            "tools_called": tools_called,
            "conversation_id": conversation_id or "",
            "citations": citation_text,
            "sources": [s.model_dump() if hasattr(s, 'model_dump') else s for s in doc_sources],
        }

    async def _handle_data(self, question: str,
                           collection_name: Optional[str] = None) -> tuple:
        """Handle data/numeric questions via series discovery + analytics."""
        # 1. Discover relevant series (scoped to collection)
        candidates = await self.discovery.search(
            question, top_k=3, collection_name=collection_name
        )
        if not candidates:
            return "No matching time series found.", [], [], []

        series_used = [c["series_id"] for c in candidates]
        tools_called = []
        data_parts = []
        citations = []

        # 2. Extract date range
        start, end = _extract_date_range(question)

        # 3. Execute appropriate tool for each candidate
        for candidate in candidates[:2]:  # Top 2 series
            sid = candidate["series_id"]

            if start and end:
                # Specific date query → get_series
                result = await analytics.get_series(sid, start=start, end=end)
                tools_called.append(f"get_series({sid})")

                if "error" not in result and result.get("observations"):
                    obs = result["observations"]
                    obs_text = ", ".join(
                        f"{o['date']}: {o['value']}" for o in obs[:10]
                    )
                    data_parts.append(
                        f"**{candidate['name']}** ({candidate['unit']}): {obs_text}"
                    )
                    if result.get("staleness_days") is not None:
                        data_type = "forecast" if any(
                            o["date"] > str(date.today()) for o in obs
                            if isinstance(o.get("date"), str)
                        ) else "actual"

                        citation = (
                            f"— {sid} — {candidate['name']}: {candidate['unit']}, "
                            f"({data_type}) Source: {candidate['source']}"
                        )
                        if candidate.get("source_url"):
                            citation += f" · [{candidate['source']} Data]({candidate.get('source_url', '')})"
                        if result["staleness_days"] and result["staleness_days"] > 90:
                            citation += (
                                f"\n⚠️ Warning: Last data point is {result['observations'][-1]['date']} "
                                f"({result['staleness_days']} days ago)."
                            )
                        citations.append(citation)
                elif "error" in result:
                    data_parts.append(f"**{candidate['name']}**: {result['error']}")
            else:
                # General query → latest
                result = await analytics.latest(sid)
                tools_called.append(f"latest({sid})")

                if "error" not in result:
                    data_type = "forecast" if result.get("is_forecast") else "actual"
                    data_parts.append(
                        f"**{candidate['name']}**: {result.get('value')} {candidate['unit']} "
                        f"(as of {result.get('date')}, {data_type})"
                    )
                    citation = (
                        f"— {sid} — {candidate['name']}: {candidate['unit']}, "
                        f"({data_type}) Source: {candidate['source']}"
                    )
                    if candidate.get("source_url"):
                        citation += f" · [{candidate['source']}]({candidate.get('source_url', '')})"
                    if result.get("staleness_days", 0) > 90:
                        citation += (
                            f"\n⚠️ Warning: Last data point is {result['date']} "
                            f"({result['staleness_days']} days ago). Source may have newer data."
                        )
                    citations.append(citation)
                else:
                    data_parts.append(f"**{candidate['name']}**: {result['error']}")

        data_context = "\n".join(data_parts) if data_parts else "No data found."
        return data_context, series_used, tools_called, citations

    async def _generate_answer(self, question: str, data_context: str, intent: str) -> str:
        """Generate a natural language answer using the LLM."""
        if intent == "document":
            system = (
                "You are JadwaChat, an AI assistant for Jadwa Investment. "
                "Answer the user's question. If you don't have data, say so clearly."
            )
            context_block = ""
        else:
            system = (
                "You are JadwaChat, a financial data assistant for Jadwa Investment.\n"
                "You have access to Saudi macroeconomic data (oil, fiscal, banking, etc.).\n"
                "Use the data below to answer accurately. Include numbers with units.\n"
                "Support bilingual (English + Arabic) responses when the user writes in Arabic.\n"
                "Be concise and professional."
            )
            context_block = f"\n\nData from analytics tools:\n{data_context}"

        prompt = ChatPromptTemplate.from_messages([
            ("system", system + context_block),
            ("human", "{question}"),
        ])

        chain = prompt | self.llm | StrOutputParser()
        answer = await chain.ainvoke({"question": question})
        return answer


_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator

