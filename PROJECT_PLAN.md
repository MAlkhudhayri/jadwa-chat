# JadwaChat — Project Plan

**Author:** Mohammed Alkhudhayri
**Date:** February 2026
**Status:** Phases 1-3 Complete, Phase 4 In Progress

---

## Executive Summary

JadwaChat is an AI-powered financial intelligence platform built for Jadwa Investment. It combines two complementary capabilities:

1. **Document RAG** — Chat with uploaded documents (PDFs, reports, research papers) using retrieval-augmented generation
2. **Structured Data Intelligence** — Query 27 macroeconomic and financial time series using natural language, with safe analytics tools and full citation trails

The system ensures **trust and accuracy** by never hallucinating numbers — all data comes from approved analytical functions with source citations (series ID, date, unit, source URL).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       JadwaChat Frontend                         │
│              (Next.js · Tailwind CSS · Jadwa Branding)           │
└──────────────────────┬───────────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────────┐
│                      FastAPI Backend                              │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                   Router / Orchestrator                      │ │
│  │                                                              │ │
│  │  1. Classify intent (numeric / definition / analysis)       │ │
│  │  2. Decompose into sub-tasks if compound query              │ │
│  │  3. Resolve series via Discovery                            │ │
│  │  4. Disambiguate if multiple candidates (clarification)     │ │
│  │  5. Execute tool chain in dependency order                  │ │
│  │  6. Enrich with document context if analysis query          │ │
│  │  7. Assemble answer with citations + staleness indicator    │ │
│  └──────┬─────────────────┬──────────────────────┬─────────────┘ │
│         │                 │                      │               │
│  ┌──────▼──────┐  ┌──────▼──────┐  ┌───────────▼────────────┐  │
│  │  Analytics  │  │  Series     │  │   Document RAG         │  │
│  │  Tools      │  │  Discovery  │  │   Pipeline             │  │
│  │             │  │             │  │                         │  │
│  │  latest()   │  │  Text       │  │  Qdrant Vector Store   │  │
│  │  change()   │  │  Search     │  │  LangChain + GPT-4o    │  │
│  │  rolling()  │  │  +          │  │  Multi-DB Collections  │  │
│  │  compare()  │  │  Semantic   │  │  Source Citations       │  │
│  │  top_movers │  │  Fallback   │  │                         │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬────────────┘  │
│         │                │                      │               │
│  ┌──────▼────────────────▼──────┐  ┌───────────▼────────────┐  │
│  │        SQLite / Postgres     │  │      Qdrant            │  │
│  │                              │  │                         │  │
│  │  series_catalog (27 series)  │  │  Document embeddings    │  │
│  │  observations (time series)  │  │  Series catalog embeds  │  │
│  │  ingestion_runs (audit)      │  │  5 predefined DBs       │  │
│  │  conversations (chat hist)   │  │  + "All Databases" mode │  │
│  │  tool_call_log (audit)       │  │                         │  │
│  └──────────────────────────────┘  └─────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Data Coverage

### 27 Time Series Across 5 Domains

| Domain | Series | Source | Frequency |
|--------|--------|--------|-----------|
| **Oil** (5) | KSA crude production, KSA oil exports, global demand, global supply, Brent price | JODI, EIA | Monthly |
| **Balance of Payments** (3) | Current account, net services, net change in reserves | SAMA | Quarterly |
| **Fiscal Environment** (5) | Revenues, expenditure, debt, debt/GDP, GDP growth | MoF, NDMC | Quarterly |
| **Financial Stability** (7) | SAMA reserves, NFA banks, govt deposits, reserve/M3, money supply, SAIBOR-SOFR 3m & 12m spreads | SAMA | Monthly/Weekly |
| **Banking Sector** (7) | CAR, LDR, demand deposits %, deposits, loans, ROE, NPL ratio | SAMA | Monthly |

### Data Sources

