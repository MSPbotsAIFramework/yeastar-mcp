"""`yeastar_list_cdr` tool (call detail records / "call reports")."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from yeastar_mcp.tools.common import DEFAULT_LIMIT, fetch_list

_CDR_FIELDS = (
    "time",
    "call_from",
    "call_to",
    "duration",
    "talk_duration",
    "disposition",
    "call_type",
    "src_addr",
)

# The upstream PBX has no start/end time filter on this endpoint (confirmed
# against the public API reference); narrowing a time window only works by
# paging through time-sorted results and stopping once you read past it.
_DESCRIPTION = (
    "List call detail records (CDR) from this PBX, newest first by default. "
    "The PBX has no server-side time-range filter: to look at a specific "
    "window, page through these time-sorted results and stop once the "
    "`time` field falls outside the window you care about."
)


def _map_cdr(item: dict[str, Any]) -> dict[str, Any]:
    return {field: item.get(field) for field in _CDR_FIELDS}


async def _list_cdr(
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    sort_by: str = "time",
    order_by: str = "desc",
) -> str:
    return await fetch_list(
        "cdr/list",
        limit=limit,
        cursor=cursor,
        extra_params={"sort_by": sort_by, "order_by": order_by},
        items_key="data",
        map_item=_map_cdr,
    )


def register(mcp: FastMCP) -> None:
    mcp.tool(
        name="yeastar_list_cdr",
        description=_DESCRIPTION,
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )(_list_cdr)
