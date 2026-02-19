"""
Orchestrator — routes user queries to the right pipeline:
  - Numeric/data questions → series discovery → analytics tools
  - Document/definition questions → document RAG (Qdrant)
  - Mixed questions → both pipelines
  - General/greeting questions → LLM general knowledge or web search

Maintains conversation memory via the history service.
Intent classification uses a lightweight LLM call (GPT-4o-mini, ~100 tokens)
instead of brittle keyword matching.
"""

import json
import logging
import re
from datetime import date
from typing import Optional, List, AsyncGenerator

from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage

from app.config import get_settings
from app.services.series_discovery import get_discovery_service
from app.services import analytics
from app.services.rag import get_rag_service
from app.services.history import get_history_service
from app.services.web_search import get_web_search_service

logger = logging.getLogger(__name__)


def _fmt_num(v) -> str:
    """Format a number for LLM readability: commas + 2 decimal places."""
    if v is None:
        return "N/A"
    try:
        f = float(v)
        if abs(f) >= 1_000:
            return f"{f:,.2f}"
        return f"{f:.4f}" if abs(f) < 1 else f"{f:.2f}"
    except (ValueError, TypeError):
        return str(v)

# ──────────────────────────────────────────────────────────────────────────────
# LLM-based intent classifier  (replaces all hardcoded keyword lists)
# ──────────────────────────────────────────────────────────────────────────────

CLASSIFY_SYSTEM_PROMPT = """\
You are an intent classifier for a financial data chat assistant.
The assistant has access to:
  - Time-series databases (oil prices, GDP, reserves, banking ratios, etc.)
  - Uploaded documents and reports (PDF, DOCX, spreadsheets)
  - Web search (as a fallback for current events)

Classify the user's question into EXACTLY ONE of these intents:
  data      - The user wants a specific number, statistic, time-series value,
              comparison, trend, or quantitative answer that would come from
              a structured database. Examples: "Oil production in July 2024?",
              "Compare GDP growth 2020 vs 2023", "Latest Brent price".
  document  - The user wants qualitative information, definitions, methodology,
              summaries, or analysis from uploaded reports/documents.
              Examples: "Summarize the Q3 report", "What is SAIBOR?",
              "Tell me about the January 2024 report".
  mixed     - The question needs BOTH data AND document context.
              Examples: "How does the report explain the GDP decline in 2023?"
  general   - Greetings, meta questions, off-topic, or anything that does NOT
              need the financial databases or documents.
              Examples: "Hello", "Who are you?", "Who won the Champions League?",
              "What's the weather?", "مرحبا"

Respond with ONLY a valid JSON object, no markdown, no explanation.
Format: {{"intent": "<one of: data, document, mixed, general>", "is_followup": <true or false>}}

Set is_followup to true if the question looks like a continuation of a prior
conversation (e.g. "more?", "go on", "what about exports?").\
"""

_classifier_llm: Optional[ChatOpenAI] = None


def _get_classifier_llm() -> ChatOpenAI:
    """Lightweight LLM for intent classification (~100 tokens, <$0.001)."""
    global _classifier_llm
    if _classifier_llm is None:
        settings = get_settings()
        _classifier_llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            openai_api_key=settings.OPENAI_API_KEY,
            max_tokens=60,
            request_timeout=10,
        )
    return _classifier_llm