| Source | Organization | URL |
|--------|-------------|-----|
| **JODI** | Joint Organisations Data Initiative | http://www.jodidb.org |
| **EIA** | U.S. Energy Information Administration | https://www.eia.gov/outlooks/steo |
| **SAMA** | Saudi Central Bank | https://www.sama.gov.sa |
| **MoF** | Ministry of Finance | https://www.mof.gov.sa |
| **NDMC** | National Debt Management Center | https://ndmc.gov.sa |

---

## Implementation Phases

### Phase 1 — Canonical Data Model ✅ Complete

**Goal:** Define the foundation that makes everything clean later.

**Deliverables:**
- `SeriesCatalog` table — 27 series with metadata (series_id, name, domain, source, unit, frequency, synonyms, source_url)
- `Observation` table — time series data points (series_id, date, value, as_of_date, ingest_run_id)
- `IngestionRun` table — full audit trail (status, timestamps, row counts, file hashes)
- Data dictionary in YAML defining every series
- Automatic seeding on app startup (idempotent)
- REST API: `/api/series/catalog`, `/api/series/catalog/{id}`, `/api/series/domains`

**Key Decisions:**
- Stable `series_id` identifiers (e.g., `brent_price`, `ksa_crude_production`)
- Every observation tagged with `as_of_date` for revision tracking
- Synonyms stored per series for discovery (e.g., "oil price, crude price, brent spot")

---

### Phase 2 — Ingestion Pipeline ✅ Complete

**Goal:** Build repeatable, auditable data ingestion — not just "pass URLs."

**Deliverables:**
- Base connector framework: `fetch()` → `parse()` → `load()` with raw snapshotting
- 5 source connectors: EIA (API v2), JODI, SAMA, MoF, NDMC
- Raw snapshots saved as: `data/raw/{source}/{dataset}/{YYYY-MM-DD}/...`
- File hashes recorded for every download
- Upsert logic: insert if new, update if value changed, skip if identical
- CSV/Excel upload endpoint for manual data loading (supports wide and long format)
- REST API: `/api/ingestion/run/{source}`, `/api/ingestion/run`, `/api/ingestion/upload-csv`, `/api/ingestion/runs`

**Current Data Loaded:**
- **EIA API:** 1,296 observations (Brent price, global demand, global supply — 2002 to 2027 forecast)
- **JODI CSV:** 574 observations (KSA production & exports — 2002 to 2025)
- **Total:** 1,870 real data points

---

### Phase 3 — Series Discovery ✅ Complete

**Goal:** When a user asks "what's happening with Saudi oil output?", the system finds `ksa_crude_production`.

**Deliverables:**
- Two-tier discovery engine:
  - **Tier 1 (Text Search):** Weighted scoring across name, synonyms, description, series_id — fuzzy matching and token overlap
  - **Tier 2 (Semantic Search):** Auto-indexes series catalog into Qdrant with embeddings, activates when text scores are weak
- Combined search with deduplication and re-ranking
- REST API: `/api/series/search?q=reserve+pressure` → returns top-5 ranked candidates

**Test Results:**

| Query | Top Result | Correct? |
|-------|-----------|----------|
| "oil price" | `brent_price` (0.85) | ✅ |
| "saudi production" | `ksa_crude_production` (0.32) | ✅ |
| "reserve pressure" | `sama_reserves`, `reserve_m3_ratio` | ✅ |
| "banking health" | `banking_roe`, `capital_adequacy_ratio` | ✅ |
| "brent" | `brent_price` (0.95) | ✅ |
| "how much does KSA export" | `ksa_oil_exports` | ✅ |

---

### Phase 4 — Analytics Tool Layer 🔄 In Progress

**Goal:** The LLM never writes raw SQL. It outputs intent → backend runs approved analytics functions.

#### 4A — Core Analytics Functions

| Function | Description | Example |
|----------|-------------|---------|
| `latest(series_id)` | Most recent value with date, unit, staleness | "What's the current Brent price?" |
| `get_series(series_id, start, end)` | Full time series for a date range | "Show me KSA production for 2024" |
| `change(series_id, period_type)` | MoM, QoQ, or YoY absolute & percent change | "How did oil demand change year-over-year?" |
| `rolling(series_id, method, window)` | Rolling mean, std, min, max | "What's the 12-month rolling average of Brent?" |
| `compare(series_a, series_b, window)` | Correlation between two series | "How correlated are oil exports and SAMA reserves?" |
| `top_movers(domain, metric, period)` | Biggest changes in a domain | "What moved the most in banking this quarter?" |

