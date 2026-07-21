"""Normalization + resilience for messy monday.com data.

Turns raw monday.com items into clean, typed records and produces a
data-quality report the agent can surface to the user.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from dateutil import parser as date_parser


# ---------------------------------------------------------------------------
# Value normalizers
# ---------------------------------------------------------------------------

_NULL_TOKENS = {"", "n/a", "na", "none", "null", "-", "--", "tbd", "unknown", "?"}


def clean_text(value: Any) -> str | None:
    """Trim, collapse whitespace, and treat common null-tokens as None."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _NULL_TOKENS:
        return None
    return re.sub(r"\s+", " ", text)


def normalize_label(value: Any) -> str | None:
    """Canonical form for categorical fields (sector, status, stage...).

    'ENERGY ', 'energy', 'Energy' -> 'Energy'. Keeps a readable Title Case
    while merging case/whitespace variants.
    """
    text = clean_text(value)
    if text is None:
        return None
    # Preserve common acronyms in upper case, title-case the rest.
    words = []
    for word in text.split(" "):
        if word.isupper() and len(word) <= 4:
            words.append(word)  # e.g. B2B, SaaS-ish acronyms
        else:
            words.append(word.capitalize())
    return " ".join(words)


def parse_date(value: Any) -> date | None:
    """Parse many messy date formats into a date. Returns None if impossible.

    Handles: 2024-01-05, 01/05/2024, 5 Jan 2024, Jan 5 2024, 2024/01/05,
    and monday-style dict values. Ambiguous m/d vs d/m defaults to day-first
    only when the first component is > 12.
    """
    if value is None:
        return None
    if isinstance(value, dict):  # monday date column JSON: {"date": "2024-01-05"}
        value = value.get("date")
    text = clean_text(value)
    if text is None:
        return None

    # Decide day-first heuristically for slash/dot separated dates.
    dayfirst = False
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}$", text)
    if m and int(m.group(1)) > 12:
        dayfirst = True

    try:
        parsed = date_parser.parse(text, dayfirst=dayfirst, fuzzy=True)
        return parsed.date()
    except (ValueError, OverflowError, TypeError):
        return None


def parse_number(value: Any) -> float | None:
    """Extract a number from messy strings: '$1,200', '1.2k', '45%', '  90 '."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = clean_text(value)
    if text is None:
        return None

    lowered = text.lower().replace(",", "").strip()
    multiplier = 1.0
    if lowered.endswith("k"):
        multiplier, lowered = 1_000.0, lowered[:-1]
    elif lowered.endswith("m"):
        multiplier, lowered = 1_000_000.0, lowered[:-1]
    # strip currency symbols / percent / stray chars, keep digits . and -
    cleaned = re.sub(r"[^0-9.\-]", "", lowered)
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Column-type aware extraction
# ---------------------------------------------------------------------------

def _raw_cell(item: dict, title: str) -> dict | None:
    for cv in item.get("column_values", []):
        col = cv.get("column") or {}
        if (col.get("title") or "").strip().lower() == title.strip().lower():
            return cv
    return None


def _cell_text(item: dict, title: str) -> str | None:
    cell = _raw_cell(item, title)
    if cell is None:
        return None
    return clean_text(cell.get("text"))


# ---------------------------------------------------------------------------
# Board -> clean records + quality report
# ---------------------------------------------------------------------------

def _classify_column(title: str, col_type: str) -> str:
    """Best-effort guess of how to normalize a column."""
    t = title.lower()
    if col_type in ("date", "timeline", "creation_log", "last_updated"):
        return "date"
    if any(k in t for k in ("date", "close", "start", "end", "due", "delivery", "created")):
        return "date"
    if col_type in ("numbers", "numeric", "rating"):
        return "number"
    if any(k in t for k in ("value", "amount", "revenue", "price", "cost", "budget", "size", "qty", "quantity", "count")):
        return "number"
    if col_type in ("status", "dropdown", "color"):
        return "label"
    if any(k in t for k in ("sector", "status", "stage", "priority", "type", "category", "owner", "region")):
        return "label"
    return "text"


def clean_board(board: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw board payload into clean records + a quality report."""
    columns = board.get("columns", [])
    col_kinds = {
        c["title"]: _classify_column(c["title"], c.get("type", ""))
        for c in columns
    }

    records: list[dict[str, Any]] = []
    total_cells = 0
    missing_cells = 0
    unparseable_dates: dict[str, int] = {}
    field_missing: dict[str, int] = {}

    for item in board.get("items", []):
        record: dict[str, Any] = {"_id": item.get("id"), "_name": clean_text(item.get("name"))}
        for col in columns:
            title = col["title"]
            kind = col_kinds[title]
            raw = _cell_text(item, title)
            total_cells += 1

            if raw is None:
                missing_cells += 1
                field_missing[title] = field_missing.get(title, 0) + 1
                record[title] = None
                continue

            if kind == "date":
                parsed = parse_date(raw)
                if parsed is None:
                    unparseable_dates[title] = unparseable_dates.get(title, 0) + 1
                    record[title] = None
                else:
                    record[title] = parsed.isoformat()
            elif kind == "number":
                record[title] = parse_number(raw)
            elif kind == "label":
                record[title] = normalize_label(raw)
            else:
                record[title] = clean_text(raw)
        records.append(record)

    row_count = len(records)
    completeness = (
        round(100 * (total_cells - missing_cells) / total_cells, 1)
        if total_cells
        else 0.0
    )

    quality = {
        "row_count": row_count,
        "column_count": len(columns),
        "overall_completeness_pct": completeness,
        # only surface columns that actually have gaps, worst first
        "missing_by_field": dict(
            sorted(field_missing.items(), key=lambda kv: kv[1], reverse=True)
        ),
        "unparseable_dates_by_field": unparseable_dates,
        "column_kinds": col_kinds,
    }

    return {
        "board_id": board.get("board_id"),
        "board_name": board.get("board_name"),
        "columns": [c["title"] for c in columns],
        "records": records,
        "data_quality": quality,
    }
