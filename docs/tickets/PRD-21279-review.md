# PRD-21279 · Code review

## Round 1 · 2026-11-04 · reviewed af86f86 (base f9e9cb6)

Verdict: changes requested

### Scope

`git diff f9e9cb6...af86f86` on `MSPbotsAIFramework/yeastar-mcp` (new repo, first version; base is the
repo's default branch `main` at the commit recorded in the `[DEV]` stub). Gates re-run independently on
this host: `uv run pytest -q` → `17 passed`; `uv run mypy src` → `Success: no issues found in 11 source
files` — matches the Self-test section exactly. README "MSPbots Connector" section diffed byte-for-byte
against `reference/readme-connector-section.md` — identical. No CJK found (`grep -rnP
'[\x{4e00}-\x{9fff}]'`). No real secrets found (grep fallback hits are all header-name constants / the
test fixture's fake secret `s3cr3t-value`).

### Findings

1. [must-fix] `src/yeastar_mcp/api_client.py:82-87` — HTTP-level `429` and `5xx` responses are neither
   retried nor mapped correctly, which is a "必须" (mandatory) requirement of the vendor-mcp SOP:
   - SOP §5 "网络健壮性" requires "对 `429` 和 `5xx` 做有限次重试 + 指数 backoff，并尊重 `Retry-After`"
     (bounded retry with exponential backoff for 429/5xx, honoring `Retry-After`). The current code has
     no retry path for this at all — `_request()` raises `YeastarApiError` on the first `status_code >=
     400` response with no retry loop, no backoff, no `Retry-After` handling.
   - SOP §4.2's fixed error vocabulary maps HTTP `429` → `code: rate_limited, retryable: true`. The
     current code falls through the generic `status_code >= 400` branch, which sets
     `code="upstream_error"` unconditionally and `retryable=response.status_code >= 500` — so a `429`
     response is reported as `upstream_error` with `retryable: false`, the opposite of what the SOP's own
     vocabulary table (and an Agent reading `retryable`) expects.
   - Why this matters here specifically: the design's own Non-functional section documents a real
     8-concurrent-token vendor cap and a known risk of hitting it under concurrent load against one
     appliance — exactly the scenario a `429`/`503`-style backpressure response is meant to signal and
     recover from with a retry. As written, that condition is surfaced as a non-retryable error instead.
   - This is also an explicit line item on the SOP §14 delivery checklist ("对 429 / 5xx 有限重试 +
     backoff，尊重 Retry-After，单次调用总耗时 < 120s") that the Self-test section does not claim was done,
     and it was not.
   - What would fix it: in `_request`, on `status_code == 429` or `>= 500`, retry a bounded number of
     times with exponential backoff, honoring a `Retry-After` header if present, keeping total wall time
     (including retries) under 120s per the same SOP line; map `429` specifically to
     `code="rate_limited", retryable=True` instead of falling into the generic `upstream_error` branch.

### Suggestions

1. `docs/tickets/PRD-21279.md` § Data & API contract lists `yeastar_list_extensions(limit=50, cursor=None,
   sort_by=None, order_by=None)` and `yeastar_list_trunks(limit=50, cursor=None, sort_by=None,
   order_by=None)`, but the implemented signatures (`src/yeastar_mcp/tools/extensions.py:27`,
   `src/yeastar_mcp/tools/trunks.py:28`) only take `limit`/`cursor` — `sort_by`/`order_by` were dropped.
   No AC requires sort control on these two tools, so this isn't blocking, but § Self-test → "Changes made
   vs. design" says "None", which isn't quite accurate for this one. Worth a one-line note for whoever
   picks this up next (add the params, or correct the design table — either is fine).
2. `src/yeastar_mcp/api_client.py:106` (`get_token`) does `return body["access_token"]` after only
   checking `errcode == 0`. If the vendor ever returns a malformed success body without that key, this
   raises an uncaught `KeyError` instead of the SOP §4.1 "never raise, always return the structured
   envelope" contract — it would surface as an MCP protocol-level error rather than the connector's own
   `{"error": {...}}` shape. Low-probability (vendor contract violation) and not currently exercised by
   any test, but cheap to harden with `body.get("access_token")` plus an explicit `upstream_error` if it's
   missing.

### Fixes

_(none yet — this is the first review round)_