#### 4B — Forecast vs. Actual Tagging

EIA data includes forecasts through 2027. Every observation must carry a `data_type` flag:

| Flag | Meaning | Display |
|------|---------|---------|
| `actual` | Published historical data | Shown normally |
| `forecast` | Forward-looking projection | Tagged: "EIA forecast, subject to revision" |
| `preliminary` | Initial release, may be revised | Tagged: "preliminary, subject to revision" |

**Rules:**
- `latest()` returns the most recent **actual** by default; pass `include_forecast=True` to include projections
- Any response containing forecast data must label it explicitly
- User never sees a forecast presented as fact

#### 4C — Data Staleness Indicator

Every tool response includes a staleness badge:

| Staleness | Badge | Example |
|-----------|-------|---------|
| < 7 days | `fresh` | "Data as of Feb 12, 2026" |
| 7-30 days | `aging` | "Data as of Jan 28, 2026 (18 days ago)" |
| > 30 days | `stale` | "**Warning:** Last data point is Dec 2025 (47 days ago). Source may have newer data." |

Implementation: `staleness = (today - max(observation.date)).days` per series. Exposed via `GET /api/series/freshness` and included in every tool result.

#### 4D — Data Gap Handling

When a series has missing periods:
- `get_series()` returns data with explicit `null` entries for gaps, plus a `gaps` array listing missing periods
- `change()` and `rolling()` skip gaps and note them: "YoY change calculated; Q2 2024 data unavailable"
- No interpolation or filling — missing data is surfaced, never hidden

#### 4E — Safety Envelope

- Read-only database access for analytics
- Statement timeout: 5 seconds max per query
- Row count limit: 10,000 rows per response
- All tool calls logged to `tool_call_log` table (function, parameters, result_summary, latency_ms, timestamp)
- Allowlist of approved functions only — no arbitrary SQL

#### 4F — Tool Call Logging Schema

```sql
CREATE TABLE tool_call_log (
    id            INTEGER PRIMARY KEY,
    conversation_id TEXT,
    function_name TEXT NOT NULL,       -- e.g., "latest", "change"
    parameters    JSON NOT NULL,       -- e.g., {"series_id": "brent_price"}
    result_summary TEXT,               -- truncated result for audit
    row_count     INTEGER,
    latency_ms    INTEGER,
    error         TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### Phase 5 — Document Pipeline (Docling) 📋 Planned

**Goal:** Tables are primary; documents enrich context for "why" and "what does X mean" questions.

**Deliverables:**
- Docling-based PDF ingestion → structured JSON/Markdown
- Chunking by section/table with metadata (source, page, section, URL, date)
- Embeddings stored in Qdrant (integrates with existing JadwaChat document collections)
- Document search: `search_docs(query, filters)` via similarity + metadata filters
- Handles SAMA reports, MoF fiscal reports, NDMC publications

**Example:** "Define Net Foreign Assets" → returns the exact paragraph from SAMA documentation with page number.

---

### Phase 6 — Router / Orchestrator + Answer Contract 📋 Planned

**Goal:** Turn components into a unified JadwaChat that routes questions intelligently.

#### 6A — Intent Classification

The orchestrator classifies every user message into one of four intent types:

| Intent | Signal Words | Pipeline |
|--------|-------------|----------|
| `numeric` | "how much", "what's the current", "trend", "change" | Analytics Tools |
| `definition` | "what is", "define", "methodology", "how is X calculated" | Document RAG |
| `analysis` | "why", "implications", "what does this mean for", "explain the drop" | Analytics Tools + Document RAG + LLM Narrative |
| `comparison` | "compare", "vs", "correlation", "relationship between" | Analytics Tools (`compare()` + `get_series()`) |

Implementation: A lightweight GPT-4o classification call with structured output (intent + extracted entities) before the main pipeline runs. Cost: ~100 tokens per classification.

#### 6B — Query Decomposition

Compound queries are broken into ordered sub-tasks:

**Example:** "Why did SAMA reserves drop and how does that compare to oil exports?"

```
Sub-task 1: change(sama_reserves, YoY)           → Get the drop magnitude
Sub-task 2: change(ksa_oil_exports, YoY)          → Get export trend
Sub-task 3: compare(sama_reserves, ksa_oil_exports, 24)  → Correlation
Sub-task 4: search_docs("SAMA reserves decline")  → Context from reports
Sub-task 5: LLM narrative combining 1-4           → Final answer
```

**Decomposition rules:**
- Max 5 sub-tasks per query (prevent runaway chains)
- Sub-tasks execute in dependency order (parallel where possible)
- Each sub-task result feeds into the final LLM context
- If any sub-task fails, the response notes what's missing rather than hallucinating

#### 6C — Disambiguation Flow

When series discovery returns multiple high-confidence candidates:

```
User: "What's the spread?"
Discovery: saibor_sofr_3m_spread (0.82), saibor_sofr_12m_spread (0.80)

