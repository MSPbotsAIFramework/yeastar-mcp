"""Shared pagination, field-mapping and error-envelope helpers for the 6 tools.

All 6 tools share the same upstream shape: a `<resource>/list` endpoint that
takes `page`/`page_size` and returns `{"errcode", "total_number", <items>}`.
This module hides that behind `limit`/`cursor` so the Agent-facing tool
contract does not leak Yeastar's page-number pagination style (see Decisions
in docs/tickets/PRD-21279.md).
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Callable

import httpx

from yeastar_mcp.api_client import YeastarApiError, YeastarClient, YeastarCredentials
from yeastar_mcp.server import get_current_credentials, tool_error_json

logger = logging.getLogger("yeastar_mcp.tools")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0


def _encode_cursor(page: int) -> str:
    return base64.urlsafe_b64encode(str(page).encode("ascii")).decode("ascii")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 1
    try:
        page = int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
    except Exception as exc:  # noqa: BLE001 - any decode failure is the caller's bad cursor
        raise YeastarApiError(code="invalid_argument", message=f"Invalid cursor: {cursor!r}", retryable=False) from exc
    if page < 1:
        raise YeastarApiError(code="invalid_argument", message=f"Invalid cursor: {cursor!r}", retryable=False)
    return page


def _clamp_limit(limit: int) -> int:
    if limit < 1 or limit > MAX_LIMIT:
        raise YeastarApiError(
            code="invalid_argument",
            message=f"limit must be between 1 and {MAX_LIMIT}, got {limit}",
            retryable=False,
        )
    return limit


async def fetch_list(
    resource_path: str,
    *,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    extra_params: dict[str, Any] | None = None,
    items_key: str = "data",
    map_item: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> str:
    """Call a `<resource>/list` endpoint and return the serialized tool result.

    Handles the full lifecycle for one tool call: read credentials from the
    request context, clamp/validate `limit`/`cursor`, call the upstream list
    endpoint (get_token -> list -> del_token, with the one-retry-on-expiry
    behavior in `YeastarClient.list_resource`), map each item if a mapper is
    given, and compute `has_more` from `total_number`.
    """
    credentials: YeastarCredentials | None = get_current_credentials()
    if credentials is None:
        return tool_error_json("not_configured", "No PBX credentials in the current request context", False)

    try:
        page = _decode_cursor(cursor)
        page_size = _clamp_limit(limit)

        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if extra_params:
            params.update(extra_params)

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=READ_TIMEOUT)) as http_client:
            client = YeastarClient(credentials)
            body = await client.list_resource(http_client, resource_path, params)
    except YeastarApiError as exc:
        return tool_error_json(exc.code, exc.message, exc.retryable)

    raw_items = body.get(items_key) or []
    items = [map_item(item) for item in raw_items] if map_item else raw_items
    total_number = body.get("total_number", len(items))
    has_more = (page * page_size) < total_number

    result: dict[str, Any] = {"items": items, "has_more": has_more}
    if has_more:
        result["next_cursor"] = _encode_cursor(page + 1)

    return json.dumps(result, separators=(",", ":"), ensure_ascii=False)
