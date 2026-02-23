# JadwaChat v1.0 — Quant Signal Engine Specification

**For:** Agent implementation handoff
**Status:** v0 in production (Railway). This spec defines v1.0.
**Codebase:** `/Users/malkhudhayri/Desktop/Jadwa/rag-multi-database-chat/`

---

## 1. What the Signal Engine Does

The signal engine is a Python package at `backend/app/services/quant/` that:

1. **Reads** raw observations from the existing PostgreSQL `observations` table
2. **Computes** momentum indicators, anomaly flags, cross-series correlations, and domain scores
3. **Writes** results to 4 new PostgreSQL tables
4. **Exposes** results via new API endpoints and a new `"signal"` intent in the orchestrator

It has **zero external dependencies** beyond what's already installed. No new databases, no new services, no new deployments. It's a library inside the existing backend.

---

## 2. Production Data Inventory (What the Engine Operates On)

The engine processes **~64 series** across 3 collections already seeded in PostgreSQL:

### Collection: "SAMA" (source: SAMA) — 56 series

| CSV File | Series Count | Date Range | Key Series |
|----------|-------------|------------|------------|
| `sama_reserve_assets.csv` | 6 | 2001–2025 | `sama__total_reserves_mn_sar`, `sama__foreign_securities_mn_sar` |
| `sama_money_supply.csv` | 6 | 1993–2020 | `sama__m1_mn_sar`, `sama__m2_mn_sar`, `sama__other_quasi_money_mn_sar` |
| `sama_financial_soundness.csv` | 6 | 2009–2014 | `sama__capital_adequacy_ratio_pct`, `sama__npl_to_total_loans_pct`, `sama__return_on_equity_pct` |
| `sama_bank_deposits.csv` | 6 | 1993–2020 | `sama__demand_deposits_mn_sar`, `sama__time_savings_mn_sar` |
| `sama_bank_claims.csv` | 5 | 1993–2020 | `sama__total_credit_mn_sar`, `sama__loans_advances_mn_sar` |
| `sama_banking_ratios.csv` | 5 | 1995–2020 | `sama__reserves_to_deposits_pct`, `sama__private_claims_to_deposits_pct` |
| `sama_saibor_rates.csv` | 6 | 2007–2025 | `sama__saibor_3m`, `sama__repo_rate`, `sama__reverse_repo_rate` |
| `sama_rate_differentials.csv` | 6 | 2007–2025 | `sama__sar_3m`, `sama__usd_3m` (SAIBOR-SOFR differentials) |
| `sama_foreign_assets_liabilities.csv` | 8 | 1993–2020 | `sama__total_foreign_assets_mn_sar`, `sama__due_from_banks_abroad_mn_sar` |
| `sama_cpi.csv` | 5 | 2013–2025 | `sama__general_cpi`, `sama__food_beverages_cpi`, `sama__housing_utilities_cpi` |
| `sama_monetary_ratios.csv` | 3 | 1993–2020 | `sama__currency_to_m3_pct`, `sama__m1_to_m3_pct` |
| `sama_balance_of_payments.csv` | 6 | 2005–2025 | `sama__current_account_mn_usd`, `sama__services_net_mn_usd` |

### Collection: "Oil Markets" (source: EIA) — 5 series

| Series ID | Unit | Date Range |
|-----------|------|------------|
| `oil_markets__brent_price_usd_bbl` | USD/bbl | 1990–2027 |
| `oil_markets__wti_price_usd_bbl` | USD/bbl | 1990–2027 |
| `oil_markets__global_oil_demand_mn_bbl_day` | mn bbl/day | 1990–2027 |
| `oil_markets__global_oil_supply_mn_bbl_day` | mn bbl/day | 1993–2027 |
| `oil_markets__opec_crude_production_mn_bbl_day` | mn bbl/day | 1993–2027 |

### Collection: "KSA Oil Production" (source: EIA) — 3 series

| Series ID | Unit | Date Range |
|-----------|------|------------|
| `ksa_oil_production__ksa_crude_production_mn_bbl_day` | mn bbl/day | 1993–2026 |
| `ksa_oil_production__ksa_total_liquids_mn_bbl_day` | mn bbl/day | 1993–2026 |
| `ksa_oil_production__ksa_spare_capacity_mn_bbl_day` | mn bbl/day | 2003–2026 |

### NOT in production yet (fiscal gap)

| Series | Source | Status |
|--------|--------|--------|
| Government Revenue | MoF | PDFs uploaded to Qdrant, not structured |
| Government Expenditure | MoF | PDFs uploaded to Qdrant, not structured |
| Government Debt | NDMC | PDFs uploaded to Qdrant, not structured |
| Debt/GDP | NDMC | Not available |
| GDP Growth | NDMC | Not available |

---

## 3. Database Schema — New Tables

**File:** `backend/app/models/signals.py` (NEW)

All tables use the existing `Base` from `app.core.database` and the existing `_utcnow` helper.

### Table: `signal_snapshots`

One row per series per month. Stores all computed indicators + final classification.

```python
class SignalSnapshot(Base):
    __tablename__ = "signal_snapshots"
    __table_args__ = (
        Index("ix_signal_series_date", "series_id", "date", unique=True),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    series_id     = Column(String, nullable=False)     # FK to series_catalog
    date          = Column(Date, nullable=False)        # observation date
    value         = Column(Float, nullable=True)        # raw observation value

    # ── Momentum indicators ──
    mom_pct       = Column(Float, nullable=True)        # month-over-month % change
    qoq_pct       = Column(Float, nullable=True)        # quarter-over-quarter % change
    yoy_pct       = Column(Float, nullable=True)        # year-over-year % change
    z_score_12m   = Column(Float, nullable=True)        # (value - mean_12) / std_12
    percentile_36m = Column(Float, nullable=True)       # rank within last 36 months (0-100)
    sma_6         = Column(Float, nullable=True)        # 6-month simple moving average
    sma_12        = Column(Float, nullable=True)        # 12-month simple moving average
    trend_slope   = Column(Float, nullable=True)        # OLS slope of last 12m, normalized

    # ── Classification ──
    signal        = Column(String, nullable=True)       # strong_up|moderate_up|stable|...
    computed_at   = Column(DateTime, default=_utcnow)
```

### Table: `anomaly_alerts`

One row per detected anomaly. Stays `is_active=True` until the anomaly resolves.

