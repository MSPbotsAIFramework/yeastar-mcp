"""Thin async wrapper around the Yeastar P-Series Appliance-Edition OpenAPI.

Yeastar's API returns HTTP 200 for both success and failure; the real
outcome is the `errcode` field in the JSON body (0 = success, non-zero =
error). Every call here inspects `errcode`, never the HTTP status, and maps
the result onto the fixed MCP error vocabulary (`YeastarApiError.code`).

One instance is created per incoming MCP request (see server.py) and is
never reused across requests: there is no cross-request token cache, so a
token is obtained and revoked once per tool call (see Decisions in
docs/tickets/PRD-21279.md). This keeps a bug in one tenant's credential
handling from ever being able to leak into another tenant's request.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("yeastar_mcp.api_client")

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0

# SOP §5 "Network robustness" (mandatory): bounded retry + exponential backoff on
# 429/5xx, honoring Retry-After, with the whole call (including retries) staying
# under 120s.
MAX_RETRY_ATTEMPTS = 3  # retries beyond the initial attempt (4 attempts total, worst case)
MAX_TOTAL_WALL_TIME = 120.0  # seconds, matches the SOP §14 checklist line item
INITIAL_BACKOFF_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Delay before retry `attempt` (0-indexed). Honors a numeric `Retry-After`
    (seconds) if the PBX sends one; otherwise exponential backoff."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass  # not a plain seconds value (e.g. an HTTP-date) -- fall back to backoff
    return INITIAL_BACKOFF_SECONDS * (BACKOFF_MULTIPLIER**attempt)

# Yeastar errcode -> (mcp error code, retryable). Codes not in this table
# fall back to the ("upstream_error", True) default in _map_errcode.
_ERRCODE_MAP: dict[int, tuple[str, bool]] = {
    10005: ("unauthorized", False),  # ACCESS DENIED: bad client id/secret or scope
    10004: ("unauthorized", False),  # TOKEN EXPIRED: handled with a retry by the caller;
    #                                   this entry is the fallback if the retry also fails.
    10009: ("upstream_error", False),  # OPERATION FAILED: feature disabled / PBX-side permission
}


class YeastarApiError(Exception):
    """A tool-facing error. `code` is one of the fixed MCP error-code values."""

    def __init__(self, code: str, message: str, retryable: bool, errcode: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        # Raw Yeastar errcode, kept internally so callers (e.g. the 10004
        # retry-once path) can branch on the exact upstream reason without
        # parsing the human-readable message. Never surfaced to the Agent.
        self.errcode = errcode


def _map_errcode(errcode: int, errmsg: str) -> YeastarApiError:
    code, retryable = _ERRCODE_MAP.get(errcode, ("upstream_error", True))
    return YeastarApiError(code=code, message=f"Yeastar errcode {errcode}: {errmsg}", retryable=retryable, errcode=errcode)


@dataclass(frozen=True)
class YeastarCredentials:
    base_url: str
    client_id: str
    client_secret: str


class YeastarClient:
    """One client per MCP request. Not shared, not cached, not reused."""

    def __init__(self, credentials: YeastarCredentials) -> None:
        self._credentials = credentials
        self._timeout = httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=READ_TIMEOUT)

    def _url(self, path: str) -> str:
        return f"{self._credentials.base_url.rstrip('/')}/openapi/v1.0/{path}"

    async def _request(self, client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        start = time.monotonic()
        attempt = 0
        while True:
            try:
                response = await client.request(method, self._url(path), **kwargs)
            except httpx.TimeoutException as exc:
                raise YeastarApiError(code="upstream_error", message=f"Timed out calling the PBX: {exc}", retryable=True) from exc
            except httpx.TransportError as exc:
                raise YeastarApiError(code="upstream_error", message=f"Could not reach the PBX: {exc}", retryable=True) from exc

            if response.status_code == 429 or response.status_code >= 500:
                remaining_budget = MAX_TOTAL_WALL_TIME - (time.monotonic() - start)
                if attempt < MAX_RETRY_ATTEMPTS and remaining_budget > 0:
                    await asyncio.sleep(min(_retry_delay(response, attempt), remaining_budget))
                    attempt += 1
                    continue
                # Retries exhausted (or no wall-time budget left): report the
                # final response using the fixed error vocabulary (SOP §4.2).
                if response.status_code == 429:
                    raise YeastarApiError(
                        code="rate_limited",
                        message=f"PBX returned HTTP 429 (rate limited) after {attempt} retry/retries",
                        retryable=True,
                    )
                raise YeastarApiError(
                    code="upstream_error",
                    message=f"PBX returned HTTP {response.status_code} after {attempt} retry/retries",
                    retryable=True,
                )

            if response.status_code >= 400:
                # Other 4xx are not retried per SOP §5 ("no retry for other 4xx").
                raise YeastarApiError(
                    code="upstream_error",
                    message=f"PBX returned HTTP {response.status_code}",
                    retryable=False,
                )
            break

        try:
            body = response.json()
        except ValueError as exc:
            raise YeastarApiError(code="upstream_error", message="PBX returned a non-JSON response", retryable=True) from exc

        errcode = body.get("errcode")
        if errcode != 0:
            raise _map_errcode(errcode, body.get("errmsg", "unknown error"))
        return body

    async def get_token(self, client: httpx.AsyncClient) -> str:
        body = await self._request(
            client,
            "POST",
            "get_token",
            json={"username": self._credentials.client_id, "password": self._credentials.client_secret},
        )
        return body["access_token"]

    async def del_token(self, client: httpx.AsyncClient, access_token: str) -> None:
        # Best-effort: revocation failing should never surface as a tool error.
        try:
            await self._request(client, "GET", "del_token", params={"access_token": access_token})
        except YeastarApiError as exc:
            logger.warning("del_token failed (ignored): %s", exc.message)

    async def list_resource(self, client: httpx.AsyncClient, resource_path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch one page of a `<resource>/list` endpoint.

        Obtains a token, calls the endpoint, retries exactly once with a
        fresh token if the first call reports errcode 10004 (token expired
        between acquisition and use), then revokes whichever token was used
        last. Never caches a token across calls (see module docstring).
        """
        token = await self.get_token(client)
        try:
            try:
                return await self._request(client, "GET", resource_path, params={**params, "access_token": token})
            except YeastarApiError as exc:
                if exc.errcode != 10004:
                    raise
                # Token expired mid-call: re-authenticate and retry exactly once.
                await self.del_token(client, token)
                token = await self.get_token(client)
                return await self._request(client, "GET", resource_path, params={**params, "access_token": token})
        finally:
            await self.del_token(client, token)
