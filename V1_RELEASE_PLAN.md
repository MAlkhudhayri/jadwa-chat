# JadwaChat v1.0 Release Plan — "The Quant Brain"

**Current state:** v0 (deployed, live)
**Target:** v1.0 — JadwaChat becomes the interface to a quantitative macro signal engine
**Author:** Mohammed Alkhudhayri
**Date:** February 2026

---

## The Thesis

v0 is a **chat tool that retrieves data**. A user asks "What's the Brent price?" and gets a number back.

v1.0 is a **chat tool that thinks about data**. A user asks "What's happening in the oil sector?" and gets:

> "The oil sector is signaling **moderately positive** (+42). Brent is at $78.20/bbl, up 4.2% MoM and sitting at the 72nd percentile vs the last 3 years. KSA production is flat at 9.0 mn bbl/day — note that this is a policy hold while prices are rising, which is unusual. No anomalies detected. The Brent-Revenue correlation remains strong (r=0.87)."

That answer requires **signals, anomalies, scorecards, and cross-series analysis** — not just a database lookup.

The quant engine is not a separate product. It's the **brain** that JadwaChat's orchestrator calls.

---

## Architecture: How the Pieces Connect

```
┌──────────────────────────────────────────────────────────────────┐
│                          JadwaChat v1.0                          │
│                        (Next.js Frontend)                        │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  "What's happening in oil?"                                 │ │
│  │  "Any anomalies this month?"                                │ │
│  │  "Compare oil revenue vs government spending"               │ │
│  │  "Give me the macro scorecard"                              │ │
│  └──────────────────────────┬──────────────────────────────────┘ │
└─────────────────────────────┼────────────────────────────────────┘
                              │  SSE stream
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Orchestrator v2                               │
│                                                                   │
│  Intent Classifier (GPT-4o-mini):                                │
│    data | document | mixed | general | ★ signal (NEW)            │
│                                                                   │
│  Tool Router:                                                     │
│    ├── data    → analytics.latest/change/rolling/compare/top     │
│    ├── document → Qdrant RAG                                      │
│    ├── general → web search / LLM knowledge                      │
│    └── ★ signal → Quant Engine API (NEW)                         │
│          ├── GET /signals/scorecard                               │
│          ├── GET /signals/anomalies                               │
│          ├── GET /signals/domain/{domain}                         │
│          ├── GET /signals/series/{id}                             │
│          └── GET /signals/cross-series                            │
└──────────────────────────────┬───────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
┌──────────────────┐ ┌─────────────────┐ ┌─────────────────────────┐
│   PostgreSQL     │ │   Qdrant        │ │  ★ Quant Signal Engine  │
│   (time series)  │ │   (documents)   │ │    (NEW — Python pkg)   │
│                  │ │                 │ │                          │
│ 23 CSV-seeded    │ │ Uploaded PDFs   │ │  src/signals/trend.py   │
│ series (SAMA,    │ │ (MoF, NDMC,     │ │  src/signals/anomaly.py │
│ EIA)             │ │ analyst reports) │ │  src/signals/scorecard  │
│                  │ │                 │ │  src/signals/cross.py   │
│ Raw observations │ │ Chunked text +  │ │                          │
│ + tool call logs │ │ embeddings      │ │  Reads from same PG DB  │
└──────────────────┘ └─────────────────┘ │  Writes signal tables   │
                                          └─────────────────────────┘
```

**Key insight:** The quant engine is **not a separate service**. It's a Python package inside the same backend that reads from the same PostgreSQL database. No network hop. No deployment headache. Just a new set of tables and a new set of functions the orchestrator can call.

---

## What Changes from v0 → v1.0

### What STAYS (v0 is solid)
- ✅ JWT authentication + rate limiting
- ✅ Streaming SSE responses
- ✅ LLM intent classification (GPT-4o-mini)
- ✅ Document RAG via Qdrant
- ✅ CSV/Excel smart upload
- ✅ Conversation memory (multi-turn)
- ✅ Web search fallback
- ✅ Analytics tools (latest, change, rolling, compare, top_movers)
- ✅ Docker + Railway deployment
- ✅ 23 seeded series (SAMA + EIA)

