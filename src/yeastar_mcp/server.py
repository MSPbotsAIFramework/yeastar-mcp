"""FastMCP factory and the request-level credential middleware.

Credentials arrive on every `/mcp` request as three headers (see README's
Header table) and are never read from the environment or a config file. The
middleware copies them into a `ContextVar` for the lifetime of that single
request and resets it in a `finally` block, so concurrent requests for
different PBX appliances never see each other's values (AC9).
"""

from __future__ import annotations

import contextvars
import json
import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from yeastar_mcp.api_client import YeastarCredentials

logger = logging.getLogger("yeastar_mcp.server")

HEADER_BASE_URL = "X-Yeastar-Base-Url"
HEADER_CLIENT_ID = "X-Yeastar-Client-Id"
HEADER_CLIENT_SECRET = "X-Yeastar-Client-Secret"

REQUIRED_HEADERS = (HEADER_BASE_URL, HEADER_CLIENT_ID, HEADER_CLIENT_SECRET)

_credentials_var: contextvars.ContextVar[YeastarCredentials | None] = contextvars.ContextVar(
    "yeastar_credentials", default=None
)

SERVICE_INSTRUCTIONS = (
    "Yeastar P-Series Appliance-Edition PBX connector. Read-only: list phone "
    "extensions, trunks, call-routing configuration (inbound routes, outbound "
    "routes, IVRs), and call detail records (CDR). Typical flow: list "
    "extensions or trunks to understand the phone system layout, then list "
    "CDR to review recent call activity. CDR has no server-side time filter; "
    "it is sorted newest-first by default, so narrow a time window by paging "
    "through results. All tools require one appliance's credentials per "
    "call; this connector serves exactly one PBX per request."
)


class CredentialMiddleware(BaseHTTPMiddleware):
    """Reads the three required headers on `/mcp` requests, else returns 401."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path != "/mcp":
            return await call_next(request)

        missing = [name for name in REQUIRED_HEADERS if not request.headers.get(name)]
        if missing:
            return JSONResponse(
                status_code=401,
                content={"error": "missing required header(s)", "missing_headers": missing},
            )

        credentials = YeastarCredentials(
            base_url=request.headers[HEADER_BASE_URL],
            client_id=request.headers[HEADER_CLIENT_ID],
            client_secret=request.headers[HEADER_CLIENT_SECRET],
        )
        token = _credentials_var.set(credentials)
        try:
            return await call_next(request)
        finally:
            _credentials_var.reset(token)


def get_current_credentials() -> YeastarCredentials | None:
    """Read the credentials set by `CredentialMiddleware` for this request.

    Returns `None` outside of a request (e.g. a bug bypassing the
    middleware) so callers can surface `not_configured` instead of crashing.
    """
    return _credentials_var.get()


def tool_error_json(code: str, message: str, retryable: bool) -> str:
    """Serialize the fixed error envelope. Compact JSON, ASCII-safe is not
    forced (vendor data may be non-ASCII); never includes a credential."""
    return json.dumps({"error": {"code": code, "message": message, "retryable": retryable}}, separators=(",", ":"))


def create_mcp_server() -> FastMCP:
    mcp = FastMCP(
        name="yeastar-mcp",
        instructions=SERVICE_INSTRUCTIONS,
        stateless_http=True,
        # The service runs behind MSPbots' internal proxy, never exposed
        # directly to the public internet, so DNS-rebinding protection is
        # safe to disable; leaving it on rejects the proxy's forwarded Host
        # header with 421 Misdirected Request.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    from yeastar_mcp.tools import extensions, reports, routing, trunks

    extensions.register(mcp)
    trunks.register(mcp)
    routing.register(mcp)
    reports.register(mcp)

    return mcp