```python
class AnomalyAlert(Base):
    __tablename__ = "anomaly_alerts"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    series_id     = Column(String, nullable=False)
    date          = Column(Date, nullable=False)
    alert_type    = Column(String, nullable=False)       # bollinger_break|trend_break|streak|level_shift
    severity      = Column(String, nullable=False)       # critical|warning|watch
    z_score       = Column(Float, nullable=True)
    description   = Column(Text, nullable=False)         # human-readable explanation
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=_utcnow)
    resolved_at   = Column(DateTime, nullable=True)
```

### Table: `domain_scorecards`

One row per domain per computation run.

```python
class DomainScorecard(Base):
    __tablename__ = "domain_scorecards"
    __table_args__ = (
        Index("ix_scorecard_domain_date", "domain", "date", unique=True),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    domain          = Column(String, nullable=False)     # oil|monetary|banking|bop|inflation
    date            = Column(Date, nullable=False)       # report date
    score           = Column(Float, nullable=False)      # -100 to +100
    direction       = Column(String, nullable=True)      # improving|stable|deteriorating
    prior_score     = Column(Float, nullable=True)       # previous month's score
    component_json  = Column(Text, nullable=True)        # JSON: {series_id: {signal, score, value}}
    alert_count     = Column(Integer, default=0)
    computed_at     = Column(DateTime, default=_utcnow)
```

### Table: `cross_series_alerts`

One row per pair divergence event.

```python
class CrossSeriesAlert(Base):
    __tablename__ = "cross_series_alerts"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    pair_name            = Column(String, nullable=False)  # "brent_vs_reserves"
    series_a_id          = Column(String, nullable=False)
    series_b_id          = Column(String, nullable=False)
    date                 = Column(Date, nullable=False)
    long_run_correlation = Column(Float, nullable=True)    # 24-month rolling
    recent_correlation   = Column(Float, nullable=True)    # 6-month rolling
    divergence           = Column(Float, nullable=True)    # abs(long - recent)
    description          = Column(Text, nullable=True)
    is_active            = Column(Boolean, default=True)
    created_at           = Column(DateTime, default=_utcnow)
```

### Table: `signal_runs`

Audit log for each pipeline execution.

```python
class SignalRun(Base):
    __tablename__ = "signal_runs"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    started_at        = Column(DateTime, default=_utcnow)
    finished_at       = Column(DateTime, nullable=True)
    status            = Column(String, default="running")  # running|success|failed
    series_processed  = Column(Integer, default=0)
    anomalies_found   = Column(Integer, default=0)
    divergences_found = Column(Integer, default=0)
    duration_ms       = Column(Integer, nullable=True)
    notes             = Column(Text, nullable=True)
```

**Migration:** Import these models in `database.py` so `Base.metadata.create_all()` picks them up automatically. No Alembic needed — the existing `init_db()` handles it.

---

## 4. Signal Computation — Full Algorithm Spec

### 4A. Trend & Momentum (`backend/app/services/quant/trend.py`)

#### Input
Read from `observations` table: all rows for a given `series_id`, sorted by date ascending.

#### Computed Indicators

| Indicator | Formula | Null if |
|-----------|---------|---------|
| `mom_pct` | `(V[t] - V[t-1]) / abs(V[t-1]) * 100` | < 2 observations |
| `qoq_pct` | `(V[t] - V[t-3]) / abs(V[t-3]) * 100` | < 4 observations |
| `yoy_pct` | `(V[t] - V[t-12]) / abs(V[t-12]) * 100` | < 13 observations |
| `z_score_12m` | `(V[t] - mean(V[t-11:t])) / std(V[t-11:t])` | < 12 observations |
| `percentile_36m` | rank of `V[t]` within `V[t-35:t]`, scaled 0–100 | < 12 observations |
| `sma_6` | `mean(V[t-5:t])` | < 6 observations |
| `sma_12` | `mean(V[t-11:t])` | < 12 observations |
| `trend_slope` | OLS slope of `V[t-11:t]` on `[0,1,...,11]`, divided by `mean(V[t-11:t])` | < 12 observations |

All percentage calculations use `abs()` in denominator to handle negative base values (e.g., current account deficits).

Division by zero guard: if denominator is 0, result is `None`.

#### Signal Classification

Evaluated in order — first match wins:

| # | Signal | Rule |
|---|--------|------|
| 1 | `reversal_up` | `mom_pct > 0` AND `yoy_pct < -5` |
| 2 | `reversal_down` | `mom_pct < 0` AND `yoy_pct > 5` |
| 3 | `strong_up` | `z_score_12m > 1.5` AND `mom_pct > 0` AND `yoy_pct > 5` |
| 4 | `strong_down` | `z_score_12m < -1.5` AND `mom_pct < 0` AND `yoy_pct < -5` |
| 5 | `moderate_up` | `mom_pct > 0` AND `yoy_pct > 0` |
| 6 | `moderate_down` | `mom_pct < 0` AND `yoy_pct < 0` |
| 7 | `stable` | default |

If any required indicator is `None`, signal = `None` (insufficient data).

#### Function Signature

```python
async def compute_series_signals(series_id: str) -> int:
    """
    Compute all indicators for one series. Write to signal_snapshots.
    Returns number of snapshots written.
    Idempotent: overwrites existing snapshots for same (series_id, date).
    """

async def compute_all_signals() -> dict[str, int]:
    """
    Run compute_series_signals for every series in series_catalog
    that has >= 12 observations. Returns {series_id: count}.
    """
```

---

### 4B. Anomaly Detection (`backend/app/services/quant/anomaly.py`)

Runs on the **latest data point** of each series. Produces 0 or more `AnomalyAlert` rows.

#### Anomaly Type 1: `bollinger_break`

**Logic:**
1. Compute 20-period SMA and standard deviation
2. Upper band = SMA + (width * std), Lower band = SMA - (width * std)
3. If latest value > upper or < lower → anomaly

**Domain-aware band width:**

| Domain (collection) | Bollinger Width | Rationale |
|---------------------|----------------|-----------|
| Oil Markets, KSA Oil Production | 2.5σ | Oil is structurally volatile |
| SAMA (series ending in `_pct`) | 1.5σ | Ratio shifts are significant |
| Everything else | 2.0σ | Standard |

**Severity:**
- `critical`: value > SMA ± 3.0σ
- `warning`: value > SMA ± 2.0σ (or domain-adjusted)
- No alert below threshold

**Description template:**
```
"{series_name} broke {'above' | 'below'} the {width}σ Bollinger Band.
Current: {value} {unit}. Band: [{lower:.2f}, {upper:.2f}].
Z-score: {z:.1f}. This level hasn't been seen since {last_breach_date}."
```

#### Anomaly Type 2: `trend_break`