### What's NEW in v1.0

| # | Feature | Why It Matters |
|---|---------|---------------|
| 1 | **Signal computation pipeline** | Transforms raw data → signals (z-score, trend, percentile) |
| 2 | **Anomaly detection** | Auto-flags unusual movements across all series |
| 3 | **Domain scorecards** | 5 macro scores a PM can scan in 10 seconds |
| 4 | **Cross-series monitor** | Detects when historically correlated series diverge |
| 5 | **"signal" intent in orchestrator** | Chat naturally routes to quant functions |
| 6 | **Signal dashboard page** | Visual scorecard + anomaly list in frontend |
| 7 | **Scheduled refresh** | Signals recompute when data updates |
| 8 | **MoF + NDMC data ingestion** | Fill the fiscal gap (5 series currently missing) |

---

## Detailed Implementation Plan

### Phase 1 — Signal Database Schema

**Goal:** Add tables to the existing PostgreSQL to store computed signals.

**File:** `backend/app/models/signals.py` (NEW)

```
New Tables:
──────────
signal_snapshots
  id | series_id | date | signal | z_score_12m | mom_pct | qoq_pct |
  yoy_pct | percentile_36m | sma_6 | sma_12 | trend_slope | computed_at

anomaly_alerts
  id | series_id | date | type | severity | description | z_score |
  is_active | created_at | resolved_at

domain_scorecards
  id | domain | date | score | direction | component_json | alert_count |
  computed_at

cross_series_alerts
  id | pair_name | series_a_id | series_b_id | date |
  long_run_correlation | recent_correlation | divergence_magnitude |
  description | is_active | created_at

signal_runs
  id | started_at | finished_at | status | series_processed |
  anomalies_detected | notes
```

These tables live alongside the existing `series_catalog`, `observations`, and `tool_call_log` tables. Same database, same migrations.

**Acceptance:** `alembic upgrade head` adds all 5 tables. No existing data affected.

---

### Phase 2 — Signal Computation Engine

**Goal:** Pure Python functions that read observations and write signal_snapshots.

**Files:**
- `backend/app/services/quant/__init__.py`
- `backend/app/services/quant/trend.py`
- `backend/app/services/quant/anomaly.py`
- `backend/app/services/quant/cross_series.py`
- `backend/app/services/quant/scorecard.py`
- `backend/app/services/quant/runner.py`

**Important:** These are NOT standalone scripts. They're async service functions that use the same `get_session_factory()` pattern as `analytics.py`. The runner reads from `observations` and writes to `signal_snapshots`, `anomaly_alerts`, `domain_scorecards`, and `cross_series_alerts`.

#### 2A — Trend Signals (`quant/trend.py`)

```python
async def compute_signals(series_id: str) -> list[SignalSnapshot]:
    """
    Read observations for series_id from PostgreSQL.
    Compute: mom_pct, qoq_pct, yoy_pct, z_score_12m, percentile_36m,
             sma_6, sma_12, trend_slope_12m.
    Classify: strong_up/moderate_up/stable/moderate_down/strong_down/
              reversal_up/reversal_down.
    Write results to signal_snapshots table.
    Return list of new snapshots.
    """
```

Signal classification rules (evaluated in order):
1. `reversal_up`: mom_pct > 0 AND yoy_pct < -5
2. `reversal_down`: mom_pct < 0 AND yoy_pct > 5
3. `strong_up`: z_score > 1.5 AND mom_pct > 0 AND yoy_pct > 5
4. `strong_down`: z_score < -1.5 AND mom_pct < 0 AND yoy_pct < -5
5. `moderate_up`: mom_pct > 0 AND yoy_pct > 0
6. `moderate_down`: mom_pct < 0 AND yoy_pct < 0
7. `stable`: default

