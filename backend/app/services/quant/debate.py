"""Agent Debate — multi-round investment debate with user participation.

Enhanced features:
  - Topic-focused debates (user sets the question)
  - Scenario injection ("What if oil drops 20%?")
  - Investment Committee Memo generation after conclusion
  - Conviction history tracking across rounds
  - Sequential agent responses for streaming UX

Session lifecycle:
  1. POST /debate         → starts session (with optional topic), runs opening round
  2. POST /debate/{id}/user → user injects a message
  3. POST /debate/{id}/round → agents respond (to each other + user)
  4. POST /debate/{id}/scenario → inject a scenario, agents react
  5. POST /debate/{id}/memo → generate IC memo after conclusion
  6. Repeat 2-4 until consensus or max rounds
"""

import asyncio
import json
import logging
import uuid
import time
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings
from app.services.quant.tools import execute_tool

logger = logging.getLogger(__name__)

MAX_ROUNDS = 8
CONSENSUS_THRESHOLD = 0.70

# ── Agent Personas ───────────────────────────────────────────────────────────

_STANCE_INSTRUCTION = (
    "\n\nIMPORTANT: End EVERY message with your stance on a new line in exactly "
    "this format: [BULLISH], [BEARISH], or [NEUTRAL]. This is mandatory."
)

AGENTS = [
    {
        "id": "sniper",
        "name": "The Sniper",
        "title": "High-Conviction Strategist",
        "emoji": "🎯",
        "color": "#1B365D",
        "system_prompt": (
            "You are The Sniper — a high-conviction, low-frequency investor. "
            "You only speak when something is truly significant. You look for "
            "major regime shifts, structural breaks, and once-in-a-cycle setups. "
            "If nothing stands out, say so bluntly. When you do see something, "
            "be precise and decisive. No filler, no hedging. "
            "You are in a live debate with other investment professionals and "
            "sometimes a human analyst. React to what others say — agree, disagree, "
            "challenge. Keep it to 2-3 sentences."
        ) + _STANCE_INSTRUCTION,
    },
    {
        "id": "scalper",
        "name": "The Scalper",
        "title": "Momentum Trader",
        "emoji": "⚡",
        "color": "#F59E0B",
        "system_prompt": (
            "You are The Scalper — you live for momentum and short-term signals. "
            "You focus on MoM% changes, recent trend breaks, and anything moving "
            "fast RIGHT NOW. You think in weeks, not years. "
            "You are in a live debate with other investment professionals and "
            "sometimes a human analyst. React to their points — especially challenge "
            "the long-term thinkers. Be energetic. 2-3 sentences."
        ) + _STANCE_INSTRUCTION,
    },
    {
        "id": "guardian",
        "name": "The Guardian",
        "title": "Risk Manager",
        "emoji": "🛡️",
        "color": "#DC2626",
        "system_prompt": (
            "You are The Guardian — capital preservation is everything. "
            "You scan for risks, anomalies, deteriorating trends, and warning signs. "
            "You're the one who says 'wait' when everyone else says 'go'. "
            "You are in a live debate. Push back on bullish takes. Acknowledge "
            "when risks are contained. Be cautious but fair. 2-3 sentences."
        ) + _STANCE_INSTRUCTION,
    },
    {
        "id": "strategist",
        "name": "The Strategist",
        "title": "Macro Analyst",
        "emoji": "🧭",
        "color": "#059669",
        "system_prompt": (
            "You are The Strategist — you see the big picture. "
            "You connect dots across domains: how oil affects reserves, how "
            "monetary policy flows into banking, how the current account shapes "
            "the fiscal outlook. You think in quarters and years. "
            "You are in a live debate. Synthesize what others are saying into "
            "a coherent thesis. Mediate disagreements with data. 2-3 sentences."
        ) + _STANCE_INSTRUCTION,
    },
    {
        "id": "contrarian",
        "name": "The Contrarian",
        "title": "Devil's Advocate",
        "emoji": "🔄",
        "color": "#7C3AED",
        "system_prompt": (
            "You are The Contrarian — you challenge the consensus. "
            "When others agree, you push back. When they disagree, you find "
            "the overlooked angle. You are NOT contrarian for its own sake — "
            "you genuinely look for what others are missing. "
            "You are in a live debate. React to the emerging consensus and "
            "poke holes in it. Be provocative but substantive. 2-3 sentences."
        ) + _STANCE_INSTRUCTION,
    },
    {
        "id": "quant",
        "name": "The Quant",
        "title": "Data Scientist",
        "emoji": "📐",
        "color": "#0284C7",
        "system_prompt": (
            "You are The Quant — pure data, no narrative. "
            "You speak in numbers: z-scores, percentiles, correlations. "
            "You flag statistical outliers and let the numbers speak. "
            "You are in a live debate. When others make claims, demand data. "
            "When you change your stance, explain which numbers moved you. "
            "2-3 sentences."
        ) + _STANCE_INSTRUCTION,
    },
]