**Logic:**
1. Check if value just crossed SMA-12 (was above/below for 6+ consecutive months, now on other side)
2. "Just crossed" = current month is on opposite side vs previous month

**Severity:** `warning`

**Description template:**
```
"{series_name} crossed {'above' | 'below'} its 12-month moving average
after {streak_months} months on the {'upper' | 'lower'} side.
SMA-12: {sma:.2f}, Current: {value:.2f}."
```

#### Anomaly Type 3: `streak`

**Logic:**
1. Count consecutive months where `mom_pct` has the same sign (positive or negative)
2. Alert if streak >= 6

**Severity:**
- `watch`: 6–8 months
- `warning`: 9+ months

**Description template:**
```
"{series_name} has {'risen' | 'fallen'} for {count} consecutive months.
Total change over streak: {total_pct:.1f}%."
```

#### Anomaly Type 4: `level_shift`

**Logic:**
1. Compute average absolute MoM change over last 24 months
2. If latest `abs(mom_pct)` > 3x that average → alert

**Severity:**
- `critical`: > 5x average
- `warning`: > 3x average

**Description template:**
```
"Unusual move in {series_name}: {mom_pct:+.1f}% MoM vs average |MoM| of {avg:.1f}%.
This is a {ratio:.1f}x deviation from normal monthly variation."
```

#### Function Signature

```python
async def detect_series_anomalies(series_id: str) -> list[dict]:
    """
    Run all 4 detectors on latest data for one series.
    Deactivate old alerts (is_active=False) if anomaly resolved.
    Write new alerts to anomaly_alerts table.
    Returns list of alert dicts.
    """

async def detect_all_anomalies() -> list[dict]:
    """Run across all series. Returns all alerts sorted by severity."""
```

---

### 4C. Cross-Series Intelligence (`backend/app/services/quant/cross_series.py`)

#### Monitored Pairs

10 pairs chosen for investment relevance to Saudi Arabia:

| # | Pair Name | Series A | Series B | Expected r | Investment Logic |
|---|-----------|----------|----------|-----------|-----------------|
| 1 | `brent_vs_reserves` | `oil_markets__brent_price_usd_bbl` | `sama__total_reserves_mn_sar` | +0.6 to +0.9 | Oil revenue flows into reserves |
| 2 | `brent_vs_current_account` | `oil_markets__brent_price_usd_bbl` | `sama__current_account_mn_usd` | +0.7 to +0.9 | Oil drives external balance |
| 3 | `credit_vs_deposits` | `sama__total_credit_mn_sar` | `sama__demand_deposits_mn_sar` | +0.8 to +0.95 | Credit cycle health — divergence = LDR stress |
| 4 | `saibor_vs_repo` | `sama__saibor_3m` | `sama__repo_rate` | +0.9+ | SAIBOR follows policy rate — divergence = liquidity stress |
| 5 | `npl_vs_credit` | `sama__npl_to_total_loans_pct` | `sama__total_credit_mn_sar` | -0.3 to -0.6 | Credit quality deteriorates when lending booms fade |
| 6 | `reserves_vs_m1` | `sama__total_reserves_mn_sar` | `sama__m1_mn_sar` | +0.5 to +0.8 | Reserve adequacy vs money creation |
| 7 | `brent_vs_wti` | `oil_markets__brent_price_usd_bbl` | `oil_markets__wti_price_usd_bbl` | +0.95+ | Normally locked — spread widening = market dislocation |
| 8 | `demand_vs_supply` | `oil_markets__global_oil_demand_mn_bbl_day` | `oil_markets__global_oil_supply_mn_bbl_day` | +0.9+ | Demand-supply gap = price pressure |
| 9 | `ksa_prod_vs_opec` | `ksa_oil_production__ksa_crude_production_mn_bbl_day` | `oil_markets__opec_crude_production_mn_bbl_day` | +0.7 to +0.9 | KSA as swing producer — divergence = policy shift |
| 10 | `cpi_vs_saibor` | `sama__general_cpi` | `sama__saibor_3m` | +0.3 to +0.6 | Inflation-rate response — divergence = real rate compression |

#### Divergence Detection Algorithm

```
For each pair:
  1. Load both series, align on overlapping dates
  2. If < 24 overlapping months → skip pair
  3. Compute 24-month rolling Pearson correlation (long_run)
  4. Compute 6-month rolling Pearson correlation (recent)
  5. divergence = abs(long_run[-1] - recent[-1])
  6. If divergence > 0.3 → create alert
```

**Severity:**
- `critical`: divergence > 0.5
- `warning`: divergence > 0.3

**Description template:**
```
"Divergence in {pair_name}: {series_a_name} and {series_b_name}
historically correlate at r={long_run:.2f} but recent 6-month
correlation dropped to r={recent:.2f} (divergence: {div:.2f}).
{investment_interpretation}"
```

The `investment_interpretation` is a static string per pair (from the table above).

#### Function Signature

```python
MONITORED_PAIRS = [
    {
        "name": "brent_vs_reserves",
        "a": "oil_markets__brent_price_usd_bbl",
        "b": "sama__total_reserves_mn_sar",
        "expected_sign": 1,
        "interpretation": "Oil revenue should flow into SAMA reserves. Divergence may indicate fiscal drawdown or capital outflow."
    },
    # ... 9 more
]

async def analyze_all_pairs() -> list[dict]:
    """Analyze all monitored pairs. Returns divergence alerts."""
```

---

### 4D. Domain Scorecards (`backend/app/services/quant/scorecard.py`)

#### Domains & Composition

5 domains, adapted to the **actual series_ids in production**:

