"""IC Memo Autopilot — one-click Investment Committee memo from signal data.

Takes a topic (e.g. "Saudi banking liquidity"), gathers all relevant signal
engine data, ML model outputs, and asks the LLM to produce a structured
IC-style memo: Thesis → Risks → Scenarios → Recommendation.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings
from app.services.quant.scorecard import get_all_scorecards, get_scorecard
from app.services.quant.anomaly import get_active_anomalies
from app.services.quant.cross_series import get_all_divergences

logger = logging.getLogger(__name__)

# Domain keyword mapping for relevance filtering
DOMAIN_KEYWORDS = {
    "oil": ["oil", "crude", "brent", "opec", "petroleum", "energy", "aramco"],
    "monetary": ["monetary", "money supply", "reserves", "sama", "interest", "rate", "liquidity", "m3", "repo"],
    "banking": ["bank", "credit", "loan", "deposit", "lending", "npl", "capital adequacy", "liquidity"],
    "bop": ["balance of payments", "trade", "export", "import", "current account", "capital flow", "fdi"],
    "inflation": ["inflation", "cpi", "price", "cost of living", "deflation", "consumer price"],
}


def _detect_relevant_domains(topic: str) -> list[str]:
    """Match topic text to relevant macro domains."""
    topic_lower = topic.lower()
    matched = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(kw in topic_lower for kw in keywords):
            matched.append(domain)
    return matched or list(DOMAIN_KEYWORDS.keys())


async def _gather_signal_context(topic: str) -> str:
    """Pull all signal data relevant to the topic into a structured text block."""
    sections = []
    relevant_domains = _detect_relevant_domains(topic)

    # 1. Scorecards
    try:
        all_scorecards = await get_all_scorecards()
        sections.append(f"AGGREGATE MACRO SCORE: {all_scorecards.get('aggregate_score', 0)} ({all_scorecards.get('aggregate_direction', 'stable')})")
        sections.append("")

        for card in all_scorecards.get("scorecards", []):
            domain = card.get("domain", "")
            label = card.get("label", domain)
            score = card.get("score", 0)
            direction = card.get("direction", "stable")
            alert_count = card.get("alert_count", 0)
            marker = " ← FOCUS" if domain in relevant_domains else ""
            sections.append(f"  {label}: score={score:+.1f}, direction={direction}, alerts={alert_count}{marker}")

        # Detailed scorecards for relevant domains
        for domain in relevant_domains:
            try:
                detail = await get_scorecard(domain)
                if "components" in detail:
                    sections.append(f"\n{domain.upper()} DOMAIN DETAIL:")
                    for comp in detail["components"][:8]:
                        name = comp.get("series_name", comp.get("series_id", ""))
                        latest = comp.get("latest_value", "")
                        mom = comp.get("mom_pct", "")
                        yoy = comp.get("yoy_pct", "")
                        z = comp.get("z_score", "")
                        sections.append(f"    {name}: value={latest}, MoM={mom}%, YoY={yoy}%, z={z}")
            except Exception:
                pass
    except Exception as e:
        sections.append(f"[Scorecard data unavailable: {e}]")

    # 2. Anomalies
    try:
        anomalies = await get_active_anomalies(severity="all")
        alerts = anomalies.get("alerts", [])
        relevant_alerts = [
            a for a in alerts
            if any(kw in (a.get("series_name", "") + a.get("description", "")).lower()
                   for d in relevant_domains for kw in DOMAIN_KEYWORDS.get(d, []))
        ]
        if not relevant_alerts:
            relevant_alerts = alerts[:10]

        sections.append(f"\nACTIVE ANOMALIES ({anomalies.get('total', 0)} total, {len(relevant_alerts)} shown):")
        for a in relevant_alerts[:12]:
            sev = a.get("severity", "watch").upper()
            sections.append(f"  [{sev}] {a.get('series_name', '')}: {a.get('description', '')}")
    except Exception as e:
        sections.append(f"[Anomaly data unavailable: {e}]")

    # 3. Cross-series divergences
    try:
        cross = await get_all_divergences()
        divs = cross.get("active_divergences", [])
        if divs:
            sections.append(f"\nCROSS-SERIES DIVERGENCES ({cross.get('divergence_count', 0)}):")
            for d in divs[:6]:
                sections.append(f"  {d.get('pair_name', '')}: {d.get('description', '')}")
    except Exception as e:
        sections.append(f"[Cross-series data unavailable: {e}]")

    # 4. ML model outputs (if available)
    try:
        from app.services.models.registry import get_registry
        registry = get_registry()

        # Changepoint results
        if registry._models.get("changepoint", None) and registry._models["changepoint"].status == "ready":
            sections.append(f"\nML MODEL INSIGHTS:")
            if registry._models["changepoint"].last_run_at:
                sections.append("  Change-point detection has been run on all series.")

        # Isolation Forest
        if registry._models.get("isolation_forest", None) and registry._models["isolation_forest"].status == "ready":
            if registry._models["isolation_forest"].last_run_at:
                sections.append("  Isolation Forest anomaly scoring available.")

        # Elastic Net drivers
        if registry._models.get("elastic_net", None) and registry._models["elastic_net"].status == "ready":
            if registry._models["elastic_net"].last_run_at:
                sections.append("  Elastic Net driver attribution available.")
    except Exception:
        pass

    return "\n".join(sections)


async def generate_ic_memo(topic: str) -> dict:
    """Generate a standalone IC memo for any topic using signal engine data.

    Args:
        topic: The memo topic (e.g. "Saudi banking liquidity outlook").

    Returns:
        Dict with ``memo`` (markdown text), ``topic``, ``tokens_used``, ``duration_ms``.
    """
    t0 = time.time()
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    signal_context = await _gather_signal_context(topic)
    relevant_domains = _detect_relevant_domains(topic)
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")

    prompt = f"""You are the Chief Investment Officer at a Saudi PE firm writing an Investment Committee memo.