AGENT_MAP = {a["id"]: a for a in AGENTS}

# ── Scenario Presets ─────────────────────────────────────────────────────────

SCENARIO_PRESETS = [
    {
        "id": "oil_crash",
        "label": "Oil drops to $50",
        "context_override": (
            "\n\n⚠️ SCENARIO INJECTION: Assume Brent crude oil has just dropped to "
            "$50/barrel — a 35% decline. All oil-related revenue, reserves, and fiscal "
            "projections should be reassessed under this scenario. React to how this "
            "changes your thesis."
        ),
    },
    {
        "id": "rate_cut",
        "label": "SAMA cuts rates 100bp",
        "context_override": (
            "\n\n⚠️ SCENARIO INJECTION: SAMA has just announced a surprise 100 basis point "
            "rate cut. Repo rate is now significantly lower. Reassess monetary conditions, "
            "banking sector impact, and any knock-on effects."
        ),
    },
    {
        "id": "inflation_spike",
        "label": "Inflation spikes to 5%",
        "context_override": (
            "\n\n⚠️ SCENARIO INJECTION: Saudi CPI has just printed at 5.0% YoY — far above "
            "the recent trend. This is a structural break. Reassess your stance given "
            "inflation risk to consumers, policy response, and real returns."
        ),
    },
    {
        "id": "global_recession",
        "label": "Global recession signal",
        "context_override": (
            "\n\n⚠️ SCENARIO INJECTION: US yield curve has deeply inverted, PMIs across "
            "Europe and China are in contraction, and global risk-off sentiment is surging. "
            "Reassess Saudi macro exposure to a potential global recession."
        ),
    },
]

SCENARIO_MAP = {s["id"]: s for s in SCENARIO_PRESETS}

# ── In-memory Session Store ──────────────────────────────────────────────────

_sessions: dict[str, dict] = {}


def _get_session(session_id: str) -> dict:
    if session_id not in _sessions:
        raise ValueError(f"Debate session '{session_id}' not found")
    return _sessions[session_id]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_stance(message: str) -> str:
    msg_upper = message.upper()
    if "[BULLISH]" in msg_upper:
        return "BULLISH"
    if "[BEARISH]" in msg_upper:
        return "BEARISH"
    if "[NEUTRAL]" in msg_upper:
        return "NEUTRAL"
    return "NEUTRAL"


def _clean_message(message: str) -> str:
    import re
    return re.sub(r'\s*\[(BULLISH|BEARISH|NEUTRAL)\]\s*$', '', message, flags=re.IGNORECASE).strip()


def _compute_consensus(stances: dict[str, str]) -> dict:
    if not stances:
        return {"reached": False, "majority_stance": None, "percentage": 0, "breakdown": {}}

    counts = {}
    for stance in stances.values():
        counts[stance] = counts.get(stance, 0) + 1

    total = len(stances)
    majority_stance = max(counts, key=counts.get)
    majority_count = counts[majority_stance]
    percentage = majority_count / total

    return {
        "reached": percentage >= CONSENSUS_THRESHOLD,
        "majority_stance": majority_stance,
        "percentage": round(percentage * 100, 1),
        "breakdown": counts,
    }


