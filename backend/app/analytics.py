"""Deterministic analytics computed in Python (not by the LLM).

We pre-aggregate the cleaned board data into compact summaries. This keeps the
number-crunching accurate and auditable, and keeps the payload sent to the LLM
small (well under Groq's tokens-per-minute limit). The LLM's job is to
interpret these summaries into insight, not to sum hundreds of rows itself.
"""
from __future__ import annotations

from typing import Any

_TOP_N = 15  # cap categories per breakdown to stay compact
_MAX_CARDINALITY = 40  # skip id-like / high-cardinality columns in breakdowns


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _distinct_count(records: list[dict], col: str) -> int:
    return len({str(r[col]) for r in records if r.get(col) is not None})


def _is_id_like(col: str) -> bool:
    """Columns that identify a row (owner/client/code/id) aren't useful BI
    dimensions and blow up the payload, so we exclude them from breakdowns."""
    c = col.lower()
    return any(k in c for k in ("code", " id", "id ", "owner", "client", "name"))


def _bi_dimensions(records: list[dict], kinds: dict[str, str], columns: list[str]):
    """Label columns worth grouping/counting by: low cardinality, not id-like."""
    dims = []
    for c in columns:
        if kinds.get(c) != "label" or _is_id_like(c):
            continue
        if _distinct_count(records, c) <= _MAX_CARDINALITY:
            dims.append(c)
    return dims