TOPIC: {topic}
DATE: {today}
RELEVANT MACRO DOMAINS: {', '.join(relevant_domains)}

Below is the latest output from the firm's quantitative signal engine — real computed indicators, anomalies, and cross-series analysis from SAMA bulletin data and market sources.

--- SIGNAL ENGINE DATA ---
{signal_context[:4000]}
--- END DATA ---

Write a formal IC memo in the following exact structure (use markdown). Be specific — cite actual numbers, scores, and anomalies from the data above. Do not make up numbers; only use what the data provides. Where data is sparse, acknowledge it.

# Investment Committee Memo

**Date:** {today}
**Topic:** {topic}
**Prepared by:** Quant Signal Engine + CIO Review

## Executive Summary
3-4 sentences. State the core thesis clearly. Reference the aggregate macro score and the most relevant domain scores.

## Investment Thesis
What is the core view? Build the argument from the signal data. Reference specific scorecard scores, trend directions, and z-scores. Structure as 3-4 bullet points.

## Supporting Evidence
List the 4-5 strongest data points that support the thesis. Use exact numbers from the signal engine.

## Key Risks
Top 3-4 risks. For each risk, cite the specific anomaly, divergence, or weak signal that flags it.
- Risk 1: [title] — [data-backed explanation]
- Risk 2: ...

## Scenario Analysis
Construct two scenarios:
### Base Case (60% probability)
What happens if current trends continue. Reference trend directions.

### Downside Scenario (25% probability)
What would trigger a reversal. Reference the anomalies and divergences that could be early warnings.

### Upside Scenario (15% probability)
What would accelerate the positive thesis.

## Recommendation
A clear, actionable recommendation. Include:
- Positioning (overweight / neutral / underweight)
- Key metrics to monitor (which series, what thresholds)
- Suggested review timeline

Keep the memo concise, data-driven, and professional. Use bullet points. No fluff."""

    try:
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            temperature=0.3,
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )

        memo_text = response.choices[0].message.content.strip()
        tokens = response.usage.total_tokens if response.usage else 0
        elapsed = int((time.time() - t0) * 1000)

        logger.info(f"IC Memo generated for '{topic}' in {elapsed}ms, {tokens} tokens")

        return {
            "memo": memo_text,
            "topic": topic,
            "tokens_used": tokens,
            "duration_ms": elapsed,
            "domains_analyzed": relevant_domains,
        }

    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        logger.error(f"IC Memo generation failed for '{topic}': {e}")
        return {
            "error": str(e),
            "topic": topic,
            "duration_ms": elapsed,
        }
