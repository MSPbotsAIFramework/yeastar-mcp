# yeastar-mcp

MCP server for Yeastar P-Series Appliance-Edition PBX, for the MSPbots Agent platform.

Read-only connector: list phone extensions, trunks, call-routing configuration
(inbound routes, outbound routes, IVRs), and call detail records (CDR) on one
on-prem Yeastar P-Series Appliance-Edition PBX per set of credentials.

- Transport: MCP Streamable HTTP (`POST /mcp`), stateless.
- Stack: Python 3.12, FastMCP, httpx, uvicorn.
- License: Apache-2.0.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

Every `/mcp` request must carry all three headers below (one PBX appliance's
credentials per request). Missing any of them returns `401` and the response
body names exactly which ones are missing; the PBX is never called in that
case.

| Header | Required | Meaning |
|---|---|---|
| `X-Yeastar-Base-Url` | Yes | The appliance's API base URL, e.g. `https://192.168.5.150:8088`. HTTPS on port 8088 is the vendor default. |
| `X-Yeastar-Client-Id` | Yes | OAuth client ID. On the PBX web portal: **Integrations → API**. |
| `X-Yeastar-Client-Secret` | Yes | OAuth client secret from the same portal screen. Treated as a secret; never logged. |

Prerequisites on the PBX itself (not configurable from this connector):

- Firmware ≥ `37.7.0.16`, models P550 / P560 / P570 only.
- The "API feature" must be enabled on the appliance (PBX web portal → System → API).
- TLS certificate verification is **on by default**. Most appliances ship a
  self-signed certificate until an admin installs a trusted one; a TLS
  failure surfaces as `upstream_error` rather than silently skipping
  verification. To avoid this, either install a trusted certificate on the
  appliance, or point `X-Yeastar-Base-Url` at the appliance's HTTP port
  instead of HTTPS (the admin's choice, not this connector's).

## Tools

All 6 tools are read-only (`readOnlyHint: true`). List tools take `limit`
(default 50, max 200) and an opaque `cursor` for the next page; the response
includes `has_more` and, when true, `next_cursor`.

| Tool | Upstream endpoint | Returns |
|---|---|---|
| `yeastar_list_extensions` | `extension/list` | `id, number, caller_id_name, email_addr, mobile_number, presence_status, role_name` |
| `yeastar_list_trunks` | `trunk/list` | `id, name, type, status`, plus `host_port`/`def_outbound_cid` (peer trunks) or `username` (account trunks) |
| `yeastar_list_inbound_routes` | `inbound_route/list` | `id, pos, name, default_destination, business_hours_destination, outside_business_hours_destination, holidays_hours_destination` |
| `yeastar_list_outbound_routes` | `outbound_route/list` | upstream route fields as returned (trunk, pattern) |
| `yeastar_list_ivrs` | `ivr/list` | upstream IVR list entries as returned |
| `yeastar_list_cdr` | `cdr/list` | `time, call_from, call_to, duration, talk_duration, disposition, call_type, src_addr`, sorted newest-first by default |

`yeastar_list_cdr` has no server-side time-range filter on the upstream API:
narrow a window by paging through the time-sorted results and stopping once
you read past it.

Not in scope for v1 (see `docs/tickets/PRD-21279.md` for why): ring groups,
queues, saved report definitions (`myreport/list`), any write/configuration
operation, and real-time call control.

## Errors

Every tool returns a JSON string. On failure:

```json
{"error": {"code": "upstream_error", "message": "...", "retryable": true}}
```

`code` is one of `not_configured | unauthorized | not_found | invalid_argument | rate_limited | upstream_error`.
An empty result list is not an error (`items: [], has_more: false`).

## Local development

```bash
uv sync
uv run pytest
uv run python -m yeastar_mcp   # listens on 0.0.0.0:8080
```

Manual smoke test against a real or mocked appliance:

```bash
curl -s -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'X-Yeastar-Base-Url: https://192.168.5.150:8088' \
  -H 'X-Yeastar-Client-Id: <client-id>' \
  -H 'X-Yeastar-Client-Secret: <client-secret>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Credentials for local testing go in shell environment variables or an
untracked local file — never hardcoded, never a fallback when a header is
missing (see Authentication headers above).