Response: "Which spread are you asking about?
  1. SAIBOR-SOFR 3-month spread (currently 45 bps)
  2. SAIBOR-SOFR 12-month spread (currently 62 bps)"
```

**Disambiguation triggers:**
- Top two candidates within 0.15 score of each other
- Query maps to multiple series in the same domain
- Ambiguous time period ("last quarter" when data is monthly)

**No disambiguation needed when:**
- Top candidate score > 0.80 and gap to second > 0.20
- User specifies series_id directly
- Follow-up in existing conversation (use context)

#### 6D — Multi-Turn Conversation Context

The orchestrator maintains conversation state for follow-up questions:

```
Turn 1: "What's the current Brent price?"
  → latest(brent_price) → "$76.50/bbl as of Dec 2024"
  → Context saved: {active_series: [brent_price], active_period: "Dec 2024"}

Turn 2: "What about last quarter?"
  → Resolves "what about" → same series (brent_price)
  → Resolves "last quarter" → Q3 2024
  → get_series(brent_price, 2024-07-01, 2024-09-30)

Turn 3: "Compare that with production"
  → Resolves "that" → brent_price
  → Resolves "production" → ksa_crude_production (discovery)
  → compare(brent_price, ksa_crude_production, 12)
```

**Implementation:**
- Last 3 turns of resolved series_ids and date ranges stored in conversation metadata
- Pronoun resolution ("it", "that", "this") maps to most recent series
- Temporal references ("last quarter", "same period last year") resolved against active context
- If ambiguous, ask for clarification rather than guess

#### 6E — Answer Contract

Every response must include these components:

```python
class AnswerEnvelope:
    # Core answer
    narrative: str              # Human-readable answer text

    # Data provenance (one per data point used)
    citations: list[Citation]

    # Metadata
    staleness: StalenessBadge   # fresh / aging / stale
    data_types_used: list[str]  # ["actual", "forecast"]
    series_used: list[str]      # ["brent_price", "ksa_crude_production"]
    confidence: str             # "high" / "medium" / "partial"

    # Audit
    tool_calls: list[str]       # ["latest(brent_price)", "change(brent_price, YoY)"]

class Citation:
    series_id: str
    series_name: str
    value: float | None
    date: date
    unit: str
    source: str                 # "EIA STEO"
    source_url: str | None
    as_of_date: date | None     # When data was ingested
    data_type: str              # "actual" | "forecast" | "preliminary"
```

**Confidence levels:**

| Level | Meaning |
|-------|---------|
| `high` | All requested data found, no gaps, all series resolved unambiguously |
| `medium` | Data found but some gaps, or one series resolved with moderate confidence |
| `partial` | Missing series or significant data gaps; answer is incomplete |

**Example formatted response:**

```
Brent crude oil averaged $76.50/bbl in December 2024, down 8.2% year-over-year.
KSA crude production held steady at 9.0 mn bbl/day.