```python
DOMAIN_CONFIG = {
    "oil": {
        "label": "Oil & Energy",
        "weight": 0.30,
        "series": {
            "oil_markets__brent_price_usd_bbl":                     0.25,
            "oil_markets__wti_price_usd_bbl":                       0.10,
            "ksa_oil_production__ksa_crude_production_mn_bbl_day":   0.20,
            "oil_markets__global_oil_demand_mn_bbl_day":             0.15,
            "oil_markets__global_oil_supply_mn_bbl_day":             0.10,
            "oil_markets__opec_crude_production_mn_bbl_day":         0.10,
            "ksa_oil_production__ksa_spare_capacity_mn_bbl_day":     0.10,
        },
    },
    "monetary": {
        "label": "Monetary & Reserves",
        "weight": 0.25,
        "series": {
            "sama__total_reserves_mn_sar":           0.20,
            "sama__m1_mn_sar":                       0.12,
            "sama__m2_mn_sar":                       0.12,
            "sama__other_quasi_money_mn_sar":         0.10,  # M3 proxy
            "sama__saibor_3m":                       0.12,
            "sama__repo_rate":                       0.10,
            "sama__foreign_currency_deposits_mn_sar": 0.12,
            "sama__reserves_to_deposits_pct":         0.12,
        },
    },
    "banking": {
        "label": "Banking Sector",
        "weight": 0.20,
        "series": {
            "sama__total_credit_mn_sar":             0.18,
            "sama__demand_deposits_mn_sar":           0.14,
            "sama__time_savings_mn_sar":              0.10,
            "sama__npl_to_total_loans_pct":           0.18,  # inverted: lower = better
            "sama__return_on_equity_pct":             0.14,
            "sama__capital_adequacy_ratio_pct":       0.14,
            "sama__private_claims_to_deposits_pct":   0.12,
        },
    },
    "bop": {
        "label": "Balance of Payments",
        "weight": 0.15,
        "series": {
            "sama__current_account_mn_usd":          0.40,
            "sama__goods_mn_usd":                    0.25,
            "sama__services_net_mn_usd":             0.20,
            "sama__total_foreign_assets_mn_sar":      0.15,
        },
    },
    "inflation": {
        "label": "Inflation & Prices",
        "weight": 0.10,
        "series": {
            "sama__general_cpi":                     0.40,
            "sama__food_beverages_cpi":               0.20,
            "sama__housing_utilities_cpi":             0.25,
            "sama__transport_cpi":                    0.15,
        },
    },
}
```

**Note:** Domain weights sum to 1.0. Series weights within each domain sum to 1.0.

#### Score Calculation

```python
SIGNAL_SCORES = {
    "strong_up":     +100,
    "moderate_up":    +50,
    "stable":           0,
    "moderate_down":  -50,
    "strong_down":   -100,
    "reversal_up":    +30,
    "reversal_down":  -30,
}

# Special: inverted series (where DOWN = GOOD)
INVERTED_SERIES = {
    "sama__npl_to_total_loans_pct",   # lower NPL = better
    # CPI series are NOT inverted — rising CPI is just "up", analyst decides if bad
}
```

For inverted series, multiply the score by -1.

**Domain score** = weighted sum of component scores.
**Direction** = compare current domain score to prior month's domain score:
- `improving`: current > prior + 5
- `deteriorating`: current < prior - 5
- `stable`: within ±5

**Aggregate score** = weighted sum of domain scores using domain weights.

#### Function Signature

```python
async def compute_domain_scorecard(domain: str, report_date: date) -> dict:
    """
    Read latest signal_snapshot for each series in the domain.
    Compute weighted score. Compare to prior month. Write to domain_scorecards.
    Returns scorecard dict.
    """

async def compute_all_scorecards(report_date: date = None) -> list[dict]:
    """Compute all 5 domain scorecards + aggregate. Returns list of dicts."""
```

---

### 4E. Pipeline Runner (`backend/app/services/quant/runner.py`)

```python
async def run_signal_pipeline() -> dict:
    """
    Master pipeline — runs everything in sequence:

    1. Query series_catalog for all series with >= 12 observations
    2. For each: compute_series_signals()     → writes signal_snapshots
    3. For each: detect_series_anomalies()    → writes anomaly_alerts
    4. Run analyze_all_pairs()                → writes cross_series_alerts
    5. Run compute_all_scorecards()           → writes domain_scorecards
    6. Log signal_run with timing + counts

    Returns:
    {
        "series_processed": 48,
        "signals_written": 4200,
        "anomalies_found": 3,
        "divergences_found": 1,
        "scorecards": [{"domain": "oil", "score": 42}, ...],
        "duration_ms": 8500,
    }
    """
```

**Performance target:** < 30 seconds for 64 series on Railway.

**When it runs:**
- On server startup (after `seed_datasets()` in `main.py` lifespan hook)
- On manual trigger via `POST /api/signals/refresh`
- Idempotent: safe to re-run

---

## 5. API Endpoints

**File:** `backend/app/api/signals.py` (NEW)

**Router:** `APIRouter(prefix="/signals", tags=["Signals"])`

| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/api/signals/dashboard` | Required | Full dashboard JSON (all scorecards + active anomalies + divergences) |
| GET | `/api/signals/scorecards` | Required | List of 5 domain scorecards + aggregate |
| GET | `/api/signals/domain/{domain}` | Required | Single domain detail with component-level signals |
| GET | `/api/signals/anomalies` | Required | Active anomaly alerts, sorted by severity |
| GET | `/api/signals/series/{series_id}` | Required | Signal history for one series (last 24 months) |
| GET | `/api/signals/cross-series` | Required | All cross-series pair correlations + active divergence alerts |
| POST | `/api/signals/refresh` | Required | Trigger pipeline re-run. Returns summary. |
| GET | `/api/signals/health` | None | Last signal_run timestamp + status |

### Dashboard Response Shape

```json
{
  "report_date": "2025-12-31",
  "aggregate_score": 22.5,
  "aggregate_direction": "improving",
  "scorecards": [
    {
      "domain": "oil",
      "label": "Oil & Energy",
      "score": 42.0,
      "direction": "improving",
      "prior_score": 35.0,
      "alert_count": 0,
      "components": {
        "oil_markets__brent_price_usd_bbl": {
          "name": "Brent Price",
          "signal": "moderate_up",
          "value": 78.2,
          "unit": "USD/bbl",
          "mom_pct": 4.2,
          "yoy_pct": 12.1,
          "z_score": 0.8
        }
      }
    }
  ],
  "anomalies": [
    {
      "series_id": "sama__npl_to_total_loans_pct",
      "series_name": "Npl To Total Loans",
      "alert_type": "bollinger_break",
      "severity": "warning",
      "z_score": -2.1,
      "description": "..."
    }
  ],
  "cross_series_alerts": [
    {
      "pair_name": "brent_vs_reserves",
      "long_run_correlation": 0.87,
      "recent_correlation": 0.42,
      "divergence": 0.45,
      "description": "..."
    }
  ],
  "last_run": "2026-02-21T10:30:00Z",
  "series_count": 48
}
```

---

## 6. Orchestrator Integration — "signal" Intent

**File:** `backend/app/services/orchestrator.py` (MODIFY)

### 6A. Add to Intent Classifier Prompt

Add this to the existing `CLASSIFY_SYSTEM_PROMPT`:

```
  signal   - The user wants macro analysis, signals, anomalies, domain
             scorecards, regime assessment, cross-series insights, or
             the "big picture" view. These go beyond raw data retrieval.
             Examples: "What's happening in oil?", "Any anomalies?",
             "Give me the macro scorecard", "Is banking deteriorating?",
             "How does oil relate to reserves?",
             "What should I watch this month?", "Macro outlook?"
