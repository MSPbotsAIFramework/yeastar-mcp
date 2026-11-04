"""Unit tests for the 6 tools: tools/list snapshot, pagination, field mapping,
error mapping. See docs/tickets/PRD-21279.ac.json for the TC-YST-* mapping.

No network and no real appliance: every upstream call is intercepted by
respx. TC-YST-009 (description text, manual) and TC-YST-019 (needs a real
vendor account) are not covered here -- see the ticket's Self-test section.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from tests.conftest import API_PREFIX, errcode_body, list_body, token_ok_body
from yeastar_mcp.server import create_mcp_server
from yeastar_mcp.tools.extensions import _list_extensions
from yeastar_mcp.tools.reports import _list_cdr
from yeastar_mcp.tools.routing import _list_inbound_routes, _list_ivrs, _list_outbound_routes
from yeastar_mcp.tools.trunks import _list_trunks

EXPECTED_TOOL_NAMES = {
    "yeastar_list_extensions",
    "yeastar_list_trunks",
    "yeastar_list_inbound_routes",
    "yeastar_list_outbound_routes",
    "yeastar_list_ivrs",
    "yeastar_list_cdr",
}


# TC-YST-001
async def test_tools_list_returns_six_read_only_tools():
    mcp = create_mcp_server()
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == EXPECTED_TOOL_NAMES
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} has no annotations"
        assert tool.annotations.readOnlyHint is True, f"{tool.name} is not marked read-only"


# TC-YST-002
@respx.mock
async def test_list_extensions_paginates_with_has_more(with_credentials):
    records = [{"id": i, "number": str(1000 + i), "caller_id_name": f"User {i}",
                "email_addr": "", "mobile_number": "", "presence_status": "available",
                "role_name": "Employee"} for i in range(50)]
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    respx.get(f"{API_PREFIX}/extension/list").mock(return_value=httpx.Response(200, json=list_body(records, total_number=60)))

    result = json.loads(await _list_extensions())

    assert len(result["items"]) == 50
    assert result["has_more"] is True
    assert "next_cursor" in result


# TC-YST-003 / TC-YST-010 (AC10, via trunks is TC-YST-018; this one is extensions)
@respx.mock
async def test_list_extensions_empty_is_not_an_error(with_credentials):
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    respx.get(f"{API_PREFIX}/extension/list").mock(return_value=httpx.Response(200, json=list_body([], total_number=0)))

    result = json.loads(await _list_extensions())

    assert result == {"items": [], "has_more": False}
    assert "error" not in result


# TC-YST-004
@respx.mock
async def test_list_trunks_maps_peer_and_account_fields(with_credentials):
    peer_trunk = {"id": 1, "name": "peer-1", "type": "peer", "status": "ok",
                  "host_port": "10.0.0.5:5060", "def_outbound_cid": "15551234567",
                  "username": "should-not-appear"}
    account_trunk = {"id": 2, "name": "acct-1", "type": "account", "status": "ok",
                      "username": "sip-user-1", "host_port": "should-not-appear"}
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    respx.get(f"{API_PREFIX}/trunk/list").mock(return_value=httpx.Response(200, json=list_body([peer_trunk, account_trunk])))

    result = json.loads(await _list_trunks())

    peer, account = result["items"]
    assert peer["host_port"] == "10.0.0.5:5060"
    assert peer["def_outbound_cid"] == "15551234567"
    assert "username" not in peer
    assert account["username"] == "sip-user-1"
    assert "host_port" not in account


# TC-YST-005
@respx.mock
async def test_list_inbound_routes_maps_all_destination_fields(with_credentials):
    route = {
        "id": 1, "pos": 0, "name": "main",
        "default_destination": "extension-100",
        "business_hours_destination": "extension-100",
        "outside_business_hours_destination": "ivr-1",
        "holidays_hours_destination": "voicemail-100",
    }
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    respx.get(f"{API_PREFIX}/inbound_route/list").mock(return_value=httpx.Response(200, json=list_body([route])))

    result = json.loads(await _list_inbound_routes())

    assert result["items"][0] == route


# TC-YST-006
@respx.mock
async def test_list_outbound_routes_passthrough_shape(with_credentials):
    routes = [{"id": 1, "name": "local", "trunk": "trunk-1", "pattern": "_1NXXNXXXXXX"}]
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    respx.get(f"{API_PREFIX}/outbound_route/list").mock(return_value=httpx.Response(200, json=list_body(routes)))

    result = json.loads(await _list_outbound_routes())

    assert result["items"] == routes


# TC-YST-007
@respx.mock
async def test_list_ivrs_returns_entries(with_credentials):
    ivrs = [{"id": 1, "name": "main-ivr", "prompt": "welcome.wav"}]
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    respx.get(f"{API_PREFIX}/ivr/list").mock(return_value=httpx.Response(200, json=list_body(ivrs)))

    result = json.loads(await _list_ivrs())

    assert result["items"] == ivrs


# TC-YST-008
@respx.mock
async def test_list_cdr_defaults_to_time_desc_and_paginates(with_credentials):
    records = [{"time": "2026-11-01 10:00:00", "call_from": "1001", "call_to": "1002",
                "duration": 30, "talk_duration": 25, "disposition": "ANSWERED",
                "call_type": "Internal", "src_addr": "1001"}]
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    cdr_route = respx.get(f"{API_PREFIX}/cdr/list").mock(return_value=httpx.Response(200, json=list_body(records)))

    result = json.loads(await _list_cdr())

    assert result["items"] == records
    assert result["has_more"] is False
    sent_params = cdr_route.calls.last.request.url.params
    assert sent_params["sort_by"] == "time"
    assert sent_params["order_by"] == "desc"


# TC-YST-012
@respx.mock
async def test_bad_credentials_map_to_unauthorized(with_credentials):
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=errcode_body(10005, "ACCESS DENIED")))

    result = json.loads(await _list_extensions())

    assert result["error"]["code"] == "unauthorized"
    assert result["error"]["retryable"] is False
    assert "10005" in result["error"]["message"]


# TC-YST-013
@respx.mock
async def test_expired_token_mid_call_retries_once_and_succeeds(with_credentials):
    records = [{"id": 1, "number": "1001", "caller_id_name": "A", "email_addr": "",
                "mobile_number": "", "presence_status": "available", "role_name": "Employee"}]

    token_route = respx.post(f"{API_PREFIX}/get_token").mock(
        side_effect=[httpx.Response(200, json=token_ok_body("tok-1")), httpx.Response(200, json=token_ok_body("tok-2"))]
    )
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    list_route = respx.get(f"{API_PREFIX}/extension/list").mock(
        side_effect=[httpx.Response(200, json=errcode_body(10004, "TOKEN EXPIRED")), httpx.Response(200, json=list_body(records))]
    )

    result = json.loads(await _list_extensions())

    assert result["items"] == records
    assert "error" not in result
    assert token_route.call_count == 2
    assert list_route.call_count == 2


# TC-YST-014
@respx.mock
async def test_expired_token_twice_stops_after_one_retry(with_credentials):
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    list_route = respx.get(f"{API_PREFIX}/extension/list").mock(
        return_value=httpx.Response(200, json=errcode_body(10004, "TOKEN EXPIRED"))
    )

    result = json.loads(await _list_extensions())

    assert result["error"]["code"] == "unauthorized"
    assert list_route.call_count == 2  # original attempt + exactly one retry, no loop


# TC-YST-015
@respx.mock
async def test_timeout_maps_to_upstream_error_without_leaking_secrets(with_credentials):
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body("top-secret-token")))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    respx.get(f"{API_PREFIX}/extension/list").mock(side_effect=httpx.ConnectTimeout("timed out"))

    result = json.loads(await _list_extensions())

    assert result["error"]["code"] == "upstream_error"
    assert result["error"]["retryable"] is True
    message = result["error"]["message"]
    assert "s3cr3t-value" not in message  # the client secret from `with_credentials`
    assert "top-secret-token" not in message


# TC-YST-016
@respx.mock
async def test_unknown_errcode_maps_to_upstream_error(with_credentials):
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    respx.get(f"{API_PREFIX}/extension/list").mock(return_value=httpx.Response(200, json=errcode_body(99999, "mystery")))

    result = json.loads(await _list_extensions())

    assert result["error"]["code"] == "upstream_error"


# TC-YST-018
@respx.mock
async def test_list_trunks_empty_is_not_an_error(with_credentials):
    respx.post(f"{API_PREFIX}/get_token").mock(return_value=httpx.Response(200, json=token_ok_body()))
    respx.get(f"{API_PREFIX}/del_token").mock(return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "SUCCESS"}))
    respx.get(f"{API_PREFIX}/trunk/list").mock(return_value=httpx.Response(200, json=list_body([], total_number=0)))

    result = json.loads(await _list_trunks())

    assert result == {"items": [], "has_more": False}
