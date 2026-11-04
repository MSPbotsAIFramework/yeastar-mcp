"""Unit tests for the credential middleware: missing-header 401s (AC6) and
request-level isolation (AC9). See docs/tickets/PRD-21279.ac.json."""

from __future__ import annotations

import asyncio

from starlette.testclient import TestClient

from yeastar_mcp.__main__ import build_app
from yeastar_mcp.api_client import YeastarCredentials
from yeastar_mcp.server import HEADER_BASE_URL, HEADER_CLIENT_ID, HEADER_CLIENT_SECRET, _credentials_var, get_current_credentials

ALL_HEADERS = {
    HEADER_BASE_URL: "https://pbx.example.test:8088",
    HEADER_CLIENT_ID: "cid",
    HEADER_CLIENT_SECRET: "secret",
}


# TC-YST-010
def test_missing_one_header_returns_401_naming_it():
    headers = dict(ALL_HEADERS)
    del headers[HEADER_CLIENT_SECRET]

    with TestClient(build_app()) as client:
        response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 401
    assert response.json()["missing_headers"] == [HEADER_CLIENT_SECRET]


# TC-YST-011
def test_missing_all_three_headers_returns_401_naming_it():
    with TestClient(build_app()) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 401
    assert set(response.json()["missing_headers"]) == {HEADER_BASE_URL, HEADER_CLIENT_ID, HEADER_CLIENT_SECRET}


# TC-YST-017
async def test_concurrent_requests_do_not_leak_context():
    """Two simulated concurrent requests, each setting its own ContextVar
    scope the way `CredentialMiddleware.dispatch` does. `asyncio.gather`
    schedules each coroutine as its own Task, and each Task gets its own
    copy of the current context -- so setting the ContextVar inside one must
    never be visible from the other."""

    results: dict[str, str] = {}

    async def simulate_request(tag: str) -> None:
        creds = YeastarCredentials(base_url=f"https://{tag}.example.test", client_id=f"cid-{tag}", client_secret="s")
        token = _credentials_var.set(creds)
        try:
            # Yield control so the two simulated requests actually interleave
            # instead of running sequentially.
            await asyncio.sleep(0)
            seen = get_current_credentials()
            await asyncio.sleep(0)
            results[tag] = seen.client_id if seen else "MISSING"
        finally:
            _credentials_var.reset(token)

    await asyncio.gather(simulate_request("a"), simulate_request("b"))

    assert results == {"a": "cid-a", "b": "cid-b"}