```

Update the valid intents list: `("data", "document", "mixed", "general", "signal")`

### 6B. Add Signal Handler to Orchestrator

```python
async def _handle_signal(self, question: str) -> tuple:
    """Route signal queries to the quant engine.

    Returns (context_str, series_used, tools_called, citations)
    same tuple shape as _handle_data.
    """
```

**Sub-routing logic (keyword-based, inside `_handle_signal`):**

| Keywords in question | Action |
|---------------------|--------|
| "scorecard", "macro", "overview", "outlook", "picture", "dashboard" | Fetch full dashboard |
| "anomaly", "anomalies", "unusual", "alert", "watch", "flag" | Fetch anomaly list |
| domain name ("oil", "banking", "monetary", "bop", "inflation") | Fetch domain scorecard |
| "compare", "relationship", "correlation", "diverge" | Fetch cross-series |
| specific series name | Fetch series signal detail |
| default | Full dashboard + active anomalies |

**Context formatting** — the handler builds a structured text block that the LLM uses to write its answer:

```
MACRO SIGNAL REPORT (as of 2025-12-31)
───────────────────────────────────────

AGGREGATE: +22.5 (improving ↑)

DOMAIN SCORECARDS:
  Oil & Energy:         +42.0 (improving ↑)  [7 series, 0 alerts]
  Monetary & Reserves:  +18.0 (stable →)     [8 series, 0 alerts]
  Banking Sector:       -12.0 (deteriorating ↓) [7 series, 1 alert]
  Balance of Payments:   +5.0 (stable →)     [4 series, 0 alerts]
  Inflation & Prices:   +28.0 (improving ↑)  [4 series, 0 alerts]

ACTIVE ANOMALIES (1):
  ⚠️ [warning] NPL Ratio: Bollinger band break (z=-2.1)
     NPL to Total Loans at 1.8%, below 20-month lower band.

CROSS-SERIES DIVERGENCES (1):
  ⚠️ [warning] Brent vs Reserves (r dropped 0.87 → 0.42)
     Oil revenue should flow into SAMA reserves.
     Divergence may indicate fiscal drawdown or capital outflow.

COMPONENT DETAIL (Oil & Energy):
  Brent Price:          moderate_up  (+4.2% MoM, +12.1% YoY, z=+0.8)
  KSA Crude Production: stable       (-0.1% MoM, +0.3% YoY, z=-0.02)
  ...
```

### 6C. Wire into `ask()` Method

In the `ask()` method, add after the `if intent in ("data", "mixed"):` block:

```python
if intent == "signal":
    signal_context, series_used, signal_tools, signal_citations = await self._handle_signal(question)
    data_context = signal_context
    tools_called.extend(signal_tools)
    citations.extend(signal_citations)
    has_db_context = True
    knowledge_source = "signal_engine"
```

Also update `_generate_answer` system prompt to handle `knowledge_source == "signal_engine"`:

```python
elif knowledge_source == "signal_engine":
    system += (
        "8. Your answer is based on the QUANT SIGNAL ENGINE. The data below "
        "contains computed indicators (z-scores, MoM%, YoY%, signals, anomalies). "
        "Synthesize this into a clear, analyst-level narrative. Be specific with "
        "numbers. Highlight what's unusual. Give actionable insight.\n"
    )
```

---

## 7. Frontend — Signal Dashboard Page

### New Files

| File | Purpose |
|------|---------|
| `frontend/app/signals/page.tsx` | Main dashboard page |
| `frontend/components/signals/ScoreGauge.tsx` | Semicircle gauge component (-100 to +100) |
| `frontend/components/signals/DomainCard.tsx` | Expandable domain card |
| `frontend/components/signals/AnomalyTable.tsx` | Sortable alert list |
| `frontend/components/signals/RadarChart.tsx` | 5-axis domain radar (Recharts or raw SVG) |

### Dashboard Layout

```
┌──────────────────────────────────────────────────────────────┐
│  ← Back to Chat        MACRO SIGNAL DASHBOARD        ⟳ Refresh │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────────────┐  ┌───────────────────────────┐  │
│  │    AGGREGATE SCORE      │  │     DOMAIN RADAR CHART    │  │
│  │                         │  │                           │  │
│  │      ╭───────╮          │  │         Oil               │  │
│  │    ╱     +22    ╲       │  │      ╱     ╲              │  │
│  │   ╱   improving  ╲     │  │  Infl ─── ──── Monetary   │  │
│  │   ╲               ╱    │  │      ╲     ╱              │  │
│  │    ╲─────────────╱     │  │    BoP ─── Banking        │  │
│  │                         │  │                           │  │
│  └─────────────────────────┘  └───────────────────────────┘  │
│                                                               │
│  ┌── Oil & Energy ────── +42 ↑ ────────────────────────────┐ │
│  │  Brent Price      moderate_up  $78.2  +4.2% MoM        │ │
│  │  KSA Production   stable       9.0    -0.1% MoM        │ │
│  │  Global Demand    moderate_up  103.1  +0.8% MoM        │ │
│  │  ...                                                     │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌── Anomaly Alerts (1) ────────────────────────────────────┐ │
│  │  ⚠️ NPL Ratio   bollinger_break  warning  z=-2.1       │ │
│  │     → Ask JadwaChat about this                           │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### Design Specs
- **Colors:** Jadwa Navy `#1B365D`, Gold `#C8A951`, White `#FFFFFF`
- **Signal badges:** Green (up), Yellow (stable/reversal), Red (down)
- **Severity badges:** Red (critical), Orange (warning), Blue (watch)
- **"Ask JadwaChat"** button on anomalies → navigates to chat, pre-fills question
- **Mobile:** Cards stack vertically, radar chart hidden on small screens
- **Refresh button:** Calls `POST /api/signals/refresh`, shows spinner, reloads

### Sidebar Addition

Add a 📊 icon button below the existing sidebar items that navigates to `/signals`.

---

## 8. Startup Sequence (Modified `main.py`)

```python
async def lifespan(app: FastAPI):
    # ... existing startup ...

    # Seed SAMA/EIA datasets from shipped CSVs
    try:
        await seed_datasets()
    except Exception as e:
        logger.warning(f"⚠️  Dataset seeding failed: {e}")

    # ★ NEW: Run signal pipeline after data is seeded
    try:
        from app.services.quant.runner import run_signal_pipeline
        result = await run_signal_pipeline()
        logger.info(
            f"✅ Signal pipeline: {result['series_processed']} series, "
            f"{result['anomalies_found']} anomalies, "
            f"{result['duration_ms']}ms"
        )
    except Exception as e:
        logger.warning(f"⚠️  Signal pipeline failed: {e}")

    # ... rest of startup ...
```

