"""Entry point: mounts the MCP app and /health under one Starlette app.

The MCP app's lifespan must be wired to the outer Starlette app explicitly —
`Mount()` alone does not run a sub-app's lifespan, and without it `/mcp`
fails with "Task group is not initialized" while `/health` still reports
200 (SOP §7). `streamable_http_app()` already returns a Starlette app with
the right lifespan context manager; we reuse its `.router.lifespan_context`.
"""

from __future__ import annotations

import logging

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from yeastar_mcp.config import settings
from yeastar_mcp.server import CredentialMiddleware, create_mcp_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def health(_request) -> JSONResponse:
    # Pure local probe: never calls the PBX, so an unreachable/slow appliance
    # never makes the container get killed for being "unhealthy" (SOP §1.1).
    return JSONResponse({"status": "ok"})


def build_app() -> Starlette:
    mcp = create_mcp_server()
    # `streamable_http_app()` already mounts the MCP endpoint at
    # `mcp.settings.streamable_http_path` (default "/mcp") internally, so it
    # is mounted here at "/", not "/mcp" -- mounting it at "/mcp" again would
    # make the real endpoint "/mcp/mcp".
    mcp_app = mcp.streamable_http_app()

    app = Starlette(
        routes=[
            Route("/health", health),
            Mount("/", app=mcp_app),
        ],
        lifespan=mcp_app.router.lifespan_context,
    )
    app.add_middleware(CredentialMiddleware)
    return app


app = build_app()


def main() -> None:
    uvicorn.run(app, host=settings.mcp_http_host, port=settings.mcp_http_port)


if __name__ == "__main__":
    main()
