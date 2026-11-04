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

Round 1, must-fix 1 (`src/yeastar_mcp/api_client.py:82-87` retry/mapping) — fixed in `bae87ff`:

- `_request()` now runs in a bounded retry loop for HTTP `429` and `>= 500` responses: up to
  `MAX_RETRY_ATTEMPTS = 3` retries (4 attempts total, worst case), exponential backoff starting at
  `INITIAL_BACKOFF_SECONDS = 1.0` doubling each attempt (`BACKOFF_MULTIPLIER = 2.0`), honoring a numeric
  `Retry-After` response header when present (falls back to the exponential value for non-numeric headers
  such as an HTTP-date, since the vendor's exact format isn't documented). Total wall time across the
  initial attempt and all retries is capped at `MAX_TOTAL_WALL_TIME = 120.0` seconds per the SOP §14
  checklist line: before each sleep the remaining budget is computed from a `time.monotonic()` start
  mark, the sleep is clamped to that remaining budget, and once the budget is exhausted the loop stops
  retrying and raises immediately instead of sleeping past the 120s ceiling.
- Once retries are exhausted (or the budget runs out), a terminal `429` now raises
  `YeastarApiError(code="rate_limited", retryable=True)` instead of falling into the generic
  `upstream_error` branch — matching the SOP §4.2 vocabulary table exactly. A terminal `>= 500` still
  raises `upstream_error` with `retryable=True` (unchanged mapping, now reached only after retries are
  exhausted instead of on the first response). Other 4xx responses are still not retried and still raise
  `upstream_error`; `retryable` for that branch is now written as the literal `False` instead of the old
  `status_code >= 500` expression — same value, clearer that it's a deliberate "don't retry" result rather
  than leftover arithmetic from the 5xx branch above it.
- Retry attempt counts/backoff values are not configurable via environment — the vendor's actual rate-limit
  behavior isn't known yet (no real appliance account was available for this round either), so the
  constants were chosen to satisfy the SOP floor (bounded, exponential, Retry-After-aware, < 120s total)
  rather than tuned against observed vendor behavior. Noting this so whoever gets appliance access can
  revisit the constants if real `429`/`Retry-After` behavior turns out to need something different.
- Tests: new `tests/test_api_client.py` (6 cases, all respx-mocked, no real PBX) covering: `429` retried
  then succeeds; `429` exhausted maps to `rate_limited`/`retryable=True` after exactly
  `1 + MAX_RETRY_ATTEMPTS` attempts; `503` retried then succeeds; `5xx` exhausted maps to
  `upstream_error`/`retryable=True`; a numeric `Retry-After` header is honored over the default backoff
  value; a plain `404` is not retried and maps to `upstream_error`/`retryable=False`. `asyncio.sleep` is
  monkeypatched to a no-op so the suite doesn't actually wait out the backoff delays.
- Re-ran gates on the fixed code: `uv run pytest -q` → `23 passed` (17 pre-existing + 6 new); `uv run mypy
  src` → `Success: no issues found in 11 source files`. Also re-ran the manual smoke check from round 1
  (`uv run python -m yeastar_mcp`, `curl` with placeholder headers): `/health` → `200`; `tools/list` with no
  headers → `401` with the missing-header list; `tools/list` with placeholder headers → `200` with the
  same 6 read-only tools as round 1. CJK scan (`grep -rnP '[\x{4e00}-\x{9fff}]' src tests`) → no output —
  the first draft of this fix's own code comments quoted the SOP in Chinese and had to be rewritten in
  English before this round was done; caught by re-running the scan, not by writing it correctly the
  first time.
- Round 1's two "Suggestions" items (dropped `sort_by`/`order_by` params on two tools; `get_token` raising
  `KeyError` on a malformed success body) are unchanged — they were marked non-blocking in round 1 and are
  not part of this round's must-fix list, so per the review-rework rule only the must-fix item above was
  addressed.

## Round 2 · 2026-11-04 · reviewed 9180e3a (base f9e9cb6)

Verdict: approved

### Scope