#### 2B — Anomaly Detection (`quant/anomaly.py`)

```python
async def detect_anomalies(series_id: str) -> list[AnomalyAlert]:
    """
    Run 4 anomaly detectors on latest data:
    1. bollinger_break: value outside 2σ/3σ Bollinger Band (20-period)
    2. trend_break: value crosses SMA-12 after 6+ months on one side
    3. streak: 6+ consecutive same-direction MoM changes
    4. level_shift: MoM change > 3x series average absolute MoM

    Domain-aware thresholds:
    - Oil: Bollinger width = 2.5σ (volatile)
    - Banking ratios: Bollinger width = 1.5σ (small moves matter)
    - Default: 2.0σ

    Severity:
    - critical: Z > 3.0 or shift > 5x average
    - warning: Z > 2.0 or shift > 3x or streak > 8
    - watch: Z > 1.5 or streak 6-8
    """
```

#### 2C — Cross-Series Intelligence (`quant/cross_series.py`)

8 monitored pairs with investment meaning:

| Pair | Expected | Logic |
|------|----------|-------|
| brent_price ↔ govt_revenues | + | Oil revenue link |
| sama_reserves ↔ brent_price | + | Reserve accumulation |
| bank_loans ↔ bank_deposits | + | Credit cycle (LDR) |
| govt_expenditure ↔ govt_revenues | + | Fiscal discipline |
| npl_ratio ↔ gdp_growth | − | Asset quality cycle |
| saibor_3m ↔ money_supply_m3 | − | Liquidity-rate link |
| ksa_production ↔ global_demand | complex | OPEC policy |
| current_account ↔ brent_price | + | External balance |

```python
async def analyze_pairs() -> list[CrossSeriesAlert]:
    """
    For each pair: compute 24-month rolling correlation.
    Alert if recent 6-month correlation diverges from
    long-run by > 0.3 (i.e. relationship is breaking).
    """
```

**Series ID mapping note:** The pairs reference canonical names but the actual DB series_ids have collection prefixes (e.g., `oil_markets__brent_price_usd_bbl`). The cross-series module needs a mapping layer:
```python
PAIR_MAPPING = {
    "brent_price": "oil_markets__brent_price_usd_bbl",
    "sama_reserves": "sama__total_reserves_mn_sar",
    "bank_loans": "sama__total_credit_mn_sar",
    # ... etc
}
```

#### 2D — Domain Scorecards (`quant/scorecard.py`)

5 domains, weighted:

```python
DOMAIN_CONFIG = {
    "oil": {
        "weight": 0.35,
        "series": {
            "oil_markets__brent_price_usd_bbl": 0.30,
            "ksa_oil_production__ksa_crude_production_mn_bbl_day": 0.25,
            "oil_markets__global_oil_demand_mn_bbl_day": 0.20,
            "oil_markets__global_oil_supply_mn_bbl_day": 0.15,
            "oil_markets__opec_crude_production_mn_bbl_day": 0.10,
        }
    },
    "monetary_stability": {
        "weight": 0.25,
        "series": {
            "sama__total_reserves_mn_sar": 0.25,
            "sama__m1_mn_sar": 0.15,
            "sama__m2_mn_sar": 0.15,
            "sama__saibor_3m": 0.15,
            "sama__total_foreign_assets_mn_sar": 0.15,
            "sama__general_cpi": 0.15,
        }
    },
    "banking": {
        "weight": 0.20,
        "series": {
            "sama__total_credit_mn_sar": 0.20,
            "sama__demand_deposits_mn_sar": 0.15,
            "sama__npl_to_total_loans_pct": 0.20,
            "sama__return_on_equity_pct": 0.15,
            "sama__capital_adequacy_ratio_pct": 0.15,
            "sama__time_savings_mn_sar": 0.15,
        }
    },
    "bop": {
        "weight": 0.10,
        "series": {
            "sama__current_account_mn_usd": 0.50,
            "sama__net_services_mn_usd": 0.25,
            "sama__net_change_reserves_mn_usd": 0.25,
        }
    },
    "fiscal": {
        "weight": 0.10,
        "series": {}  # Populated when MoF/NDMC data is added
    },
}
```

