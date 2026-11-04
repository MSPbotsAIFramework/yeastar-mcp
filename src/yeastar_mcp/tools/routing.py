"""`yeastar_list_inbound_routes`, `yeastar_list_outbound_routes`, `yeastar_list_ivrs` tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from yeastar_mcp.tools.common import DEFAULT_LIMIT, fetch_list

_INBOUND_ROUTE_FIELDS = (
    "id",
    "pos",
    "name",
    "default_destination",
    "business_hours_destination",
    "outside_business_hours_destination",
    "holidays_hours_destination",
)


def _map_inbound_route(item: dict[str, Any]) -> dict[str, Any]:
    return {field: item.get(field) for field in _INBOUND_ROUTE_FIELDS}


async def _list_inbound_routes(limit: int = DEFAULT_LIMIT, cursor: str | None = None) -> str:
    return await fetch_list("inbound_route/list", limit=limit, cursor=cursor, items_key="data", map_item=_map_inbound_route)


async def _list_outbound_routes(limit: int = DEFAULT_LIMIT, cursor: str | None = None) -> str:
    # Returned as-is (no field remapping): the upstream shape (trunk, pattern,
    # etc.) is already the Agent-useful shape, and there is no peer/account-
    # style field split to normalize here, unlike trunks.
    return await fetch_list("outbound_route/list", limit=limit, cursor=cursor, items_key="data")


async def _list_ivrs(limit: int = DEFAULT_LIMIT, cursor: str | None = None) -> str:
    return await fetch_list("ivr/list", limit=limit, cursor=cursor, items_key="data")


def register(mcp: FastMCP) -> None:
    mcp.tool(
        name="yeastar_list_inbound_routes",
        description=(
            "List inbound call routes on this PBX: for each route, the "
            "default, business-hours, after-hours, and holiday destinations."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )(_list_inbound_routes)

    mcp.tool(
        name="yeastar_list_outbound_routes",
        description="List outbound call routes on this PBX: trunk and dial-pattern used for each route.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )(_list_outbound_routes)

    mcp.tool(
        name="yeastar_list_ivrs",
        description="List IVR (auto-attendant) menus configured on this PBX.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )(_list_ivrs)