# ── Context Builder ──────────────────────────────────────────────────────────

async def _build_debate_context() -> str:
    dashboard_task = execute_tool("get_scorecard", {"domain": "all"})
    anomalies_task = execute_tool("get_anomalies", {"severity": "all"})
    cross_task = execute_tool("get_cross_series", {})

    dashboard, anomalies, cross = await asyncio.gather(
        dashboard_task, anomalies_task, cross_task
    )

    lines = [
        "MARKET SIGNAL DATA (as of today)",
        "═══════════════════════════════════",
        "",
        f"AGGREGATE SCORE: {dashboard.get('aggregate_score', 0):+.1f} "
        f"({dashboard.get('aggregate_direction', 'stable')})",
        "",
        "DOMAIN SCORECARDS:",
    ]

    for card in dashboard.get("scorecards", []):
        score = card.get("score", 0)
        direction = card.get("direction", "stable")
        alert_count = card.get("alert_count", 0)
        lines.append(
            f"  {card.get('label', card.get('domain', '?'))}: {score:+.1f} ({direction})"
            f"{f', {alert_count} alerts' if alert_count else ''}"
        )
        for sid, comp in card.get("components", {}).items():
            if not comp.get("available"):
                continue
            name = comp.get("name", sid)
            signal = comp.get("signal", "N/A")
            mom = comp.get("mom_pct")
            yoy = comp.get("yoy_pct")
            z = comp.get("z_score")
            value = comp.get("value")
            unit = comp.get("unit", "")
            metrics = []
            if mom is not None:
                metrics.append(f"MoM:{mom:+.1f}%")
            if yoy is not None:
                metrics.append(f"YoY:{yoy:+.1f}%")
            if z is not None:
                metrics.append(f"z:{z:+.1f}")
            lines.append(f"    {name}: {signal} ({value} {unit}) [{' '.join(metrics)}]")

    alert_list = anomalies.get("alerts", [])
    lines.append("")
    lines.append(f"ACTIVE ANOMALIES ({len(alert_list)}):")
    for a in alert_list:
        lines.append(f"  [{a.get('severity', '?').upper()}] {a.get('series_name', '?')}: "
                      f"{a.get('alert_type', '?')} — {a.get('description', '')}")
    if not alert_list:
        lines.append("  None.")

    divs = cross.get("active_divergences", [])
    lines.append("")
    lines.append(f"CROSS-SERIES DIVERGENCES ({len(divs)}):")
    for d in divs:
        lines.append(f"  {d['pair_name']}: r {d.get('long_run_correlation', '?')} → "
                      f"{d.get('recent_correlation', '?')} (Δ{d.get('divergence', '?')})")
    if not divs:
        lines.append("  None.")

    return "\n".join(lines)


# ── Agent Caller ─────────────────────────────────────────────────────────────

