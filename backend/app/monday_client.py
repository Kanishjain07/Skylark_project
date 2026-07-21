"""Thin async client for the monday.com GraphQL API (read-only).

Handles authentication, pagination via items_page/next_items_page, and
returns raw board data. Cleaning/normalization happens in data_cleaning.py.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from .config import get_settings


class MondayError(RuntimeError):
    """Raised when the monday.com API returns an error or is unreachable."""


class MondayClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        # very small in-process cache: board_id -> (fetched_at, payload)
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._settings.monday_api_token,
            "Content-Type": "application/json",
            "API-Version": "2024-10",
        }

    async def _post(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        if not self._settings.monday_api_token:
            raise MondayError(
                "MONDAY_API_TOKEN is not set. Add it to backend/.env"
            )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._settings.monday_api_url,
                    headers=self._headers,
                    json={"query": query, "variables": variables or {}},
                )
        except httpx.HTTPError as exc:  # network-level failure
            raise MondayError(f"Could not reach monday.com: {exc}") from exc

        if resp.status_code == 401:
            raise MondayError("monday.com rejected the API token (401 Unauthorized).")
        if resp.status_code >= 400:
            raise MondayError(
                f"monday.com returned HTTP {resp.status_code}: {resp.text[:300]}"
            )

        data = resp.json()
        if data.get("errors"):
            messages = "; ".join(e.get("message", str(e)) for e in data["errors"])
            raise MondayError(f"monday.com GraphQL error: {messages}")
        return data["data"]

    async def fetch_board(self, board_id: str) -> dict[str, Any]:
        """Return {board_id, board_name, columns, items} with all pages fetched.

        Results are cached in-process for BOARD_CACHE_TTL_SECONDS.
        """
        ttl = self._settings.board_cache_ttl_seconds
        cached = self._cache.get(board_id)
        if cached and (time.time() - cached[0]) < ttl:
            return cached[1]

        first_query = """
        query ($boardId: [ID!], $limit: Int!) {
          boards(ids: $boardId) {
            id
            name
            columns { id title type }
            items_page(limit: $limit) {
              cursor
              items {
                id
                name
                column_values {
                  id
                  text
                  value
                  column { title type }
                }
              }
            }
          }
        }
        """
        data = await self._post(first_query, {"boardId": [board_id], "limit": 250})
        boards = data.get("boards") or []
        if not boards:
            raise MondayError(
                f"No board found with id {board_id}. Check the board ID and that "
                "the token has access to it."
            )
        board = boards[0]
        columns = board.get("columns", [])
        items = list(board["items_page"]["items"])
        cursor = board["items_page"].get("cursor")

        # Paginate remaining items.
        next_query = """
        query ($cursor: String!, $limit: Int!) {
          next_items_page(cursor: $cursor, limit: $limit) {
            cursor
            items {
              id
              name
              column_values { id text value column { title type } }
            }
          }
        }
        """
        while cursor:
            page = await self._post(next_query, {"cursor": cursor, "limit": 250})
            page_data = page["next_items_page"]
            items.extend(page_data["items"])
            cursor = page_data.get("cursor")

        result = {
            "board_id": board["id"],
            "board_name": board["name"],
            "columns": columns,
            "items": items,
        }
        self._cache[board_id] = (time.time(), result)
        return result

    async def health(self) -> dict[str, Any]:
        """Lightweight call to verify token validity."""
        data = await self._post("query { me { id name email } }")
        return data.get("me", {})


# module-level singleton
monday_client = MondayClient()