📊 Data freshness: aging (18 days since last update)

Sources:
  • brent_price — $76.50/bbl, Dec 2024 (actual)
    EIA STEO · https://www.eia.gov/outlooks/steo · ingested Feb 12, 2026
  • ksa_crude_production — 9.0 mn bbl/day, Dec 2024 (actual)
    JODI · http://www.jodidb.org · ingested Feb 10, 2026
```

#### 6F — Graceful Degradation

When the system can't fully answer a question:

| Scenario | Behavior |
|----------|----------|
| Series not found | "I don't have data on X. Available series in [domain]: ..." |
| Data too stale | Answer with staleness warning + suggest checking source directly |
| Partial data gaps | Answer with available data, note gaps explicitly |
| Out of scope | "This question requires data I don't track. The closest series I have is..." |
| Tool execution error | "I couldn't calculate X due to [error]. Here's what I can tell you: ..." |

---

### Phase 7 — Evaluation & Testing 📋 Planned

**Goal:** Prove the system works correctly and catch regressions automatically.

#### 7A — Golden Dataset

A curated set of 80+ question/answer pairs covering all query types:

| Category | Count | Examples |
|----------|-------|---------|
| Latest value | 10 | "What's the current Brent price?" → brent_price, latest actual |
| Change calculation | 15 | "YoY change in SAMA reserves?" → change(sama_reserves, YoY) |
| Time range | 10 | "KSA production in 2024" → get_series with correct date range |
| Comparison | 10 | "Correlation between oil exports and reserves" → compare() |
| Top movers | 5 | "What moved most in banking?" → top_movers(banking, pct_change) |
| Document retrieval | 10 | "Define capital adequacy ratio" → correct document chunk |
| Compound / analysis | 10 | "Why did reserves drop?" → tools + docs + narrative |
| Disambiguation | 5 | "What's the spread?" → triggers clarification |
| Follow-up / multi-turn | 5 | "What about last quarter?" → correct context resolution |
| Out of scope | 5 | "What's the S&P 500?" → graceful "I don't track that" |

#### 7B — Automated Evaluation Checks

Each golden test case verifies:

| Check | Description |
|-------|-------------|
| **Series resolution** | Correct series_id(s) resolved from natural language |
| **Tool selection** | Correct analytics function(s) called |
| **Numeric accuracy** | Returned values match expected (within rounding tolerance) |
| **Citation presence** | Response includes series_id, source, date, unit |
| **No hallucination** | No numbers appear that didn't come from tool results |
| **Staleness shown** | Freshness indicator present when data > 7 days old |
| **Forecast labeled** | Any forecast data explicitly tagged |
| **Graceful failure** | Out-of-scope queries handled without hallucination |

#### 7C — Test Infrastructure

```
tests/
├── conftest.py                 # Fixtures: test DB, mock Qdrant, sample data
├── test_analytics_tools.py     # Unit tests for each analytics function
├── test_series_discovery.py    # Discovery accuracy against golden queries
├── test_ingestion.py           # Connector fetch/parse/upsert logic
├── test_router.py              # Intent classification and query decomposition
├── test_answer_contract.py     # Citation completeness, staleness, forecast labels
├── test_disambiguation.py      # Ambiguous query handling
├── test_multi_turn.py          # Conversation context resolution
├── golden/
│   └── golden_dataset.yaml     # 80+ question/expected_answer pairs
└── e2e/
    └── test_full_pipeline.py   # End-to-end: question → formatted answer