async def classify_intent(question: str, chat_history: Optional[List[dict]] = None) -> dict:
    """Classify question intent using GPT-4o-mini.

    Returns:
        {"intent": "data"|"document"|"mixed"|"general", "is_followup": bool}
    """
    try:
        llm = _get_classifier_llm()

        # Include last user message for context if available
        history_hint = ""
        if chat_history:
            last_user = next(
                (m["content"] for m in reversed(chat_history) if m["role"] == "user"),
                None,
            )
            if last_user:
                history_hint = f"\n\nPrevious user message: \"{last_user[:120]}\""

        prompt = ChatPromptTemplate.from_messages([
            ("system", CLASSIFY_SYSTEM_PROMPT),
            ("human", "{question}{history_hint}"),
        ])
        chain = prompt | llm | StrOutputParser()
        raw = await chain.ainvoke({"question": question, "history_hint": history_hint})

        # Parse JSON — strip markdown fences if any
        raw = raw.strip().strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        result = json.loads(raw)

        intent = result.get("intent", "document")
        if intent not in ("data", "document", "mixed", "general"):
            intent = "document"

        classified = {
            "intent": intent,
            "is_followup": result.get("is_followup", False),
        }
        logger.info(f"LLM intent: {classified} for: {question[:80]}")
        return classified

    except Exception as e:
        logger.warning(f"LLM intent classification failed ({e}), falling back to 'mixed'")
        return {"intent": "mixed", "is_followup": False}


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

    year_match = re.search(r"((?:19|20)\d{2})", q_lower)
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
        self.history = get_history_service()

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

    def _convert_history(self, history: List[dict]) -> list:
        """Convert history dicts to LangChain message objects."""
        messages = []
        for msg in history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        return messages

    async def ask(self, question: str, collection_name: Optional[str] = None,
                  conversation_id: Optional[str] = None) -> dict:
        """Main entry point — classify, discover, execute, assemble.
        
        Strategy:
        1. Create or validate conversation (for memory).
        2. Load chat history.
        3. Query Qdrant for document/entity context.
        4. For data/mixed intent, query structured time series (SQLite).
        5. Merge all context + history → LLM → save messages.
        """
        # ─── 0. Conversation management ───────────────────────────────
        if conversation_id and await self.history.conversation_exists(conversation_id):
            pass
        else:
            conversation_id = await self.history.create_conversation(
                collection_name=collection_name or "all-databases",
                title=question[:80],
            )

        # Load chat history for multi-turn context
        chat_history = await self.history.get_chat_history_for_llm(conversation_id)
        history_messages = self._convert_history(chat_history)

        # ─── Intent classification (LLM-based, no hardcoded keywords) ─
        classification = await classify_intent(question, chat_history)
        intent = classification["intent"]
        is_followup = classification["is_followup"]

        series_used = []
        tools_called = []
        data_context = ""
        doc_context = ""
        citations = []
        doc_sources = []

        # ─── Contextual query rewriting for follow-ups ────────────────
        search_query = question
        if is_followup and chat_history:
            search_query = self._rewrite_query_for_search(question, chat_history)
            if search_query != question:
                logger.info(f"Rewritten search query: {search_query[:100]}")

        # ─── 1. Query Qdrant for document/entity context (skip for general) ─
        # Always search ALL collections so every tab has full access
        if intent != "general":
            try:
                vs = get_rag_service().vectorstore
                retrieved_docs = await vs.similarity_search_all(
                    query=search_query,
                )
                tools_called.append("document_rag")

                if retrieved_docs:
                    doc_parts = []
                    for doc in retrieved_docs:
                        content = doc.get("content", "")
                        if content:
                            doc_parts.append(content)
                            metadata = doc.get("metadata", {})
                            from app.models.schemas import Source
                            doc_sources.append(Source(
                                content=content[:500],
                                metadata=metadata,
                                score=doc.get("score", 0.0),
                                page=metadata.get("page"),
                                filename=metadata.get("source"),
                            ))
                    if doc_parts:
                        doc_context = "\n\n".join(doc_parts)

            except Exception as e:
                logger.warning(f"Document RAG failed: {e}")

        # ─── 2. For data/mixed, also query structured time series ──────
        # Always search ALL series (no collection filter)
        if intent in ("data", "mixed"):
            data_context, series_used, ts_tools, citations = await self._handle_data(
                question, collection_name=None
            )
            tools_called.extend(ts_tools)

        # ─── 3. Merge context and check if we have relevant data ──────
        merged_context = ""
        has_db_context = False
        knowledge_source = "database"

        # Put structured data FIRST so the LLM prioritises exact numbers
        no_data_phrases = {"No data found.", "No matching time series found."}
        if data_context and data_context not in no_data_phrases:
            merged_context += (
                "STRUCTURED TIME SERIES DATA (use these exact numbers when answering):\n"
                f"{data_context}\n\n"
            )
            has_db_context = True

        if doc_context:
            merged_context += (
                "Supporting documents (use only if structured data above is insufficient):\n"
                f"{doc_context}\n\n"
            )
            has_db_context = True

        # ─── 3b. FALLBACK: web search if no relevant DB context ───────
        web_citations = []
        if not has_db_context:
            is_greeting = (intent == "general" and len(question.split()) <= 5)

            if not is_greeting:
                logger.info("No relevant DB context — falling back to web search")
                try:
                    web_service = get_web_search_service()
                    web_results = await web_service.search(question, max_results=5)

                    if web_results:
                        web_context = web_service.format_context(web_results)
                        merged_context = f"Web search results:\n{web_context}\n\n"
                        web_citations = web_service.format_citations(web_results)
                        knowledge_source = "web_search"
                        tools_called.append("web_search")

                        from app.models.schemas import Source
                        for r in web_results:
                            doc_sources.append(Source(
                                content=f"{r.title}\n{r.snippet}",
                                metadata={
                                    "source": r.url,
                                    "title": r.title,
                                    "type": "web_search",
                                },
                                score=0.0,
                                page=None,
                                filename=r.url,
                            ))
                    else:
                        knowledge_source = "general_knowledge"
                except Exception as e:
                    logger.warning(f"Web search fallback failed: {e}")
                    knowledge_source = "general_knowledge"

            if not merged_context.strip():
                merged_context = (
                    "No specific data found in the databases or web. "
                    "You may answer from your general knowledge, but clearly "
                    "state that the answer is from general knowledge, not from "
                    "JadwaChat's databases."
                )
                knowledge_source = "general_knowledge"

        # ─── 4. Generate answer ───────────────────────────────────────
        answer = await self._generate_answer(
            question, merged_context, intent, history_messages, knowledge_source
        )

        # ─── 5. Save messages to conversation history ─────────────────
        sources_dicts = [s.model_dump() for s in doc_sources]
        await self.history.add_message(conversation_id, "user", question)
        await self.history.add_message(
            conversation_id, "assistant", answer, sources=sources_dicts
        )

        # Build citation text
        all_citations = citations + web_citations
        citation_text = "\n".join(all_citations) if all_citations else ""

        return {
            "answer": answer,
            "intent": intent,
            "series_used": series_used,
            "tools_called": tools_called,
            "conversation_id": conversation_id or "",
            "citations": citation_text,
            "sources": [s.model_dump() if hasattr(s, 'model_dump') else s for s in doc_sources],
            "knowledge_source": knowledge_source,
        }

    def _rewrite_query_for_search(self, question: str, chat_history: List[dict]) -> str:
        """Rewrite follow-up queries using recent conversation context.

        Called only when the LLM classifier flags is_followup=True.
        Prepends the prior user topic so Qdrant/discovery retrieve relevant data.
        """
        if not chat_history:
            return question

        # Find the most recent user message topic
        for msg in reversed(chat_history[-4:]):  # Last 2 exchanges
            if msg["role"] == "user":
                prior = msg["content"]
                augmented = f"{prior} {question}"
                return augmented

        return question

    # ─── Tool detection helpers ─────────────────────────────────────────────

    def _detect_tool(self, question: str) -> str:
        """Detect which analytics tool to use based on question keywords.

        Returns one of: compare, top_movers, rolling, change, get_series, latest, auto
        """
        q = question.lower()

        # Compare / correlation — needs two series
        if any(kw in q for kw in (
            "compare", "correlation", "vs", "versus", "relationship",
            "correlate", "between", "against",
        )):
            return "compare"

        # Top movers / biggest changes
        if any(kw in q for kw in (
            "top mover", "biggest change", "largest change", "most changed",
            "top change", "biggest mover", "which changed the most",
            "what moved", "what changed the most", "significant change",
        )):
            return "top_movers"

        # Rolling average / moving average / trend
        if any(kw in q for kw in (
            "rolling", "moving average", "rolling average",
            "smoothed", "12-month average", "6-month average",
            "rolling mean", "rolling std", "volatility over",
        )):
            return "rolling"

        # Change — month-over-month, year-over-year, etc.
        if any(kw in q for kw in (
            "change", "growth", "increase", "decrease", "decline",
            "mom", "yoy", "qoq", "month-over-month", "year-over-year",
            "quarter-over-quarter", "grew", "fell", "dropped", "rose",
            "percent change", "% change",
        )):
            return "change"

        # Specific date range → get_series
        start, end = _extract_date_range(question)
        if start and end:
            return "get_series"

        return "latest"

    def _detect_change_method(self, question: str) -> str:
        """Detect the change period: YoY, MoM, or QoQ."""
        q = question.lower()
        if any(kw in q for kw in ("yoy", "year-over-year", "annual", "yearly")):
            return "YoY"
        if any(kw in q for kw in ("qoq", "quarter-over-quarter", "quarterly")):
            return "QoQ"
        return "MoM"  # default

    def _detect_rolling_params(self, question: str) -> tuple:
        """Extract rolling window size and method from question."""
        q = question.lower()

        # Window size
        window = 12  # default
        window_match = re.search(r"(\d+)\s*-?\s*month", q)
        if window_match:
            window = int(window_match.group(1))
        elif "quarterly" in q or "3-month" in q:
            window = 3
        elif "6-month" in q or "half" in q:
            window = 6

        # Method
        method = "mean"
        if any(kw in q for kw in ("std", "deviation", "volatility", "variance")):
            method = "std"
        elif any(kw in q for kw in ("minimum", "lowest")) or re.search(r"\bmin\b", q):
            method = "min"
        elif any(kw in q for kw in ("maximum", "highest", "peak")) or re.search(r"\bmax\b", q):
            method = "max"

        return window, method

    def _detect_domain(self, question: str) -> Optional[str]:
        """Extract domain filter for top_movers."""
        q = question.lower()
        domain_map = {
            "oil": ["oil", "crude", "petroleum", "energy"],
            "bop": ["balance of payments", "bop", "current account", "trade"],
            "fiscal": ["fiscal", "budget", "revenue", "expenditure", "debt", "gdp"],
            "stability": ["monetary", "money supply", "reserves", "saibor", "stability"],
            "banking": ["banking", "bank", "loan", "deposit", "npl"],
        }
        for domain, keywords in domain_map.items():
            for kw in keywords:
                if kw in q:
                    return domain
        return None

    def _build_citation(self, candidate: dict, result: dict,
                        tool_name: str, extra: str = "") -> str:
        """Build a consistent citation string."""
        sid = candidate.get("series_id", "")
        name = candidate.get("name", "Unknown")
        unit = candidate.get("unit", "")
        source = candidate.get("source", "")
        source_url = candidate.get("source_url", "")

        citation = f"— {sid} , {name}: {unit}, Source: {source}"
        if source_url:
            citation += f" · [{source}]({source_url})"
        if extra:
            citation += f" | {extra}"

        staleness = result.get("staleness_days")
        if staleness and staleness > 90:
            latest_date = result.get("date") or result.get("latest_date", "?")
            citation += f"\nNote: Data may be stale, last point: {latest_date} ({staleness} days ago)"

        return citation

    # ─── Main data handler with smart tool routing ───────────────────────

    async def _handle_data(self, question: str,
                           collection_name: Optional[str] = None) -> tuple:
        """Handle data/numeric questions via series discovery + analytics.

        Smart routing:
          compare → analytics.compare()   (needs 2 series)
          top_movers → analytics.top_movers()  (domain-level scan)
          rolling → analytics.rolling()    (rolling statistics)
          change → analytics.change()      (MoM/YoY/QoQ)
          get_series → analytics.get_series()  (date-range query)
          latest → analytics.latest()      (default)
        """
        tool = self._detect_tool(question)
        logger.info(f"Detected analytics tool: {tool} for question: {question[:80]}")

        # ── top_movers: doesn't need series discovery ───────────────────
        if tool == "top_movers":
            domain = self._detect_domain(question)
            period = self._detect_change_method(question)
            result = await analytics.top_movers(domain=domain, period=period, limit=5)
            tools_called = [f"top_movers(domain={domain}, period={period})"]

            if "error" in result:
                return result["error"], [], tools_called, []

            movers = result.get("movers", [])
            if not movers:
                return "No series with sufficient data to calculate changes.", [], tools_called, []

            series_used = [m["series_id"] for m in movers]
            parts = [f"**Top {period} movers** ({domain or 'all domains'}):"]
            for i, m in enumerate(movers, 1):
                direction = "UP" if m["change_percent"] > 0 else "DOWN"
                parts.append(
                    f"{i}. {direction} **{m['name']}**: {m['change_percent']:+.1f}% "
                    f"({m['current_value']} {m['unit']}, as of {m['current_date']})"
                )
            data_context = "\n".join(parts)
            citations = [f"— Top movers analysis across {result['total_series_checked']} series"]
            return data_context, series_used, tools_called, citations

        # ── All other tools need series discovery ───────────────────────
        candidates = await self.discovery.search(
            question, top_k=5 if tool == "compare" else 3,
            collection_name=collection_name,
        )
        if not candidates:
            return "No matching time series found.", [], [], []

        # Filter weak matches
        candidates = [c for c in candidates if c.get("score", 0) >= 4.0]
        if not candidates:
            return "No matching time series found.", [], [], []

        series_used = [c["series_id"] for c in candidates]
        tools_called = []
        data_parts = []
        citations = []

        # ── compare: needs exactly 2 series ─────────────────────────────
        if tool == "compare" and len(candidates) >= 2:
            sid_a = candidates[0]["series_id"]
            sid_b = candidates[1]["series_id"]
            result = await analytics.compare(sid_a, sid_b, window=24)
            tools_called.append(f"compare({sid_a}, {sid_b})")

            if "error" not in result:
                data_parts.append(
                    f"**Comparison: {candidates[0]['name']} vs {candidates[1]['name']}**\n"
                    f"- Correlation: {result['correlation']} ({result.get('interpretation', '')})\n"
                    f"- {candidates[0]['name']} trend: {result['series_a_trend']} "
                    f"(latest: {result['series_a_latest']['value']} on {result['series_a_latest']['date']})\n"
                    f"- {candidates[1]['name']} trend: {result['series_b_trend']} "
                    f"(latest: {result['series_b_latest']['value']} on {result['series_b_latest']['date']})\n"
                    f"- Period: {result['date_range']['start']} to {result['date_range']['end']} "
                    f"({result['overlapping_periods']} overlapping observations)"
                )
                citations.append(
                    f" Comparison: {sid_a} vs {sid_b} | "
                    f"r = {result['correlation']}, {result['overlapping_periods']} data points"
                )
            else:
                data_parts.append(f"Comparison error: {result['error']}")
                # Fallback: show latest for both
                for c in candidates[:2]:
                    r = await analytics.latest(c["series_id"])
                    tools_called.append(f"latest({c['series_id']})")
                    if "error" not in r:
                        data_parts.append(
                            f"**{c['name']}**: {r.get('value')} {c['unit']} (as of {r.get('date')})"
                        )
                        citations.append(self._build_citation(c, r, "latest"))

        # ── rolling: rolling statistics ──────────────────────────────────
        elif tool == "rolling":
            window, method = self._detect_rolling_params(question)
            for candidate in candidates[:2]:
                sid = candidate["series_id"]
                result = await analytics.rolling(sid, window=window, method=method)
                tools_called.append(f"rolling({sid}, window={window}, method={method})")

                if "error" not in result:
                    data_parts.append(
                        f"**{candidate['name']}** , {window}-period rolling {method}:\n"
                        f"- Current rolling value: {result['current_rolling_value']} {candidate['unit']}\n"
                        f"- Current raw value: {result['current_raw_value']} {candidate['unit']}\n"
                        f"- Latest date: {result['latest_date']}\n"
                        f"- Total rolling data points: {result['total_points']}"
                    )
                    # Add recent rolling observations for LLM context
                    if result.get("observations"):
                        recent = result["observations"][-6:]
                        obs_text = ", ".join(f"{o['date']}: {o['value']}" for o in recent)
                        data_parts.append(f"  Recent rolling values: {obs_text}")
                    citations.append(self._build_citation(
                        candidate, result, "rolling",
                        f"{window}-period rolling {method} = {result['current_rolling_value']}"
                    ))
                else:
                    data_parts.append(f"**{candidate['name']}**: {result['error']}")

        # ── change: period-over-period change ────────────────────────────
        elif tool == "change":
            method = self._detect_change_method(question)
            for candidate in candidates[:2]:
                sid = candidate["series_id"]
                result = await analytics.change(sid, method=method)
                tools_called.append(f"change({sid}, method={method})")

                if "error" not in result:
                    direction = "UP" if (result.get("change_percent") or 0) > 0 else "DOWN"
                    data_parts.append(
                        f"{direction} **{candidate['name']}** ({method}):\n"
                        f"- Current: {result['current_value']} {candidate['unit']} ({result['current_date']})\n"
                        f"- Previous: {result['previous_value']} {candidate['unit']} ({result['previous_date']})\n"
                        f"- Change: {result.get('change_absolute', 'N/A')} ({result.get('change_percent', 'N/A')}%)"
                    )
                    citations.append(self._build_citation(
                        candidate, result, "change",
                        f"{method} change: {result.get('change_percent', 'N/A')}%"
                    ))
                else:
                    data_parts.append(f"**{candidate['name']}**: {result['error']}")

        # ── get_series: date-range query ─────────────────────────────────
        elif tool == "get_series":
            start, end = _extract_date_range(question)
            # Only use the BEST match to avoid noise
            for candidate in candidates[:1]:
                sid = candidate["series_id"]
                result = await analytics.get_series(sid, start=start, end=end)
                tools_called.append(f"get_series({sid})")

                if "error" not in result and result.get("observations"):
                    obs = result["observations"]
                    unit = candidate.get("unit") or result.get("unit") or ""
                    obs_text = ", ".join(
                        f"{o['date']}: {_fmt_num(o['value'])} {unit}".strip()
                        for o in obs[:10]
                    )
                    if len(obs) > 10:
                        obs_text += f" ... ({len(obs)} total observations)"
                    data_parts.append(
                        f"**{candidate['name']}** ({unit or 'value'}): {obs_text}"
                    )
                    citations.append(self._build_citation(
                        candidate, result, "get_series",
                        f"{len(obs)} observations"
                    ))
                elif "error" in result:
                    data_parts.append(f"**{candidate['name']}**: {result['error']}")

        # ── latest: default fallback ─────────────────────────────────────
        else:
            for candidate in candidates[:2]:
                sid = candidate["series_id"]
                result = await analytics.latest(sid)
                tools_called.append(f"latest({sid})")

                if "error" not in result:
                    data_type = "forecast" if result.get("is_forecast") else "actual"
                    unit = candidate.get("unit") or result.get("unit") or ""
                    data_parts.append(
                        f"**{candidate['name']}**: {_fmt_num(result.get('value'))} {unit} "
                        f"(as of {result.get('date')}, {data_type})"
                    )
                    citations.append(self._build_citation(candidate, result, "latest"))
                else:
                    data_parts.append(f"**{candidate['name']}**: {result['error']}")

        data_context = "\n".join(data_parts) if data_parts else "No data found."
        return data_context, series_used, tools_called, citations

    def _build_answer_prompt(self, context: str, knowledge_source: str) -> ChatPromptTemplate:
        """Build the LLM prompt for answer generation.

        Shared by both _generate_answer() and _generate_answer_stream() to
        avoid duplicating the system prompt.
        """
        system = (
            "You are JadwaChat, an intelligent financial data assistant for Jadwa Investment.\n"
            "You answer questions using the retrieved context below.\n"
            "The context may include:\n"
            "  - Entity/cross-sectional data (countries, sectors, companies with attributes)\n"
            "  - Time series data (oil prices, GDP growth, etc. over time)\n"
            "  - Document text (reports, notes, analysis)\n"
            "  - Web search results (when database has no relevant data)\n\n"
            "Rules:\n"
            "1. ALWAYS use STRUCTURED TIME SERIES DATA when it is provided. These are exact "
            "numbers from our databases — report them directly and confidently.\n"
            "2. Do NOT say 'the data is not available' if structured data IS provided above.\n"
            "3. Include specific numbers with units when available.\n"
            "4. If the context contains relevant data, provide a confident, insightful answer.\n"
            "5. You CAN and SHOULD derive insights, comparisons, and recommendations from "
            "the numerical data provided (e.g., reserves, production, rates, CPI).\n"
            "6. Support bilingual (English + Arabic) when the user writes in Arabic.\n"
            "7. Be concise and professional.\n"
            "8. Remember prior messages in this conversation. If the user says 'more', "
            "'continue', or asks follow-up questions, use the chat history to understand "
            "context and provide deeper analysis.\n"
        )

        # Always add the no-source-attribution rule
        system += (
            "9. NEVER add source attribution, citations, or emoji markers (like 📌, 🌐, 💡) "
            "at the end of your response. The UI displays sources separately.\n"
        )

        if knowledge_source == "web_search":
            system += (
                "10. Your answer is based on WEB SEARCH results.\n"
            )
        elif knowledge_source == "general_knowledge":
            system += (
                "10. You have NO relevant data from databases or web search. You may answer "
                "from your general training knowledge but state this clearly.\n"
            )

        context_block = f"\n\nContext:\n{context}"

        return ChatPromptTemplate.from_messages([
            ("system", system + context_block),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}"),
        ])

    async def _generate_answer(self, question: str, context: str, intent: str,
                               history_messages: list = None,
                               knowledge_source: str = "database") -> str:
        """Generate a natural language answer using the LLM with context and conversation history."""
        prompt = self._build_answer_prompt(context, knowledge_source)
        chain = prompt | self.llm | StrOutputParser()
        answer = await chain.ainvoke({
            "question": question,
            "chat_history": history_messages or [],
        })
        return answer

    async def _generate_answer_stream(
        self, question: str, context: str, intent: str,
        history_messages: list = None,
        knowledge_source: str = "database",
    ) -> AsyncGenerator[str, None]:
        """Stream the LLM answer token by token — same prompt as _generate_answer."""
        prompt = self._build_answer_prompt(context, knowledge_source)
        chain = prompt | self.llm | StrOutputParser()
        async for token in chain.astream({
            "question": question,
            "chat_history": history_messages or [],
        }):
            if token:
                yield token

    async def ask_stream(
        self, question: str, collection_name: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """Streaming version of ask() — yields SSE events.

        Event sequence:
          1. {"type": "metadata", ...}    — intent, tools, series info
          2. {"type": "sources", ...}     — retrieved doc sources
          3. {"type": "token", ...}       — each streamed token
          4. {"type": "done", ...}        — final event with conversation_id
        """
        # ─── 0. Conversation management ─────────────────────────────────
        if conversation_id and await self.history.conversation_exists(conversation_id):
            pass
        else:
            conversation_id = await self.history.create_conversation(
                collection_name=collection_name or "all-databases",
                title=question[:80],
            )

        chat_history = await self.history.get_chat_history_for_llm(conversation_id)
        history_messages = self._convert_history(chat_history)

        # ─── Intent classification ──────────────────────────────────────
        classification = await classify_intent(question, chat_history)
        intent = classification["intent"]
        is_followup = classification["is_followup"]

        series_used = []
        tools_called = []
        data_context = ""
        doc_context = ""
        citations = []
        doc_sources = []

        search_query = question
        if is_followup and chat_history:
            search_query = self._rewrite_query_for_search(question, chat_history)

        # ─── 1. Document retrieval (always search ALL collections) ────────
        if intent != "general":
            try:
                vs = get_rag_service().vectorstore
                retrieved_docs = await vs.similarity_search_all(query=search_query)
                tools_called.append("document_rag")

                if retrieved_docs:
                    doc_parts = []
                    for doc in retrieved_docs:
                        content = doc.get("content", "")
                        if content:
                            doc_parts.append(content)
                            metadata = doc.get("metadata", {})
                            from app.models.schemas import Source
                            doc_sources.append(Source(
                                content=content[:500],
                                metadata=metadata,
                                score=doc.get("score", 0.0),
                                page=metadata.get("page"),
                                filename=metadata.get("source"),
                            ))
                    if doc_parts:
                        doc_context = "\n\n".join(doc_parts)
            except Exception as e:
                logger.warning(f"Document RAG failed: {e}")

        # ─── 2. Structured data (always search ALL series) ────────────────
        if intent in ("data", "mixed"):
            data_context, series_used, ts_tools, citations = await self._handle_data(
                question, collection_name=None
            )
            tools_called.extend(ts_tools)

        # ─── 3. Merge context ──────────────────────────────────────────
        merged_context = ""
        has_db_context = False
        knowledge_source = "database"

        # Put structured data FIRST so the LLM prioritises exact numbers
        no_data_phrases = {"No data found.", "No matching time series found."}
        if data_context and data_context not in no_data_phrases:
            merged_context += (
                "STRUCTURED TIME SERIES DATA (use these exact numbers when answering):\n"
                f"{data_context}\n\n"
            )
            has_db_context = True

        if doc_context:
            merged_context += (
                "Supporting documents (use only if structured data above is insufficient):\n"
                f"{doc_context}\n\n"
            )
            has_db_context = True

        # ─── 3b. Web search fallback ────────────────────────────────────
        web_citations = []
        if not has_db_context:
            is_greeting = (intent == "general" and len(question.split()) <= 5)
            if not is_greeting:
                try:
                    web_service = get_web_search_service()
                    web_results = await web_service.search(question, max_results=5)
                    if web_results:
                        web_context = web_service.format_context(web_results)
                        merged_context = f"Web search results:\n{web_context}\n\n"
                        web_citations = web_service.format_citations(web_results)
                        knowledge_source = "web_search"
                        tools_called.append("web_search")

                        from app.models.schemas import Source
                        for r in web_results:
                            doc_sources.append(Source(
                                content=f"{r.title}\n{r.snippet}",
                                metadata={"source": r.url, "title": r.title, "type": "web_search"},
                                score=0.0, page=None, filename=r.url,
                            ))
                    else:
                        knowledge_source = "general_knowledge"
                except Exception as e:
                    logger.warning(f"Web search fallback failed: {e}")
                    knowledge_source = "general_knowledge"

            if not merged_context.strip():
                merged_context = (
                    "No specific data found in the databases or web. "
                    "You may answer from your general knowledge, but clearly "
                    "state that the answer is from general knowledge, not from "
                    "JadwaChat's databases."
                )
                knowledge_source = "general_knowledge"

        # ─── Yield metadata + sources first ─────────────────────────────
        yield {
            "type": "metadata",
            "intent": intent,
            "series_used": series_used,
            "tools_called": tools_called,
            "knowledge_source": knowledge_source,
        }

        yield {
            "type": "sources",
            "sources": [s.model_dump() if hasattr(s, "model_dump") else s for s in doc_sources],
            "conversation_id": conversation_id,
        }

        # ─── 4. Stream LLM answer ──────────────────────────────────────
        full_response = ""
        async for token in self._generate_answer_stream(
            question, merged_context, intent, history_messages, knowledge_source
        ):
            full_response += token
            yield {"type": "token", "content": token}

        # ─── 5. Save to history ─────────────────────────────────────────
        sources_dicts = [s.model_dump() for s in doc_sources]
        await self.history.add_message(conversation_id, "user", question)
        await self.history.add_message(
            conversation_id, "assistant", full_response, sources=sources_dicts
        )

        # ─── 6. Final event ────────────────────────────────────────────
        all_citations = citations + web_citations

        yield {
            "type": "done",
            "conversation_id": conversation_id,
            "citations": "\n".join(all_citations) if all_citations else "",
        }


_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator

