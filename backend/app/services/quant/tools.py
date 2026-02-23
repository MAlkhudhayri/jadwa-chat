"""Tool Registry — every quant function the orchestrator (or agent) can call.

Each tool has:
  - name: unique identifier
  - description: what it does (becomes OpenAI tool description in v1.1)
  - function: the async callable
  - parameters: JSON Schema for arguments (becomes OpenAI tool schema in v1.1)

Used by _handle_signal() for keyword-based sub-routing in v1.0.
In v1.1 this becomes the OpenAI function-calling schema with zero changes.
"""

import logging

from app.services import analytics
from app.services.quant.trend import get_series_signal, get_latest_signal
from app.services.quant.anomaly import get_active_anomalies, get_series_anomalies
from app.services.quant.cross_series import get_pair_analysis, get_all_divergences
from app.services.quant.scorecard import get_scorecard, get_all_scorecards, get_aggregate_score
from app.services.series_discovery import get_discovery_service

logger = logging.getLogger(__name__)


# ── Discovery helpers ────────────────────────────────────────────────────────

async def list_available_series() -> dict:
    """List all available time series with their IDs, names, domains, and units.

    Call this first when unsure which series_id to use.

    Returns:
        Dict with list of all series.
    """
    discovery = get_discovery_service()
    series = await discovery.get_all_series()
    return {"series": series, "total": len(series)}


async def discover_series(query: str, top_k: int = 5) -> dict:
    """Find the best matching series for a natural language query.

    Args:
        query: Natural language description of the data needed.
        top_k: Number of results (default 5).

    Returns:
        Dict with top matches and relevance scores.
    """
    discovery = get_discovery_service()
    matches = await discovery.search(query, top_k=top_k)
    return {"matches": matches, "total": len(matches)}


# ── Tool Registry ────────────────────────────────────────────────────────────

TOOL_REGISTRY = [
    # ── Data tools (existing analytics.py) ──
    {
        "name": "latest",
        "description": (
            "Get the most recent observation value for a time series. "
            "Use when the user asks for a current number."
        ),
        "function": analytics.latest,
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "string",
                    "description": "The series identifier, e.g. 'oil_markets__brent_price_usd_bbl'",
                },
            },
            "required": ["series_id"],
        },
    },
    {
        "name": "change",
        "description": (
            "Calculate period-over-period change (MoM, QoQ, YoY) for a series. "
            "Use when the user asks about growth, decline, or change."
        ),
        "function": analytics.change,
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string"},
                "method": {
                    "type": "string",
                    "enum": ["MoM", "QoQ", "YoY"],
                    "description": "Period: MoM (month-over-month), QoQ (quarter), YoY (year)",
                },
            },
            "required": ["series_id"],
        },
    },
    {
        "name": "rolling",
        "description": (
            "Calculate rolling statistics (mean, std, min, max) over a window. "
            "Use for trend analysis or volatility."
        ),
        "function": analytics.rolling,
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string"},
                "window": {
                    "type": "integer",
                    "description": "Rolling window in months (default 12)",
                },
                "method": {
                    "type": "string",
                    "enum": ["mean", "std", "min", "max"],
                },
            },
            "required": ["series_id"],
        },
    },
    {
        "name": "compare",
        "description": (
            "Compare two series: Pearson correlation, trend direction, latest values. "
            "Use when the user asks about relationships between indicators."
        ),
        "function": analytics.compare,
        "parameters": {
            "type": "object",
            "properties": {
                "series_a": {"type": "string", "description": "First series ID"},
                "series_b": {"type": "string", "description": "Second series ID"},
                "window": {
                    "type": "integer",
                    "description": "Overlapping periods to use (default 24)",
                },
            },
            "required": ["series_a", "series_b"],
        },
    },
    {
        "name": "top_movers",
        "description": (
            "Find the series with the biggest changes in a domain or across all domains. "
            "Use for market scanning."
        ),
        "function": analytics.top_movers,
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Optional domain filter"},
                "period": {"type": "string", "enum": ["MoM", "QoQ", "YoY"]},
                "limit": {"type": "integer", "description": "Number of results (default 5)"},
            },
        },
    },
    {
        "name": "get_series",
        "description": (
            "Get raw time series observations for a date range. "
            "Use when the user asks for historical data."
        ),
        "function": analytics.get_series,
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string"},
                "start": {"type": "string", "description": "Start date YYYY-MM-DD"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["series_id"],
        },
    },

    # ── Signal tools (new quant engine) ──
    {
        "name": "get_scorecard",
        "description": (
            "Get the macro signal scorecard for a domain (oil, monetary, banking, bop, inflation) "
            "or 'all' for the full dashboard. Returns score (-100 to +100), direction, component "
            "signals, and any anomaly alerts. Use for macro overview questions."
        ),
        "function": get_scorecard,
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["oil", "monetary", "banking", "bop", "inflation", "all"],
                    "description": "Domain to score, or 'all' for aggregate",
                },
            },
            "required": ["domain"],
        },
    },
    {
        "name": "get_anomalies",
        "description": (
            "Get active anomaly alerts across all series. Returns unusual movements that need "
            "analyst attention: Bollinger band breaks, trend breaks, streaks, and level shifts. "
            "Sorted by severity (critical > warning > watch)."
        ),
        "function": get_active_anomalies,
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["all", "critical", "warning", "watch"],
                    "description": "Filter by severity level (default: all)",
                },
            },
        },
    },
    {
        "name": "get_series_signal",
        "description": (
            "Get the full signal analysis for a specific series: current value, MoM/QoQ/YoY "
            "change, z-score, percentile, signal classification, and any active anomalies. "
            "Use when the user asks about a specific indicator's trend or status."
        ),
        "function": get_series_signal,
        "parameters": {
            "type": "object",
            "properties": {
                "series_id": {"type": "string"},
            },
            "required": ["series_id"],
        },
    },
    {
        "name": "get_cross_series",
        "description": (
            "Get cross-series correlation analysis and divergence alerts. Shows which "
            "historically correlated pairs are diverging, with investment interpretation. "
            "Use when the user asks about relationships between macro indicators."
        ),
        "function": get_all_divergences,
        "parameters": {
            "type": "object",
            "properties": {
                "pair_name": {
                    "type": "string",
                    "description": "Optional: specific pair (e.g. 'brent_vs_reserves'). Omit for all pairs.",
                },
            },
        },
    },

    # ── Discovery tools ──
    {
        "name": "list_available_series",
        "description": (
            "List all available time series with their IDs, names, domains, and units. "
            "Call this first when unsure which series_id to use."
        ),
        "function": list_available_series,
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "discover_series",
        "description": (
            "Find the best matching series for a natural language query. "
            "Returns top matches with relevance scores."
        ),
        "function": discover_series,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language description of the data needed",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results (default 5)",
                },
            },
            "required": ["query"],
        },
    },
]


def get_tool_by_name(name: str) -> dict | None:
    """Lookup a tool by name."""
    for tool in TOOL_REGISTRY:
        if tool["name"] == name:
            return tool
    return None


def get_openai_tools_schema() -> list:
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
            },
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
        logger.error(f"Tool '{name}' failed: {e}")
        return {"error": f"Tool '{name}' failed: {str(e)}"}