---

## 9. File Tree — What to Create

```
backend/app/
├── models/
│   └── signals.py                        ← NEW (5 SQLAlchemy models)
├── services/
│   ├── quant/
│   │   ├── __init__.py                   ← NEW
│   │   ├── trend.py                      ← NEW (Section 4A)
│   │   ├── anomaly.py                    ← NEW (Section 4B)
│   │   ├── cross_series.py               ← NEW (Section 4C)
│   │   ├── scorecard.py                  ← NEW (Section 4D)
│   │   └── runner.py                     ← NEW (Section 4E)
│   └── orchestrator.py                   ← MODIFY (Section 6)
├── api/
│   └── signals.py                        ← NEW (Section 5)
├── core/
│   └── database.py                       ← MODIFY (import signals models)
└── main.py                               ← MODIFY (Section 8)

frontend/
├── app/
│   └── signals/
│       └── page.tsx                      ← NEW (Section 7)
├── components/
│   └── signals/
│       ├── ScoreGauge.tsx                ← NEW
│       ├── DomainCard.tsx                ← NEW
│       ├── AnomalyTable.tsx              ← NEW
│       └── RadarChart.tsx                ← NEW
└── components/
    └── Sidebar.tsx                       ← MODIFY (add signals nav)

tests/
├── test_trend.py                         ← NEW
├── test_anomaly.py                       ← NEW
└── test_scorecard.py                     ← NEW
```

---

## 10. Implementation Order

| Step | Files | Depends On | Test |
|------|-------|------------|------|
| 1 | `models/signals.py` + import in `database.py` | Nothing | Server starts, tables created |
| 2 | `quant/trend.py` | Step 1 | `compute_all_signals()` writes snapshots |
| 3 | `quant/anomaly.py` | Step 2 | `detect_all_anomalies()` finds anomalies |
| 4 | `quant/cross_series.py` | Step 1 | `analyze_all_pairs()` returns correlations |
| 5 | `quant/scorecard.py` | Step 2 | `compute_all_scorecards()` returns 5 scores |
| 6 | `quant/runner.py` | Steps 2-5 | Full pipeline runs in <30s |
| 7 | `api/signals.py` + register in `main.py` | Step 6 | `/api/signals/dashboard` returns JSON |
| 8 | Orchestrator `"signal"` intent | Step 7 | "What's the macro picture?" works in chat |
| 9 | Frontend dashboard | Step 7 | `/signals` page renders |
| 10 | Tests | Steps 2-5 | `pytest tests/` passes |

**Each step is independently testable.** Step 6 is the first "wow" moment (full pipeline). Step 8 is the demo moment (chat understands signals).

---

## 11. Agentic Mode (v1.1 — Design for It Now, Build Later)

### Why This Section Exists

v1.0 uses a **pipeline**: classify intent → pick one handler → call it → format → answer. That works for direct questions ("What's the Brent price?", "Show me the scorecard").

But analysts ask **complex questions** that need multi-step reasoning:

- *"Why are SAMA reserves declining while oil prices are rising?"*
- *"What should I be worried about this month?"*
- *"Compare the banking sector now vs 2019"*
- *"Write me a CIO brief on the macro picture"*

These need the LLM to **decide what data to pull, look at results, then decide what else to pull** — an agentic loop.

v1.1 will add this. But v1.0 must be **built agent-ready** so the upgrade is a thin wrapper, not a rewrite.

### What "Agent-Ready" Means for v1.0 (Design Constraints)

**CRITICAL: The implementing agent must follow these rules so that v1.1 agentic mode is a 1-day addition, not a 1-week rewrite.**

#### Rule 1: Every quant function must be a standalone async callable

Each function in `quant/` must:
- Accept simple arguments (strings, ints, optional dates)
- Return a plain `dict` (JSON-serializable)
- Not depend on orchestrator state
- Have a clear docstring (this becomes the tool description for the LLM)

```python
# ✅ GOOD — agent-callable
async def get_scorecard(domain: str) -> dict:
    """Get the signal scorecard for a domain.
    Args:
        domain: One of 'oil', 'monetary', 'banking', 'bop', 'inflation', or 'all'.
    Returns:
        Dict with score (-100 to +100), direction, component signals, and alerts.
    """

# ❌ BAD — coupled to pipeline
def _format_scorecard_context(scorecard, question, citations_list):
    # This mixes data retrieval with orchestrator formatting
```

#### Rule 2: Create a tool registry

**File:** `backend/app/services/quant/tools.py` (NEW in v1.0)

This file defines every callable tool with its metadata. In v1.0 it's used by `_handle_signal()` for sub-routing. In v1.1 it becomes the OpenAI function-calling schema with zero changes.

