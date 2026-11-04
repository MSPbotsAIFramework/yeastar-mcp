"""`yeastar_list_extensions` tool."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from yeastar_mcp.tools.common import DEFAULT_LIMIT, fetch_list

_EXTENSION_FIELDS = (
    "id",
    "number",
    "caller_id_name",
    "email_addr",
    "mobile_number",
    "presence_status",
    "role_name",
)


def _map_extension(item: dict[str, Any]) -> dict[str, Any]:
    return {field: item.get(field) for field in _EXTENSION_FIELDS}


async def _list_extensions(limit: int = DEFAULT_LIMIT, cursor: str | None = None) -> str:
    return await fetch_list("extension/list", limit=limit, cursor=cursor, items_key="data", map_item=_map_extension)


def register(mcp: FastMCP) -> None:
    mcp.tool(
        name="yeastar_list_extensions",
        description=(
            "List phone extensions configured on this PBX. "
            "Returns id, number, caller ID name, email, mobile number, "
            "presence status, and role for each extension."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )(_list_extensions)
