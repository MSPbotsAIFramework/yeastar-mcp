"""Unit tests for `YeastarClient._request`'s HTTP-level retry/backoff policy
(SOP §5 "Network robustness", review round 1 must-fix on PRD-21279).

Exercised through `_list_extensions` -- same respx-mocked, no-network style as
test_tools.py -- so these tests cover the real call path (get_token -> list ->
del_token), not just the retry helper in isolation. `asyncio.sleep` is
monkeypatched to a no-op so the exponential backoff doesn't slow the suite
down or depend on wall-clock time.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from tests.conftest import API_PREFIX, list_body, token_ok_body
from yeastar_mcp import api_client as api_client_module
from yeastar_mcp.tools.extensions import _list_extensions


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace the real backoff sleep with a no-op, recording the delays asked for."""
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(api_client_module.asyncio, "sleep", fake_sleep)
    return delays


# Must-fix 1: bounded retry + backoff on 429/5xx, exact vocabulary mapping.


@respx.mock
async def test_429_retries_then_succeeds(with_credentials, no_sleep):
    records = [{"id": 1, "number": "1001", "caller_id_name": "A", "email_addr": "",
                "mobile_number": "", "presence_status": "available", "role_name": "Employee"}]
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    list_route = respx.get(f"{API_PREFIX}/extension/list").mock(
        side_effect=[httpx.Response(429), httpx.Response(429), httpx.Response(200, json=list_body(records))]
    )

    result = json.loads(await _list_extensions())

    assert result["items"] == records
    assert "error" not in result
    assert list_route.call_count == 3
    assert len(no_sleep) == 2  # one backoff sleep per retried 429


@respx.mock
async def test_429_exhausts_retries_maps_to_rate_limited(with_credentials, no_sleep):
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    list_route = respx.get(f"{API_PREFIX}/extension/list").mock(return_value=httpx.Response(429))

    result = json.loads(await _list_extensions())

    assert result["error"]["code"] == "rate_limited"
    assert result["error"]["retryable"] is True
    # initial attempt + MAX_RETRY_ATTEMPTS retries, never an unbounded loop
    assert list_route.call_count == 1 + api_client_module.MAX_RETRY_ATTEMPTS
    assert len(no_sleep) == api_client_module.MAX_RETRY_ATTEMPTS


@respx.mock
async def test_503_retries_then_succeeds(with_credentials, no_sleep):
    records = [{"id": 1, "number": "1001", "caller_id_name": "A", "email_addr": "",
                "mobile_number": "", "presence_status": "available", "role_name": "Employee"}]
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    list_route = respx.get(f"{API_PREFIX}/extension/list").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=list_body(records))]
    )

    result = json.loads(await _list_extensions())

    assert result["items"] == records
    assert list_route.call_count == 2


@respx.mock
async def test_5xx_exhausts_retries_maps_to_upstream_error_retryable(with_credentials, no_sleep):
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    list_route = respx.get(f"{API_PREFIX}/extension/list").mock(return_value=httpx.Response(502))

    result = json.loads(await _list_extensions())

    assert result["error"]["code"] == "upstream_error"
    assert result["error"]["retryable"] is True
    assert list_route.call_count == 1 + api_client_module.MAX_RETRY_ATTEMPTS


@respx.mock
async def test_retry_honors_retry_after_header(with_credentials, no_sleep):
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    respx.get(f"{API_PREFIX}/extension/list").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json=list_body([])),
        ]
    )

    await _list_extensions()

    assert no_sleep == [7.0]  # the header value, not the default exponential backoff


@respx.mock
async def test_other_4xx_not_retried(with_credentials, no_sleep):
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    list_route = respx.get(f"{API_PREFIX}/extension/list").mock(return_value=httpx.Response(404))

    result = json.loads(await _list_extensions())

    assert result["error"]["code"] == "upstream_error"
    assert result["error"]["retryable"] is False
    assert list_route.call_count == 1  # no retry for a plain 4xx
    assert no_sleep == []