```python
"""Tool registry — every quant function the orchestrator (or agent) can call.

Each tool has:
  - name: unique identifier
  - description: what it does (becomes OpenAI tool description in v1.1)
  - function: the async callable
  - parameters: JSON Schema for arguments (becomes OpenAI tool schema in v1.1)
"""

from app.services.quant.trend import get_series_signal, get_latest_signal
from app.services.quant.anomaly import get_active_anomalies, get_series_anomalies
from app.services.quant.cross_series import get_pair_analysis, get_all_divergences
from app.services.quant.scorecard import get_scorecard, get_all_scorecards, get_aggregate_score
from app.services import analytics

TOOL_REGISTRY = [
    # ── Data tools (existing analytics.py) ──
    {
        "name": "latest",
        "description": "Get the most recent observation value for a time series. Use when the user asks for a current number.",
        "function": analytics.latest,
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "string",
                    "description": "The series identifier, e.g. 'oil_markets__brent_price_usd_bbl'"
                }
            },
            "required": ["series_id"]
        }
    },
    {
        "name": "change",
        "description": "Calculate period-over-period change (MoM, QoQ, YoY) for a series. Use when the user asks about growth, decline, or change.",
        "function": analytics.change,
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string"},
                "method": {
                    "type": "string",
                    "enum": ["MoM", "QoQ", "YoY"],
                    "description": "Period: MoM (month-over-month), QoQ (quarter), YoY (year)"
                }
            },
            "required": ["series_id"]
        }
    },
    {
        "name": "rolling",
        "description": "Calculate rolling statistics (mean, std, min, max) over a window. Use for trend analysis or volatility.",
        "function": analytics.rolling,
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string"},
                "window": {"type": "integer", "description": "Rolling window in months (default 12)"},
                "method": {"type": "string", "enum": ["mean", "std", "min", "max"]}
            },
            "required": ["series_id"]
        }
    },
    {
        "name": "compare",
        "description": "Compare two series: Pearson correlation, trend direction, latest values. Use when the user asks about relationships between indicators.",
        "function": analytics.compare,
        "parameters": {
            "type": "object",
            "properties": {
                "series_a": {"type": "string", "description": "First series ID"},
                "series_b": {"type": "string", "description": "Second series ID"},
                "window": {"type": "integer", "description": "Overlapping periods to use (default 24)"}
            },
            "required": ["series_a", "series_b"]
        }
    },
    {
        "name": "top_movers",
        "description": "Find the series with the biggest changes in a domain or across all domains. Use for market scanning.",
        "function": analytics.top_movers,
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Optional domain filter"},
                "period": {"type": "string", "enum": ["MoM", "QoQ", "YoY"]},
                "limit": {"type": "integer", "description": "Number of results (default 5)"}
            }
        }
    },
    {
        "name": "get_series",
        "description": "Get raw time series observations for a date range. Use when the user asks for historical data.",
        "function": analytics.get_series,
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string"},
                "start": {"type": "string", "description": "Start date YYYY-MM-DD"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"}
            },
            "required": ["series_id"]
        }
    },

    # ── Signal tools (new quant engine) ──
    {
        "name": "get_scorecard",
        "description": "Get the macro signal scorecard for a domain (oil, monetary, banking, bop, inflation) or 'all' for the full dashboard. Returns score (-100 to +100), direction, component signals, and any anomaly alerts. Use for macro overview questions.",
        "function": "quant.scorecard.get_scorecard",  # resolved at import time
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["oil", "monetary", "banking", "bop", "inflation", "all"],
                    "description": "Domain to score, or 'all' for aggregate"
                }
            },
            "required": ["domain"]
        }
    },
    {
        "name": "get_anomalies",
        "description": "Get active anomaly alerts across all series. Returns unusual movements that need analyst attention: Bollinger band breaks, trend breaks, streaks, and level shifts. Sorted by severity (critical > warning > watch).",
        "function": "quant.anomaly.get_active_anomalies",
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["all", "critical", "warning", "watch"],
                    "description": "Filter by severity level (default: all)"
                }
            }
        }
    },
    {
        "name": "get_series_signal",
        "description": "Get the full signal analysis for a specific series: current value, MoM/QoQ/YoY change, z-score, percentile, signal classification, and any active anomalies. Use when the user asks about a specific indicator's trend or status.",
        "function": "quant.trend.get_series_signal",
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string"}
            },
            "required": ["series_id"]
        }
    },
    {
        "name": "get_cross_series",
        "description": "Get cross-series correlation analysis and divergence alerts. Shows which historically correlated pairs are diverging, with investment interpretation. Use when the user asks about relationships between macro indicators.",
        "function": "quant.cross_series.get_all_divergences",
        "parameters": {
            "type": "object",
            "properties": {
                "pair_name": {
                    "type": "string",
                    "description": "Optional: specific pair (e.g. 'brent_vs_reserves'). Omit for all pairs."
                }
            }
        }
    },
    {
        "name": "search_documents",
        "description": "Search uploaded documents (PDFs, reports) for qualitative information. Use when the user asks about report contents, definitions, or methodology.",
        "function": "rag.search",  # wrapper around vectorstore.similarity_search_all
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    },
]


def get_tool_by_name(name: str) -> dict:
    """Lookup a tool by name."""
    for tool in TOOL_REGISTRY:
        if tool["name"] == name:
            return tool
    return None


def get_openai_tools_schema() -> list[dict]:
    """Convert registry to OpenAI function-calling format.
    Used in v1.1 agentic mode.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
        }
        for t in TOOL_REGISTRY
    ]


async def execute_tool(name: str, arguments: dict) -> dict:
    """Execute a tool by name with given arguments.
    Used by both _handle_signal (v1.0) and agent loop (v1.1).
    """
    tool = get_tool_by_name(name)
    if not tool:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = await tool["function"](**arguments)
        return result
    except Exception as e:
        return {"error": f"Tool '{name}' failed: {str(e)}"}
```

#### Rule 3: `_handle_signal` must use the tool registry

In v1.0, `_handle_signal()` does keyword-based sub-routing but calls tools through `execute_tool()`:

```python
async def _handle_signal(self, question: str) -> tuple:
    from app.services.quant.tools import execute_tool

    q = question.lower()

    if any(kw in q for kw in ("anomaly", "anomalies", "unusual", "alert")):
        result = await execute_tool("get_anomalies", {"severity": "all"})
        # ... format context
    elif any(kw in q for kw in ("scorecard", "macro", "overview", "outlook")):
        result = await execute_tool("get_scorecard", {"domain": "all"})
        # ... format context
    # ... etc
```

This means when v1.1 adds the agent loop, it uses the **same `execute_tool()`** function — just called by the LLM instead of by keyword matching.

#### Rule 4: Every tool function must include a `_available_series` helper

The agent needs to know what series exist. Add this to the tool registry:

```python
{
    "name": "list_available_series",
    "description": "List all available time series with their IDs, names, domains, and units. Call this first when unsure which series_id to use.",
    "function": "discovery.get_all_series",
    "parameters": {"type": "object", "properties": {}}
},
{
    "name": "discover_series",
    "description": "Find the best matching series for a natural language query. Returns top matches with relevance scores.",
    "function": "discovery.search",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural language description of the data needed"},
            "top_k": {"type": "integer", "description": "Number of results (default 5)"}
        },
        "required": ["query"]
    }
}
```

This lets the agent resolve "reserves" → `sama__total_reserves_mn_sar` without hardcoded mappings.

---

### v1.1 Agentic Implementation (Future — NOT Built in v1.0)

Once v1.0 is done with the above constraints, adding agent mode is a **single file change**:

#### New intent: `"analysis"`

Add to the classifier prompt:
```
  analysis - The user's question requires multi-step reasoning, combining
             data from multiple sources, or explaining WHY something is
             happening. Cannot be answered with a single tool call.
             Examples: "Why are reserves declining while oil is rising?",
             "What should I worry about?", "Write me a macro brief",
             "Compare banking sector now vs 2019",
             "What's driving the current account surplus?"
```

#### Agent loop in orchestrator