Score calculation: signal → numeric (-100 to +100) → weighted average per domain → weighted average across domains.

#### 2E — Pipeline Runner (`quant/runner.py`)

```python
async def run_signal_pipeline() -> dict:
    """
    Master pipeline:
    1. Get all series with observations from DB
    2. For each: compute_signals() → write signal_snapshots
    3. For each: detect_anomalies() → write anomaly_alerts
    4. Run analyze_pairs() → write cross_series_alerts
    5. Run compute_scorecards() → write domain_scorecards
    6. Log signal_run with stats
    Return summary dict.
    """
```

**Acceptance:** `await run_signal_pipeline()` processes all series, writes to all 4 signal tables, completes in <30 seconds for 23 series.

---

### Phase 3 — Orchestrator "signal" Intent

**Goal:** Teach the orchestrator to recognize and route signal queries.

**File:** `backend/app/services/orchestrator.py` (MODIFY)

#### 3A — Update Intent Classifier

Add `signal` to the intent classification prompt:

```
  signal   - The user wants macro analysis, signals, anomalies, scorecards,
             regime assessment, or cross-series insights. These go beyond
             raw data retrieval.
             Examples: "What's happening in oil?", "Any anomalies?",
             "Give me the macro scorecard", "Is banking deteriorating?",
             "How does oil relate to government revenue?",
             "What should I watch this month?"
```

#### 3B — Add Signal Handler

```python
async def _handle_signal(self, question: str) -> tuple:
    """Route signal queries to the quant engine.

    Sub-routing:
    - "scorecard" / "macro" / "overview" → full scorecard
    - "anomalies" / "unusual" / "alerts" → anomaly list
    - domain name ("oil", "banking") → domain-specific scorecard
    - "compare X and Y" / "relationship" → cross-series
    - specific series → series signal detail
    - default → full scorecard + active anomalies
    """
```

The handler formats quant results into rich context for the LLM:

```python
# Example context passed to GPT-4o:
"""
Structured signal data:

MACRO SCORECARD (as of 2026-02-01):
  Oil:                +42 (moderate_up, improving)
  Monetary Stability: +18 (stable)
  Banking:            -12 (moderate_down, deteriorating)
  BoP:                +5  (stable)
  Fiscal:             N/A (insufficient data)
  Aggregate:          +22 (moderate_up)

ACTIVE ANOMALIES (2):
  ⚠️ [warning] sama__npl_to_total_loans_pct: Bollinger band break
     Z-score: -2.1, NPL ratio at 1.8%, below 20-month lower band
  👁 [watch] oil_markets__brent_price_usd_bbl: 7-month consecutive rise
     Streak anomaly: MoM positive for 7 consecutive months

CROSS-SERIES ALERTS (1):
  ⚠️ ksa_production ↔ global_demand: Divergence detected
     Long-run correlation: +0.72, Recent 6m: +0.31 (divergence: 0.41)
     KSA production flat while demand rising — possible OPEC policy hold
"""
```

The LLM then writes a natural language synthesis. The numbers come from the quant engine (deterministic), the narrative comes from GPT-4o.

#### 3C — Tool Detection Update

Add to `_detect_tool()`:
```python
# Signal / scorecard / anomaly queries
if any(kw in q for kw in (
    "scorecard", "macro picture", "macro overview", "what's happening",
    "anomaly", "anomalies", "unusual", "alert", "watch",
    "signal", "signals", "regime", "deteriorating", "improving",
    "sentiment", "health", "outlook",
)):
    return "signal"
```

**Acceptance:** Asking "What's the macro picture?" returns a scorecard-based answer. Asking "Any anomalies?" returns active alerts.