async def _call_agent_round(
    client: AsyncOpenAI,
    agent: dict,
    market_context: str,
    conversation: list[dict],
    model: str,
    topic: Optional[str] = None,
) -> dict:
    """Call one agent with market context + full conversation history."""
    system_content = agent["system_prompt"]
    if topic:
        system_content += f"\n\nDEBATE TOPIC: {topic}\nFocus your analysis and stance on this specific question."

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": f"MARKET DATA:\n{market_context}"},
    ]

    for msg in conversation:
        speaker = msg.get("name", "Unknown")
        content = msg.get("message", "")
        stance = msg.get("stance", "")
        stance_tag = f" [{stance}]" if stance else ""

        if msg.get("role") == "user":
            messages.append({
                "role": "user",
                "content": f"[HUMAN ANALYST]: {content}",
            })
        elif msg.get("role") == "scenario":
            messages.append({
                "role": "user",
                "content": f"[SCENARIO ALERT]: {content}",
            })
        else:
            messages.append({
                "role": "user",
                "content": f"[{speaker}]: {content}{stance_tag}",
            })

    prompt_suffix = ""
    if topic:
        prompt_suffix = f" Focus on the topic: {topic}"

    messages.append({
        "role": "user",
        "content": f"Your turn. Respond to the discussion.{prompt_suffix} Keep it to 2-3 sentences. End with your stance [BULLISH], [BEARISH], or [NEUTRAL].",
    })

    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.8,
            max_tokens=200,
            messages=messages,
        )
        raw = response.choices[0].message.content.strip()
        stance = _extract_stance(raw)
        clean = _clean_message(raw)

        return {
            "agent_id": agent["id"],
            "name": agent["name"],
            "title": agent["title"],
            "emoji": agent["emoji"],
            "color": agent["color"],
            "message": clean,
            "stance": stance,
            "role": "agent",
            "tokens_used": response.usage.total_tokens if response.usage else 0,
        }
    except Exception as e:
        logger.error(f"Agent {agent['id']} failed in round: {e}")
        return {
            "agent_id": agent["id"],
            "name": agent["name"],
            "title": agent["title"],
            "emoji": agent["emoji"],
            "color": agent["color"],
            "message": "I'll pass on this round.",
            "stance": "NEUTRAL",
            "role": "agent",
            "error": str(e),
        }


# ── Sequential agent runner (for streaming UX) ──────────────────────────────

async def _run_agents_sequential(
    client: AsyncOpenAI,
    agents: list[dict],
    market_context: str,
    conversation: list[dict],
    model: str,
    topic: Optional[str] = None,
) -> list[dict]:
    """Run agents sequentially so frontend can display them one by one.

    Each agent sees all prior agents' responses from this round too,
    making the conversation more natural and reactive.
    """
    round_results = []
    round_conversation = list(conversation)

    for agent in agents:
        result = await _call_agent_round(
            client, agent, market_context, round_conversation, model, topic
        )
        round_results.append(result)
        round_conversation.append(result)

    return round_results


# ── Public API ───────────────────────────────────────────────────────────────

async def start_debate(topic: Optional[str] = None) -> dict:
    """Start a new debate session and run the opening round.

    Args:
        topic: Optional debate question/topic to focus the discussion.

    Returns:
        Full session state including first round responses.
    """
    session_id = str(uuid.uuid4())[:8]
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    model = settings.LLM_MODEL

    market_context = await _build_debate_context()

    results = await _run_agents_sequential(
        client, AGENTS, market_context, [], model, topic
    )

    stances = {r["agent_id"]: r["stance"] for r in results}
    consensus = _compute_consensus(stances)

    conviction_history = [{
        "round": 1,
        "stances": dict(stances),
    }]

    session = {
        "session_id": session_id,
        "topic": topic,
        "market_context": market_context,
        "conversation": list(results),
        "stances": stances,
        "consensus": consensus,
        "conviction_history": conviction_history,
        "round": 1,
        "status": "consensus_reached" if consensus["reached"] else "active",
        "created_at": time.time(),
        "total_tokens": sum(r.get("tokens_used", 0) for r in results),
        "scenarios_applied": [],
    }

    _sessions[session_id] = session
    return _session_response(session, results)


async def add_user_message(session_id: str, message: str) -> dict:
    """User injects a message into the debate, then agents respond."""
    session = _get_session(session_id)

    if session["status"] != "active":
        return _session_response(session, [], note="Debate has already concluded.")

    if session["round"] >= MAX_ROUNDS:
        session["status"] = "max_rounds"
        return _session_response(session, [], note="Maximum rounds reached.")

    user_msg = {
        "agent_id": "user",
        "name": "You",
        "title": "Analyst",
        "emoji": "👤",
        "color": "#374151",
        "message": message,
        "stance": "",
        "role": "user",
    }
    session["conversation"].append(user_msg)

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    model = settings.LLM_MODEL

    results = await _run_agents_sequential(
        client, AGENTS, session["market_context"],
        session["conversation"], model, session.get("topic"),
    )

    session["conversation"].extend(results)
    session["round"] += 1
    session["total_tokens"] += sum(r.get("tokens_used", 0) for r in results)

    for r in results:
        session["stances"][r["agent_id"]] = r["stance"]

    session["consensus"] = _compute_consensus(session["stances"])

    session["conviction_history"].append({
        "round": session["round"],
        "stances": dict(session["stances"]),
    })

    if session["consensus"]["reached"]:
        session["status"] = "consensus_reached"
    elif session["round"] >= MAX_ROUNDS:
        session["status"] = "max_rounds"

    return _session_response(session, results, user_message=user_msg)