```

**CI integration:** `pytest tests/ --golden` runs the full golden dataset. Any regression fails the build.

---

### Phase 8 — Operational Readiness 📋 Planned

**Goal:** Production-grade reliability, monitoring, and maintainability.

#### 8A — Data Refresh Strategy

| Source | Refresh Frequency | Method |
|--------|-------------------|--------|
| EIA STEO | Monthly (when STEO updates) | Scheduled cron job or manual trigger |
| JODI | Monthly | Manual CSV upload (JODI has no public API) |
| SAMA | Monthly | Scheduled connector + manual fallback |
| MoF | Quarterly | Manual upload after fiscal reports |
| NDMC | Quarterly | Manual upload after debt reports |

**Freshness monitoring:**
- `GET /api/series/freshness` — returns staleness for all 27 series
- Alert (log warning) when any series exceeds its expected update frequency by 2x
- Dashboard widget showing data currency per domain

#### 8B — Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Data source downtime** | Stale data, failed ingestion | Raw snapshots ensure last-known-good data; staleness badges warn users |
| **API rate limits (EIA)** | Blocked ingestion | Exponential backoff + daily rate tracking; manual CSV fallback |
| **Source data revisions** | Numbers change after publication | `as_of_date` tracks ingestion time; raw snapshots prove what we had |
| **Embedding model changes** | Vector search breaks | Pin embedding model version; re-index on model upgrade with A/B comparison |
| **LLM cost at scale** | Budget overrun | Token usage logging per conversation; classification call is ~100 tokens; cache repeated queries |
| **Schema changes upstream** | Connector parsing fails | File hash comparison detects format changes; alert + manual review |
| **Qdrant downtime** | Document search fails | Analytics tools still work (SQLite); graceful degradation in router |

#### 8C — Logging & Observability

| Component | What's Logged |
|-----------|--------------|
| Tool calls | Function, params, result summary, latency, errors → `tool_call_log` table |
| Ingestion | Source, rows loaded, file hash, duration, errors → `ingestion_runs` table |
| LLM calls | Model, tokens in/out, latency, cost estimate → application log |
| Series freshness | Per-series staleness computed daily → `/api/series/freshness` |
| Errors | Structured JSON logs with request ID, traceback, user context |

#### 8D — Remaining Connector Work

Three connectors have placeholder implementations and need real data integration:

| Connector | Status | Blocker | Series Count |
|-----------|--------|---------|-------------|
| **SAMA** | Placeholder | Need to map Monthly Statistics Excel format | 14 series |
| **MoF** | Placeholder | Need quarterly fiscal report format | 2 series |
| **NDMC** | Placeholder | Need debt statistics page format | 3 series |

**Plan:** Prioritize SAMA (covers 14 of 27 series). Manual CSV upload works as interim for all three.

---

## Demo Scenario

A realistic multi-turn conversation showing the system end-to-end:

```
User: How has Brent crude performed this year?

JadwaChat:
  [Router] Intent: numeric → Analytics Tools
  [Discovery] "Brent crude" → brent_price (0.95)
  [Tools] get_series(brent_price, 2024-01-01, 2024-12-31)
  [Tools] change(brent_price, YoY)

  Brent crude averaged $78.20/bbl in 2024, ending the year at $76.50/bbl
  in December. This represents a decline of 3.1% year-over-year from 2023.

  The price ranged from a low of $73.80 (Sep 2024) to a high of
  $83.40 (Apr 2024).

  📊 Data freshness: fresh (3 days ago)

  Sources:
    • brent_price — EIA STEO · ingested Feb 12, 2026
      https://www.eia.gov/outlooks/steo

---

User: How does that compare with Saudi production?

JadwaChat:
  [Router] Intent: comparison
  [Context] "that" → brent_price (from previous turn)
  [Discovery] "Saudi production" → ksa_crude_production (0.90)
  [Tools] compare(brent_price, ksa_crude_production, 12)
  [Tools] change(ksa_crude_production, YoY)

  KSA crude production averaged 9.0 mn bbl/day in 2024, largely
  unchanged year-over-year (-0.2%).

  The correlation between Brent price and KSA production over the
  trailing 12 months was -0.34, suggesting a weak inverse relationship
  — production held steady even as prices declined.

  📊 Data freshness: aging (brent_price: 3 days, ksa_crude_production: 15 days)

  Sources:
    • brent_price — EIA STEO · ingested Feb 12, 2026
    • ksa_crude_production — JODI · ingested Jan 31, 2026

---

User: Why might reserves be declining?