---

### Phase 4 — Signal Dashboard (Frontend)

**Goal:** Visual scorecard page accessible from the sidebar.

**New files:**
- `frontend/app/signals/page.tsx` — Dashboard page
- `frontend/components/ScoreGauge.tsx` — Semicircle gauge (-100 to +100)
- `frontend/components/DomainCard.tsx` — Per-domain scorecard card
- `frontend/components/AnomalyTable.tsx` — Sortable anomaly list
- `frontend/components/RadarChart.tsx` — 5-axis domain radar

**Design:**
- Route: `/signals` (accessible from sidebar icon)
- Auto-refreshes from `GET /api/signals/dashboard`
- Jadwa brand colors: Navy `#1B365D`, Gold `#C8A951`, White
- Mobile-responsive (cards stack vertically)
- Click any domain → expands to show component series + sparklines
- Click any anomaly → opens chat with "Tell me more about [anomaly]"

**New API endpoints** (`backend/app/api/signals.py`):

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/signals/dashboard` | Full dashboard: scorecards + anomalies + cross-series |
| GET | `/api/signals/domain/{domain}` | Single domain detail with component signals |
| GET | `/api/signals/anomalies` | Active anomalies, sorted by severity |
| GET | `/api/signals/series/{series_id}` | Signal history for one series (last 24 months) |
| POST | `/api/signals/refresh` | Trigger signal pipeline recomputation |

**Acceptance:** `/signals` page loads in <2 seconds, shows 5 domain scores, any active anomalies, and a radar chart.

---

### Phase 5 — Data Gap: MoF + NDMC Ingestion

**Goal:** Add the 5 missing fiscal series.

**Problem:** MoF publishes quarterly fiscal reports as PDFs. NDMC provides debt statistics via their website. Neither has a clean API.

**Strategy:**
1. **Manual extraction first:** Download MoF quarterly reports, extract revenue/expenditure tables into CSVs, place in `data/raw/mof/`
2. **Build a `seed_fiscal.py`** that follows the same pattern as `seed_datasets.py`
3. **Series to add:**
   - `fiscal__govt_revenues_mn_sar`
   - `fiscal__govt_expenditure_mn_sar`
   - `fiscal__govt_debt_mn_sar` (from NDMC)
   - `fiscal__debt_to_gdp_pct` (from NDMC)
   - `fiscal__gdp_growth_pct` (from NDMC)
4. **Frequency:** Quarterly → duplicate to each month in quarter for alignment
5. **Stretch goal:** PDF table extraction using Docling (already in the stack)

**Acceptance:** `fiscal` domain in scorecards has real data, not "N/A".

---

### Phase 6 — Scheduled Signal Refresh

**Goal:** Signals recompute automatically when data changes.

**Options (pick one):**

| Option | Complexity | Recommended |
|--------|-----------|-------------|
| A. Run on startup + manual trigger | Low | ✅ For v1.0 |
| B. Cron job (APScheduler) | Medium | v1.1 |
| C. Event-driven (run after any upload/seed) | Medium | v1.1 |

**v1.0 approach (Option A):**
- Add `await run_signal_pipeline()` to `main.py` lifespan hook (after `seed_datasets`)
- Add `POST /api/signals/refresh` for manual trigger (admin only)
- Signals are fresh on every deploy (Railway redeploys = restart = re-run)

**Acceptance:** Deploying a new version to Railway automatically recomputes all signals.

---

### Phase 7 — Polish & Testing

#### 7A — Tests
- `tests/test_trend.py` — Known input series → expected signal classification
- `tests/test_anomaly.py` — Synthetic 4σ spike → expect critical bollinger_break
- `tests/test_scorecard.py` — All strong_up → aggregate = +100
- `tests/test_orchestrator_signal.py` — "What's the macro picture?" → intent = signal

#### 7B — Error Handling
- Signal engine returns graceful fallback if series has <12 observations
- Scorecard omits domains with no series data (shows "Insufficient data")
- Cross-series skips pairs where one series has no data

#### 7C — Logging
- Every signal pipeline run logged in `signal_runs` table
- Duration per series tracked
- Anomaly count per run for monitoring trends

---

## Execution Priority & Timeline

| Week | Phase | Deliverable | Demo Value |
|------|-------|-------------|------------|
| 1 | Phase 1 + 2A-2B | Signal tables + trend + anomaly computation | "The engine runs" |
| 2 | Phase 2C-2E | Cross-series + scorecards + runner | "Full quant pipeline" |
| 3 | Phase 3 | Orchestrator signal intent | **"Ask JadwaChat about macro outlook"** |
| 4 | Phase 4 | Signal dashboard in frontend | **Visual showpiece** |
| 5 | Phase 5 + 6 | Fiscal data + auto-refresh | Complete data coverage |
| 6 | Phase 7 | Tests + polish | Production confidence |

**Minimum impressive demo (Week 3):** User asks "What's the macro picture?" and gets a scorecard-backed answer with anomaly alerts — through the same chat interface they already use.

**Full impressive demo (Week 4):** User opens `/signals` dashboard, sees 5 domain gauges, clicks "Banking" to drill down, sees NPL ratio has a bollinger break alert, clicks it, and the chat opens with "Tell me more about the NPL anomaly" already answered.

---

## What Makes This Interview-Winning

1. **Same product, radically smarter.** You're not building two things. JadwaChat v0 retrieves data. v1.0 interprets it.

2. **The quant engine has no LLM.** All signals are deterministic math. The LLM only writes the narrative. This shows you understand that quant = formulas, not vibes.

3. **Domain scorecards prove you think like an investor.** You weighted oil at 35% because Saudi Arabia is an oil economy. You know which cross-series relationships matter. That's domain expertise, not just engineering.

4. **The chat + dashboard combo is unique.** Most quant tools are dashboards. Most chat tools are retrieval. You built both, connected. The dashboard shows the numbers, the chat explains them.

5. **It scales.** Today: 23 series across 3 sources. Tomorrow: 100 series, same pipeline. The architecture doesn't change.

---

## Files Changed / Created Summary

### New Files
```
backend/app/models/signals.py           — Signal SQLAlchemy models
backend/app/services/quant/__init__.py   — Package init
backend/app/services/quant/trend.py      — Trend + momentum signals
backend/app/services/quant/anomaly.py    — Anomaly detection
backend/app/services/quant/cross_series.py — Correlation monitoring
backend/app/services/quant/scorecard.py  — Domain scorecards
backend/app/services/quant/runner.py     — Pipeline orchestrator
backend/app/api/signals.py              — Signal API endpoints
backend/app/core/seed_fiscal.py         — MoF/NDMC data seeder
frontend/app/signals/page.tsx           — Dashboard page
frontend/components/ScoreGauge.tsx      — Gauge component
frontend/components/DomainCard.tsx      — Scorecard card
frontend/components/AnomalyTable.tsx    — Alert table
frontend/components/RadarChart.tsx      — 5-axis radar
tests/test_trend.py                     — Signal tests
tests/test_anomaly.py                   — Anomaly tests
tests/test_scorecard.py                 — Scorecard tests
```

### Modified Files
```
backend/app/services/orchestrator.py    — Add "signal" intent + handler
backend/app/main.py                     — Add signal_runs to lifespan, register signals router
backend/app/core/database.py            — Import new signal models for table creation
backend/app/models/schemas.py           — Add signal response schemas
frontend/components/Sidebar.tsx         — Add "Signals" nav link
frontend/app/layout.tsx                 — Add /signals route
```

### NOT Changed (Remains v0)
```
All existing analytics tools (latest, change, rolling, compare, top_movers)
All existing auth/upload/chat/collection endpoints
All existing frontend chat components
seed_datasets.py (SAMA/EIA data pipeline)
Docker/deployment config
```