async def run_next_round(session_id: str) -> dict:
    """Run the next round — agents respond to the conversation so far."""
    session = _get_session(session_id)

    if session["status"] != "active":
        return _session_response(session, [], note="Debate has already concluded.")

    if session["round"] >= MAX_ROUNDS:
        session["status"] = "max_rounds"
        return _session_response(session, [], note="Maximum rounds reached.")

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    model = settings.LLM_MODEL

    results = await _run_agents_sequential(
        client, AGENTS, session["market_context"],
        session["conversation"], model, session.get("topic"),
    )

    session["conversation"].extend(results)
    session["round"] += 1
    session["total_tokens"] += sum(r.get("tokens_used", 0) for r in results)

    for r in results:
        session["stances"][r["agent_id"]] = r["stance"]

    session["consensus"] = _compute_consensus(session["stances"])

    session["conviction_history"].append({
        "round": session["round"],
        "stances": dict(session["stances"]),
    })

    if session["consensus"]["reached"]:
        session["status"] = "consensus_reached"
    elif session["round"] >= MAX_ROUNDS:
        session["status"] = "max_rounds"

    return _session_response(session, results)


async def inject_scenario(session_id: str, scenario_id: str) -> dict:
    """Inject a what-if scenario into the debate. Agents react in a new round."""
    session = _get_session(session_id)

    if session["status"] != "active":
        return _session_response(session, [], note="Debate has already concluded.")

    scenario = SCENARIO_MAP.get(scenario_id)
    if not scenario:
        raise ValueError(f"Unknown scenario: {scenario_id}. Available: {list(SCENARIO_MAP.keys())}")

    session["market_context"] += scenario["context_override"]
    session["scenarios_applied"].append(scenario_id)

    scenario_msg = {
        "agent_id": "system",
        "name": "Scenario",
        "title": scenario["label"],
        "emoji": "⚡",
        "color": "#D97706",
        "message": scenario["context_override"].strip().replace("⚠️ SCENARIO INJECTION: ", ""),
        "stance": "",
        "role": "scenario",
    }
    session["conversation"].append(scenario_msg)

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    model = settings.LLM_MODEL

    results = await _run_agents_sequential(
        client, AGENTS, session["market_context"],
        session["conversation"], model, session.get("topic"),
    )

    session["conversation"].extend(results)
    session["round"] += 1
    session["total_tokens"] += sum(r.get("tokens_used", 0) for r in results)

    for r in results:
        session["stances"][r["agent_id"]] = r["stance"]

    session["consensus"] = _compute_consensus(session["stances"])
    session["conviction_history"].append({
        "round": session["round"],
        "stances": dict(session["stances"]),
    })

    if session["consensus"]["reached"]:
        session["status"] = "consensus_reached"
    elif session["round"] >= MAX_ROUNDS:
        session["status"] = "max_rounds"

    return _session_response(session, results, scenario_message=scenario_msg)