```python
async def _handle_analysis(self, question: str, chat_history: list) -> tuple:
    """Agentic mode: LLM picks tools iteratively.

    The LLM gets access to all tools in TOOL_REGISTRY and decides:
    1. Which tool to call first
    2. What to do with the result
    3. Whether it needs more data (call another tool)
    4. When it has enough to synthesize an answer

    Max 6 tool calls per question to prevent runaway costs.
    """
    from app.services.quant.tools import get_openai_tools_schema, execute_tool

    tools_schema = get_openai_tools_schema()
    tools_called = []
    series_used = set()
    citations = []

    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        *chat_history,
        {"role": "user", "content": question},
    ]

    for round_num in range(6):  # max 6 tool calls
        response = await openai.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools_schema,
            tool_choice="auto",
        )

        choice = response.choices[0]

        # If the LLM is done reasoning, it returns a final text answer
        if choice.finish_reason == "stop":
            final_answer = choice.message.content
            break

        # Otherwise, execute whatever tools the LLM requested
        for tool_call in choice.message.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            result = await execute_tool(name, args)
            tools_called.append(f"{name}({args})")

            # Track series for citations
            if "series_id" in args:
                series_used.add(args["series_id"])

            # Feed result back to the LLM
            messages.append(choice.message)  # assistant's tool_call message
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result),
            })

    context = f"Agent completed {len(tools_called)} tool calls."
    return context, list(series_used), tools_called, citations
```

#### Agent system prompt

```python
AGENT_SYSTEM_PROMPT = """You are JadwaChat's analysis agent for Jadwa Investment.

You have access to tools that query Saudi macroeconomic data (oil, banking,
monetary, fiscal, balance of payments) and a quant signal engine that computes
trend signals, anomaly alerts, domain scorecards, and cross-series correlations.

Your job:
1. Break the user's question into the data you need
2. Call the right tools to gather that data
3. Look at the results and decide if you need more
4. Synthesize everything into a clear, analyst-level answer

Rules:
- Always start with discover_series or get_scorecard to orient yourself
- Use specific numbers and cite series names
- If you see an anomaly, investigate it (call get_series_signal for details)
- Max 6 tool calls — be efficient
- Support English and Arabic
- Be concise and professional
"""
```

#### Cost & Performance Controls

| Control | Value | Why |
|---------|-------|-----|
| Max tool calls | 6 per question | Prevents runaway API costs |
| Model | GPT-4o (not 4o-mini) | Mini can't reason about tool selection well |
| Timeout | 45 seconds total | User patience limit with streaming |
| Fallback | If agent fails, fall back to signal pipeline | Never leave user with no answer |
| Cost estimate | ~$0.03-0.05 per agent question | ~3-5x pipeline cost, acceptable for analyst tool |

#### When to trigger

The intent classifier decides. Add a confidence hint:

```
Set intent to "analysis" ONLY when the question clearly requires multiple
data points or reasoning about relationships. When in doubt, use "signal"
(single-step) rather than "analysis" (multi-step).
```

---

### v1.1 Summary: What Changes vs v1.0

| Component | v1.0 (build now) | v1.1 (future, thin upgrade) |
|-----------|-------------------|------------------------------|
| Tool registry | ✅ Built. Used by `_handle_signal` keyword routing | Same registry, now also used by agent loop |
| `execute_tool()` | ✅ Built. Called by keyword router | Same function, now also called by LLM |
| `get_openai_tools_schema()` | ✅ Built. Not used yet | Now feeds into `openai.chat.completions.create(tools=...)` |
| Intent classifier | 5 intents (data/document/mixed/general/signal) | 6 intents (+analysis) |
| `_handle_analysis()` | ❌ Not built | NEW: 60 lines, agent loop |
| `AGENT_SYSTEM_PROMPT` | ❌ Not built | NEW: 15 lines |
| Frontend | No changes needed | No changes needed (same streaming SSE) |
| Database | No changes needed | No changes needed |
| Cost | ~$0.01/question | ~$0.03-0.05 for agent questions |

**Total v1.1 diff:** ~100 lines of Python. That's the payoff of building agent-ready in v1.0.

---

## 12. Updated Implementation Order (Including Agent Readiness)

| Step | Files | Depends On | Test | Agent-Ready? |
|------|-------|------------|------|-------------|
| 1 | `models/signals.py` + import in `database.py` | Nothing | Server starts, tables created | N/A |
| 2 | `quant/trend.py` | Step 1 | `compute_all_signals()` writes snapshots | ✅ Functions return plain dicts |
| 3 | `quant/anomaly.py` | Step 2 | `detect_all_anomalies()` finds anomalies | ✅ Functions return plain dicts |
| 4 | `quant/cross_series.py` | Step 1 | `analyze_all_pairs()` returns correlations | ✅ Functions return plain dicts |
| 5 | `quant/scorecard.py` | Step 2 | `compute_all_scorecards()` returns 5 scores | ✅ Functions return plain dicts |
| 6 | `quant/runner.py` | Steps 2-5 | Full pipeline runs in <30s | N/A |
| 7 | **`quant/tools.py`** ⭐ | Steps 2-5 + existing analytics | Tool registry loads, `execute_tool` works | ✅ **This is the agent bridge** |
| 8 | `api/signals.py` + register in `main.py` | Steps 6-7 | `/api/signals/dashboard` returns JSON | N/A |
| 9 | Orchestrator `"signal"` intent (uses tools.py) | Steps 7-8 | "What's the macro picture?" works in chat | ✅ Uses `execute_tool()` |
| 10 | Frontend dashboard | Step 8 | `/signals` page renders | N/A |
| 11 | Tests | Steps 2-5 | `pytest tests/` passes | N/A |

**Step 7 is new and critical.** It's the bridge between v1.0 pipeline and v1.1 agent. Build it in v1.0 even though the agent loop doesn't exist yet.

---

## 13. Design Principles (Summary for Implementing Agent)

1. **Every quant function returns a plain dict.** No formatting, no citations, no orchestrator coupling. Data in → dict out.
2. **The tool registry is the single source of truth** for what the system can do. Both the pipeline router and the future agent loop read from it.
3. **`execute_tool(name, args)` is the universal executor.** Never call quant functions directly from the orchestrator — always go through the registry.
4. **The signal intent uses keyword sub-routing in v1.0**, but it routes through `execute_tool()` so the upgrade to LLM-driven routing in v1.1 is a swap, not a rewrite.
5. **No new dependencies for agent mode.** OpenAI function calling is already supported by `langchain-openai`. The agent loop is raw `openai` SDK or LangChain — either works since both are installed.
6. **Streaming works identically.** The agent loop collects tool results, then streams the final synthesis through the same SSE pipeline. No frontend changes needed.
