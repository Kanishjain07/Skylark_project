"""The Business Intelligence agent, powered by Groq (OpenAI-compatible API).

Architecture note: the agent does NOT receive hundreds of raw rows. Instead it
calls tools that return Python-computed aggregates (accurate, auditable, and
small enough for Groq's token-per-minute limit). It can also pull a handful of
example rows for drill-down. The model's job is interpretation, not arithmetic.
"""
from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from .analytics import compute_analytics, sample_records
from .config import get_settings
from .data_service import get_deals, get_work_orders
from .monday_client import MondayError

SYSTEM_PROMPT = """\
You are the Skylark Business Intelligence agent. You answer business questions \
for founders and executives using live data from two monday.com boards:
- "Work Orders": project execution / operational data.
- "Deals": sales pipeline data (revenue, stages, sectors).

TOOLS
- deals_summary / work_orders_summary return pre-computed aggregates: totals, \
averages, counts by category, value broken down by category (e.g. value by \
stage, value by sector), date ranges, and a data_quality report. Use these \
for almost every question - the numbers are already correct.
- Each summary includes a "headline_metrics" object with authoritative DERIVED \
figures: total value, win/lost counts and win_rate_pct, and the #1 sector by \
value with a full sector_ranking_by_value. ALWAYS use headline_metrics for win \
rate, "best/top" rankings, and totals. Never compute these yourself or override \
them - if you state a win rate or a best sector, copy it from headline_metrics.
- get_examples returns a few individual rows for drill-down (e.g. "show me some \
energy deals"). Use only when the user wants specific records.
- Call the summary tool(s) before answering a data question. Use the deals \
board for pipeline/revenue/sector questions, work orders for \
operational/delivery questions, and both when a question spans them.

GROUNDING RULES (critical - never break these)
- Use ONLY the sector names, stage names, statuses, categories, and numbers \
that literally appear in the tool results. NEVER invent categories. If a sector \
like "Healthcare" or "Finance" is not in the data, do not mention it. The valid \
sectors/stages are exactly the keys returned in category_counts, \
value_breakdowns, and sector_ranking_by_value.
- NEVER make up numbers. Every figure you state must come from a tool result.
- Do NOT create time-based distributions ("this quarter", "next quarter") \
unless a tool explicitly provides those buckets. Most close dates are missing, \
so such buckets are NOT computable - instead report how many deals actually \
have a close date (from data_quality) and note the rest are unknown.
- If you are unsure whether something is in the data, say the data does not \
include it rather than guessing.

HOW YOU ANSWER
- Give insight, not just numbers. Explain what a figure means, call out risks, \
trends, and concentrations (e.g. pipeline stuck in one stage, revenue \
concentrated in one sector). Interpret, don't just report.
- Be concise and skimmable. Lead with a one-line headline answer in bold, then \
supporting detail.
- Format for readability: when presenting several figures (value by stage, by \
sector, a KPI set), use a compact markdown table with a header row and bold the \
single most important number. Use short bullets for insights. Keep tables to \
the few columns that matter - don't dump every field.
- Format money consistently (e.g. $2.31B, $812.9M, $985K), not raw long digit \
strings, unless the user asks for exact figures.
- The data is messy. When missing/incomplete data affects an answer, say so \
plainly using the data_quality figures, e.g. "Note: 320 of 346 deals have no \
close date, so any time-based view is limited."
- DEFAULT TO ANSWERING. Prefer to make a reasonable assumption, state it in one \
short line, and give the answer. Only ask a clarifying question when you truly \
cannot proceed (e.g. two equally likely, very different interpretations).
- Map a user's informal term to the closest ACTUAL sector(s) in the data and \
answer directly - do not stop to ask. For example "energy" maps to Renewables \
(and Powerline, which is power/energy infrastructure); say "I've read 'energy' \
as Renewables + Powerline" then give the pipeline. This is interpretation, not \
fabrication - you are still using real sectors from the data.
- Show the key numbers behind a total or rate so the answer is auditable. \
Never mention internal ids; use human-readable labels.
- Never mention tool names, function names, JSON fields, or internal terms like \
"headline_metrics", "deals_summary", or "data_quality report" to the user. \
Speak in plain business language as if you already knew the data.
"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "deals_summary",
            "description": (
                "Pre-computed aggregates for the monday.com Deals board (sales "
                "pipeline): totals, counts by stage/sector/status, deal value "
                "broken down by category, date ranges, and data quality."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "work_orders_summary",
            "description": (
                "Pre-computed aggregates for the monday.com Work Orders board "
                "(project execution): counts by status, value/metric summaries, "
                "date ranges, and data quality."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_examples",
            "description": (
                "Return a few individual rows for drill-down. Use when the user "
                "wants specific/example records rather than aggregates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {
                        "type": "string",
                        "enum": ["deals", "work_orders"],
                        "description": "Which board to sample from.",
                    },
                    "filter_field": {
                        "type": "string",
                        "description": (
                            "Optional column to filter on (e.g. 'Sector/service')."
                        ),
                    },
                    "filter_value": {
                        "type": "string",
                        "description": (
                            "Optional case-insensitive substring the field must "
                            "contain (e.g. 'energy')."
                        ),
                    },
                    "limit": {
                        "type": "string",
                        "description": "Max rows to return as a number, e.g. '15' (default 15).",
                    },
                },
                "required": ["board"],
            },
        },
    },
]

_MAX_TOOL_ROUNDS = 6


class AgentResult(dict):
    """{reply, tools_used, data_quality, error}"""


def _history_to_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history:
        role = "assistant" if msg.get("role") == "assistant" else "user"
        content = msg.get("content", "")
        if content:
            messages.append({"role": role, "content": content})
    return messages


async def _execute_tool(
    name: str, args: dict, data_quality: dict[str, Any]
) -> dict[str, Any]:
    """Run a tool call and return a JSON-serializable result."""
    if name == "deals_summary":
        board = await get_deals()
        data_quality["deals"] = {
            "board_name": board.get("board_name"),
            **board.get("data_quality", {}),
        }
        return compute_analytics(board)

    if name == "work_orders_summary":
        board = await get_work_orders()
        data_quality["work_orders"] = {
            "board_name": board.get("board_name"),
            **board.get("data_quality", {}),
        }
        return compute_analytics(board)

    if name == "get_examples":
        which = args.get("board", "deals")
        board = await (get_deals() if which == "deals" else get_work_orders())
        contains = None
        if args.get("filter_field") and args.get("filter_value"):
            contains = {args["filter_field"]: args["filter_value"]}
        try:
            limit = int(args.get("limit") or 15)
        except (ValueError, TypeError):
            limit = 15
        return sample_records(board, limit=min(max(limit, 1), 30), contains=contains)

    return {"error": f"unknown tool {name}"}


async def run_agent(history: list[dict[str, str]]) -> AgentResult:
    settings = get_settings()

    if not settings.groq_configured:
        return AgentResult(
            reply="The agent is not configured yet: GROQ_API_KEY is missing on "
            "the server.",
            tools_used=[],
            data_quality={},
            error="missing_groq_key",
        )
    if not settings.monday_configured:
        return AgentResult(
            reply="The agent is not configured yet: monday.com credentials "
            "(token / board IDs) are missing on the server.",
            tools_used=[],
            data_quality={},
            error="missing_monday_config",
        )

    client = AsyncOpenAI(
        api_key=settings.groq_api_key, base_url=settings.groq_base_url
    )
    messages = _history_to_messages(history)
    tools_used: list[str] = []
    data_quality: dict[str, Any] = {}

    try:
        for _ in range(_MAX_TOOL_ROUNDS):
            response = await client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                tools=_TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                return AgentResult(
                    reply=(msg.content or "").strip()
                    or "I couldn't produce an answer for that.",
                    tools_used=tools_used,
                    data_quality=data_quality,
                    error=None,
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments or "{}",
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await _execute_tool(name, args, data_quality)
                tools_used.append(name)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": json.dumps(result, default=str),
                    }
                )

        return AgentResult(
            reply="I gathered the data but ran out of reasoning steps before "
            "finishing. Try a more specific question.",
            tools_used=tools_used,
            data_quality=data_quality,
            error="max_rounds",
        )

    except MondayError as exc:
        return AgentResult(
            reply=f"I couldn't reach monday.com: {exc}",
            tools_used=tools_used,
            data_quality=data_quality,
            error="monday_error",
        )
    except Exception as exc:  # noqa: BLE001 - surface any model/SDK error cleanly
        return AgentResult(
            reply=f"Something went wrong while answering: {exc}",
            tools_used=tools_used,
            data_quality=data_quality,
            error="agent_error",
        )