async def generate_memo(session_id: str) -> dict:
    """Generate an Investment Committee memo summarizing the debate.

    Returns a structured memo with thesis, arguments, dissent, and recommendation.
    """
    session = _get_session(session_id)

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    topic_line = f"Debate Topic: {session['topic']}\n" if session.get("topic") else ""
    scenarios_line = ""
    if session.get("scenarios_applied"):
        labels = [SCENARIO_MAP[s]["label"] for s in session["scenarios_applied"] if s in SCENARIO_MAP]
        scenarios_line = f"Scenarios Tested: {', '.join(labels)}\n"

    transcript = ""
    for msg in session["conversation"]:
        role_tag = msg.get("role", "agent")
        name = msg.get("name", "Unknown")
        stance = f" [{msg['stance']}]" if msg.get("stance") else ""
        if role_tag == "scenario":
            transcript += f"\n[SCENARIO] {msg['message']}\n"
        else:
            transcript += f"{name}{stance}: {msg['message']}\n"

    consensus = session["consensus"]
    history_text = ""
    for entry in session.get("conviction_history", []):
        round_num = entry["round"]
        round_stances = entry["stances"]
        stance_summary = ", ".join(f"{AGENT_MAP.get(aid, {}).get('name', aid)}: {s}" for aid, s in round_stances.items())
        history_text += f"  Round {round_num}: {stance_summary}\n"

    prompt = f"""You are the Chief Investment Officer writing an Investment Committee memo.

Based on the following multi-agent debate among 6 investment professionals, produce a formal IC memo.

{topic_line}{scenarios_line}
Final Outcome: {consensus['percentage']}% {consensus['majority_stance'] or 'No consensus'}
Rounds: {session['round']}

Conviction Evolution:
{history_text}

Full Debate Transcript:
{transcript}

Market Data Summary:
{session['market_context'][:2000]}

Write the memo in this exact structure (use markdown):

# Investment Committee Memo

**Date:** Today
**Topic:** {session.get('topic', 'Saudi Macro Outlook')}
**Outcome:** {consensus['percentage']}% {consensus['majority_stance'] or 'Split'} after {session['round']} rounds

## Executive Summary
2-3 sentences capturing the key conclusion.

## Bull Case
The strongest arguments for a positive outlook. Cite specific data points.

## Bear Case
The strongest arguments for caution. Cite specific data points.

## Key Risks
Top 3 risks identified during the debate.

## Dissenting Views
Which agents disagreed and why. This is important for the record.

## Recommendation
A clear, actionable recommendation based on the debate outcome.

Keep the memo concise and professional. Use bullet points where appropriate."""

    try:
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            temperature=0.3,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )

        memo_text = response.choices[0].message.content.strip()
        tokens = response.usage.total_tokens if response.usage else 0
        session["total_tokens"] += tokens

        return {
            "session_id": session_id,
            "memo": memo_text,
            "tokens_used": tokens,
            "consensus": consensus,
        }
    except Exception as e:
        logger.error(f"Memo generation failed: {e}")
        return {"session_id": session_id, "error": str(e)}


def get_session_state(session_id: str) -> dict:
    session = _get_session(session_id)
    return _session_response(session, [])


def _session_response(session: dict, new_messages: list,
                      user_message: dict = None, scenario_message: dict = None,
                      note: str = None) -> dict:
    pre_messages = []
    if scenario_message:
        pre_messages.append(scenario_message)
    if user_message:
        pre_messages.append(user_message)

    resp = {
        "session_id": session["session_id"],
        "topic": session.get("topic"),
        "round": session["round"],
        "status": session["status"],
        "consensus": session["consensus"],
        "stances": session["stances"],
        "conversation": session["conversation"],
        "conviction_history": session.get("conviction_history", []),
        "new_messages": pre_messages + new_messages,
        "total_tokens": session.get("total_tokens", 0),
        "max_rounds": MAX_ROUNDS,
        "scenarios_applied": session.get("scenarios_applied", []),
        "available_scenarios": [
            {"id": s["id"], "label": s["label"]}
            for s in SCENARIO_PRESETS
            if s["id"] not in session.get("scenarios_applied", [])
        ],
    }
    if note:
        resp["note"] = note
    return resp


def get_available_agents() -> list:
    return [
        {
            "id": a["id"],
            "name": a["name"],
            "title": a["title"],
            "emoji": a["emoji"],
            "color": a["color"],
        }
        for a in AGENTS
    ]