JadwaChat:
  [Router] Intent: analysis → Analytics Tools + Document RAG
  [Discovery] "reserves" → sama_reserves (0.88)
  [Tools] change(sama_reserves, YoY)
  [Docs] search_docs("SAMA reserves decline factors")

  SAMA foreign reserves stood at SAR 1,680 bn as of November 2024,
  down 4.2% year-over-year.

  According to SAMA's Financial Stability Report (p. 23), reserve
  drawdowns typically reflect a combination of:
  - Lower oil revenues reducing government deposits at SAMA
  - Increased capital project spending under Vision 2030
  - Seasonal current account fluctuations

  Note: SAMA data is 47 days old — newer data may be available.
  ⚠️ Stale: last data point is Nov 2024

  Sources:
    • sama_reserves — SAMA Monthly Statistics · ingested Dec 30, 2025
    • SAMA Financial Stability Report 2024, p. 23
```

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Frontend** | Next.js 14, Tailwind CSS, TypeScript | App Router for streaming; Tailwind for rapid Jadwa-branded UI |
| **Backend** | Python 3.13, FastAPI, LangChain | Async-first; FastAPI for auto-docs and streaming SSE |
| **LLM** | OpenAI GPT-4o (streaming) | Best balance of capability, speed, and cost for tool use |
| **Embeddings** | OpenAI text-embedding-3-large (3072-dim) | Highest quality for financial domain; pinned version for consistency |
| **Vector DB** | Qdrant (documents + series catalog) | Native filtering, good Python SDK, self-hosted via Docker |
| **Structured DB** | SQLite with async (upgradeable to Postgres) | Zero-ops for development; async via aiosqlite; Postgres for production scale |
| **Data Ingestion** | httpx, pandas, custom connectors | httpx for async HTTP; pandas for CSV/Excel parsing |
| **Deployment** | Docker Compose (Qdrant + Backend + Frontend) | Single `docker compose up` for full stack |

---

## Key Design Decisions

1. **Tables-first, not RAG-first** — Financial data is numerical. You can't reliably extract "YoY change in SAMA reserves" from chunked PDFs. Structured time series are first-class citizens.

2. **LLM never writes SQL** — All data access goes through approved tool functions (`latest()`, `change()`, `rolling()`, `compare()`). This prevents hallucination, injection, and ensures auditability.

3. **Answer contract with citations** — Every numeric answer must cite the series_id, date, unit, source, and source URL. This builds trust for a regulated financial institution.

4. **Two-tier search** — Deterministic text search handles exact matches fast; semantic search via Qdrant catches conceptual queries ("reserve pressure" → SAMA reserves).

5. **Qdrant for documents, SQLite for time series** — Each database does what it's best at. Vector search for unstructured text, relational queries for structured numerical data.

6. **Raw snapshotting** — Every data download is saved with file hashes and timestamps. If a source revises numbers, we can prove what we had.

7. **Forecast vs. actual separation** — EIA projections are never presented as fact. Every observation carries a `data_type` flag and forecasts are labeled explicitly in responses.

8. **Graceful degradation over silence** — When data is missing, stale, or ambiguous, the system tells the user what it doesn't know rather than guessing.

---

## Current Status

| Phase | Status | Key Metric |
|-------|--------|------------|
| Phase 1 — Data Model | ✅ Complete | 27 series defined, 3 tables, YAML dictionary |
| Phase 2 — Ingestion | ✅ Complete | 1,870 real observations loaded (EIA API + JODI CSV) |
| Phase 3 — Discovery | ✅ Complete | 6/6 test queries return correct top result |
| Phase 4 — Analytics | 🔄 In Progress | 6 tool functions + staleness + forecast tagging |
| Phase 5 — Documents | 📋 Planned | Docling pipeline + document search |
| Phase 6 — Router | 📋 Planned | Intent classification, decomposition, disambiguation, multi-turn |
| Phase 7 — Evaluation | 📋 Planned | 80+ golden test cases, automated regression |
| Phase 8 — Operations | 📋 Planned | Refresh strategy, monitoring, remaining connectors |