def _numeric_summary(records: list[dict], col: str) -> dict[str, Any]:
    vals = [r[col] for r in records if _is_number(r.get(col))]
    if not vals:
        return {"count": 0}
    total = sum(vals)
    return {
        "count": len(vals),
        "sum": round(total, 2),
        "avg": round(total / len(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
    }


def _value_counts(records: list[dict], col: str) -> dict[str, Any]:
    counts: dict[str, int] = {}
    missing = 0
    for r in records:
        v = r.get(col)
        if v is None:
            missing += 1
            continue
        key = str(v)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top = dict(ordered[:_TOP_N])
    result: dict[str, Any] = {"distinct": len(counts), "counts": top}
    if len(ordered) > _TOP_N:
        result["note"] = f"showing top {_TOP_N} of {len(counts)} values"
    if missing:
        result["missing"] = missing
    return result


def _grouped_sum(records: list[dict], value_col: str, group_col: str) -> dict[str, Any]:
    groups: dict[str, dict[str, float]] = {}
    for r in records:
        g = r.get(group_col)
        v = r.get(value_col)
        key = str(g) if g is not None else "(missing)"
        bucket = groups.setdefault(key, {"sum": 0.0, "count": 0})
        bucket["count"] += 1
        if _is_number(v):
            bucket["sum"] += v
    ordered = sorted(groups.items(), key=lambda kv: kv[1]["sum"], reverse=True)
    top = {
        k: {"sum": round(b["sum"], 2), "count": b["count"]}
        for k, b in ordered[:_TOP_N]
    }
    result: dict[str, Any] = {"groups": top}
    if len(ordered) > _TOP_N:
        result["note"] = f"showing top {_TOP_N} of {len(groups)} groups"
    return result


def _date_range(records: list[dict], col: str) -> dict[str, Any]:
    vals = sorted(v for r in records if (v := r.get(col)) is not None)
    if not vals:
        return {"count": 0}
    return {"count": len(vals), "earliest": vals[0], "latest": vals[-1]}


def _headline_metrics(
    records: list[dict],
    kinds: dict[str, str],
    columns: list[str],
    value_col: str | None,
) -> dict[str, Any]:
    """Pre-compute the common DERIVED figures the LLM tends to get wrong
    (totals, won/lost, win rate, #1 sector). Deterministic and authoritative.
    """
    label_cols = [c for c in columns if kinds.get(c) == "label"]
    headline: dict[str, Any] = {"total_rows": len(records)}

    if value_col:
        vals = [r[value_col] for r in records if _is_number(r.get(value_col))]
        headline["value"] = {
            "column": value_col,
            "total": round(sum(vals), 2) if vals else 0,
            "avg": round(sum(vals) / len(vals), 2) if vals else 0,
            "rows_with_value": len(vals),
            "rows_missing_value": len(records) - len(vals),
        }

    # Won / lost / win-rate, inferred from a stage or status column.
    stage_col = next((c for c in label_cols if "stage" in c.lower()), None) or next(
        (c for c in label_cols if "status" in c.lower()), None
    )
    if stage_col:
        won = lost = 0
        for r in records:
            v = r.get(stage_col)
            if v is None:
                continue
            lv = str(v).lower()
            if "won" in lv or "win" in lv:
                won += 1
            elif "lost" in lv or "lose" in lv or "dead" in lv:
                lost += 1
        decided = won + lost
        headline["won_lost"] = {
            "basis_column": stage_col,
            "won": won,
            "lost": lost,
            "win_rate_pct": round(100 * won / decided, 1) if decided else None,
            "note": "win_rate = won / (won + lost); undecided deals excluded",
        }

    # #1 sector by total value.
    sector_col = next((c for c in label_cols if "sector" in c.lower()), None)
    if sector_col and value_col:
        groups = _grouped_sum(records, value_col, sector_col)["groups"]
        ranked = sorted(groups.items(), key=lambda kv: kv[1]["sum"], reverse=True)
        if ranked:
            top_name, top_b = ranked[0]
            headline["top_sector_by_value"] = {
                "column": sector_col,
                "name": top_name,
                "value": top_b["sum"],
                "deals": top_b["count"],
            }
            headline["sector_ranking_by_value"] = [
                {"name": n, "value": b["sum"], "deals": b["count"]}
                for n, b in ranked[:8]
            ]

    return headline


def _pick_value_column(kinds: dict[str, str], columns: list[str]) -> str | None:
    """Heuristically choose the primary monetary/value column."""
    numeric = [c for c in columns if kinds.get(c) == "number"]
    if not numeric:
        return None
    for c in numeric:
        if any(k in c.lower() for k in ("value", "amount", "revenue", "deal", "price")):
            return c
    return numeric[0]


def compute_analytics(board: dict[str, Any]) -> dict[str, Any]:
    """Compact, LLM-ready aggregates for a cleaned board."""
    records = board.get("records", [])
    kinds: dict[str, str] = board.get("data_quality", {}).get("column_kinds", {})
    columns = board.get("columns", [])

    number_cols = [c for c in columns if kinds.get(c) == "number"]
    date_cols = [c for c in columns if kinds.get(c) == "date"]
    # Only meaningful, low-cardinality dimensions (drops Owner/Client codes etc).
    dim_cols = _bi_dimensions(records, kinds, columns)

    value_col = _pick_value_column(kinds, columns)

    numeric_summary = {c: _numeric_summary(records, c) for c in number_cols}
    category_counts = {c: _value_counts(records, c) for c in dim_cols}
    date_ranges = {c: _date_range(records, c) for c in date_cols}

    value_breakdowns: dict[str, Any] = {}
    if value_col:
        for g in dim_cols:
            value_breakdowns[f"{value_col} by {g}"] = _grouped_sum(
                records, value_col, g
            )

    return {
        "board_name": board.get("board_name"),
        "row_count": len(records),
        "primary_value_column": value_col,
        "headline_metrics": _headline_metrics(records, kinds, columns, value_col),
        "columns": {c: kinds.get(c, "text") for c in columns},
        "numeric_summary": numeric_summary,
        "category_counts": category_counts,
        "value_breakdowns": value_breakdowns,
        "date_ranges": date_ranges,
        "data_quality": board.get("data_quality", {}),
    }


def sample_records(
    board: dict[str, Any],
    limit: int = 15,
    contains: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return up to `limit` individual rows (optionally filtered) for drill-down.

    `contains` maps a column name to a case-insensitive substring the value must
    contain. Used when the user asks to see specific/example records.
    """
    columns = ["Item Name"] + list(board.get("columns", []))
    out_rows = []
    for rec in board.get("records", []):
        if contains:
            ok = True
            for col, needle in contains.items():
                cell = rec.get(col)
                if cell is None or needle.lower() not in str(cell).lower():
                    ok = False
                    break
            if not ok:
                continue
        row = [rec.get("_name")] + [rec.get(c) for c in board.get("columns", [])]
        out_rows.append(row)
        if len(out_rows) >= limit:
            break
    return {
        "board_name": board.get("board_name"),
        "columns": columns,
        "rows": out_rows,
        "returned": len(out_rows),
    }
