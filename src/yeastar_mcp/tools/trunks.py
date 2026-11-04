"""`yeastar_list_trunks` tool."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from yeastar_mcp.tools.common import DEFAULT_LIMIT, fetch_list

_COMMON_FIELDS = ("id", "name", "type", "status")


def _map_trunk(item: dict[str, Any]) -> dict[str, Any]:
    mapped = {field: item.get(field) for field in _COMMON_FIELDS}
    # Yeastar trunks come in two shapes depending on `type`: a "peer" trunk
    # (IP-to-IP, no registration) carries host_port/def_outbound_cid; an
    # "account" trunk (registers with a username/password) carries username.
    if item.get("type") == "account":
        mapped["username"] = item.get("username")
    else:
        mapped["host_port"] = item.get("host_port")
        mapped["def_outbound_cid"] = item.get("def_outbound_cid")
    return mapped


async def _list_trunks(limit: int = DEFAULT_LIMIT, cursor: str | None = None) -> str:
    return await fetch_list("trunk/list", limit=limit, cursor=cursor, items_key="data", map_item=_map_trunk)


def register(mcp: FastMCP) -> None:
    mcp.tool(
        name="yeastar_list_trunks",
        description=(
            "List SIP/IAX trunks configured on this PBX, with type, status, "
            "and the connection details relevant to that trunk type "
            "(host/port for peer trunks, username for account trunks)."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )(_list_trunks)
