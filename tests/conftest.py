"""Shared fixtures: a credentials context manager and Yeastar JSON builders.

Every list endpoint under test is reached through the public tool functions
(`yeastar_mcp.tools.*`), with httpx calls intercepted by `respx` -- no real
network, no real PBX, matching the "needs a real vendor account" split in
docs/tickets/PRD-21279.ac.json (only TC-YST-019 needs one; everything else
here runs fully mocked).
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

from yeastar_mcp.api_client import YeastarCredentials
from yeastar_mcp.server import _credentials_var

BASE_URL = "https://pbx.example.test:8088"
API_PREFIX = f"{BASE_URL}/openapi/v1.0"


@pytest.fixture
def credentials() -> YeastarCredentials:
    return YeastarCredentials(base_url=BASE_URL, client_id="test-client-id", client_secret="s3cr3t-value")


@contextlib.contextmanager
def use_credentials(creds: YeastarCredentials):
    token = _credentials_var.set(creds)
    try:
        yield creds
    finally:
        _credentials_var.reset(token)


@pytest.fixture
def with_credentials(credentials: YeastarCredentials):
    with use_credentials(credentials) as creds:
        yield creds


def token_ok_body(access_token: str = "tok-1") -> dict[str, Any]:
    return {
        "errcode": 0,
        "errmsg": "SUCCESS",
        "access_token": access_token,
        "access_token_expire_time": 1800,
        "refresh_token": "refresh-1",
        "refresh_token_expire_time": 86400,
    }


def errcode_body(errcode: int, errmsg: str = "error") -> dict[str, Any]:
    return {"errcode": errcode, "errmsg": errmsg}


def list_body(items: list[dict[str, Any]], total_number: int | None = None) -> dict[str, Any]:
    return {
        "errcode": 0,
        "errmsg": "SUCCESS",
        "data": items,
        "total_number": total_number if total_number is not None else len(items),
    }
