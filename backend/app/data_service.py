"""Fetches + cleans board data. Sits between monday_client and the agent."""
from __future__ import annotations

from typing import Any

from .config import get_settings
from .data_cleaning import clean_board
from .monday_client import monday_client


async def get_work_orders() -> dict[str, Any]:
    settings = get_settings()
    raw = await monday_client.fetch_board(settings.monday_work_orders_board_id)
    return clean_board(raw)


async def get_deals() -> dict[str, Any]:
    settings = get_settings()
    raw = await monday_client.fetch_board(settings.monday_deals_board_id)
    return clean_board(raw)