`git diff 030854e...9180e3a` on `MSPbotsAIFramework/yeastar-mcp` (the round 1 must-fix fix; `docs/tickets/PRD-21279-review.md`,
`src/yeastar_mcp/api_client.py`, `tests/test_api_client.py` — 3 files, 230 insertions / 14 deletions). Base
re-checked: `origin/main` force-refetched, still at `f9e9cb6` (single-commit repo, nothing else merged since
round 1), so no re-sync was needed. Gates re-run independently on this host (a fresh host without `uv`
installed; installed `uv 0.13.7` via the official installer, then `uv sync`): `uv run pytest -q` → `23
passed`; `uv run mypy src` → `Success: no issues found in 11 source files` — both match the `[DEV]` stub and
the Round 1 Fixes note exactly. Full-repo CJK scan (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git
--exclude-dir=.venv .`) found no CJK under `src/` or `tests/` (confirms the dev's own `src tests`-scoped scan
from the Fixes note); it did surface the pre-existing Chinese quotations of the SOP text in this doc's own
Round 1 section (lines 20-21, 34-35) — see Suggestion 1 below, not a new must-fix since it predates this
round's diff. README and `Dockerfile` are untouched this round (already verified byte-identical / building in
round 1) so not re-checked.

### Findings

No new must-fix in this round's diff.

#### Round 1 must-fix verification

1. `src/yeastar_mcp/api_client.py:82-87` (original line numbers) retry/mapping — **confirmed fixed**. Read
   the full `_request()` implementation (now `api_client.py:96-144`): on HTTP `429` or `>= 500` it retries up
   to `MAX_RETRY_ATTEMPTS = 3` times (4 attempts total, worst case) with exponential backoff
   (`INITIAL_BACKOFF_SECONDS = 1.0`, `BACKOFF_MULTIPLIER = 2.0`), honors a numeric `Retry-After` header
   (falls back to backoff for non-numeric values such as an HTTP-date), and bounds total wall time at
   `MAX_TOTAL_WALL_TIME = 120.0`s via a `time.monotonic()` start mark with the sleep clamped to the
   remaining budget on every iteration. A terminal `429` (retries exhausted or budget used up) now raises
   `YeastarApiError(code="rate_limited", retryable=True)`, matching the SOP §4.2 vocabulary table exactly; a
   terminal `>= 500` keeps `upstream_error`/`retryable=True`; other `4xx` are unchanged (not retried,
   `upstream_error`/`retryable=False`). `tests/test_api_client.py` (6 new cases, `respx`-mocked,
   `asyncio.sleep` monkeypatched to a no-op) independently exercise: `429` retried then succeeds; `429`
   exhausted → `rate_limited`/`retryable=True` after exactly `1 + MAX_RETRY_ATTEMPTS` calls; `503` retried
   then succeeds; `5xx` exhausted → `upstream_error`/`retryable=True`; a numeric `Retry-After` header honored
   over the default backoff; a plain `404` not retried. Verified by reading the implementation and the tests
   line by line, and independently re-running the gates (see Scope) — numbers match the Fixes note exactly.

### Suggestions

1. `docs/tickets/PRD-21279-review.md:20-21,34-35` (Round 1 section, predates this round's diff) — quotes the
   SOP's original Chinese wording ("网络健壮性", "对 429 和 5xx 做有限次重试...") for citation precision. The
   MCP track's review-doc convention is English-only (`mcp-track.md` §4.3) and the repo-wide CJK scan
   (`mcp-track.md` §3.2 step 7) isn't scoped to exclude `docs/`. Low priority and not blocking this round:
   it's inside an already-superseded review round's text, not the connector's served surface (README, code,
   error messages — all clean), and carries no behavioral or acceptance risk. Flagging for whoever next
   touches this file; not bouncing this round over it.
2. Carried over from Round 1, still open and still non-blocking: dropped `sort_by`/`order_by` params on
   `yeastar_list_extensions`/`yeastar_list_trunks` vs. the design table in `docs/tickets/PRD-21279.md`;
   `get_token` (`api_client.py:146`) raising `KeyError` on a malformed success body instead of a structured
   `upstream_error`.

Status: frozen @ 9180e3a
