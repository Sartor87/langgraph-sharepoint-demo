# ADR-0008: Agent 4 fails open — a Fabric MCP error never aborts the audit run

## Status

Accepted

## Context

Agent 4 fans in with Agent 1 into Agent 2 within the same LangGraph superstep (`START` → `{agent1, agent4}` → `agent2`). LangGraph aborts the entire graph run if any node in a superstep raises an unhandled exception. Agent 4's first implementation had no error handling around the Fabric MCP interaction (`client.get_tools()`, tool execution, LLM calls) — a final whole-branch review caught that any Fabric network error, auth failure (the Managed Identity's Fabric permission grant is a manual prerequisite that may not be provisioned), or MCP protocol error would silently take down the primary SharePoint audit, which Agent 4 is only supposed to *supplement*.

## Decision

`agent4_fabric_context()`'s entire body is wrapped in a broad `except Exception`. Any failure degrades to a `fabric_context` entry carrying the error (`{"summary": "Fabric context unavailable: ...", "error": str(exc)}`) instead of propagating. This is deliberately broad — network, auth, and protocol errors are all real, expected possibilities for an external dependency this project doesn't operate, and none of them should be allowed to fail the core workflow.

## Consequences

- Fabric being completely unreachable (e.g. the permission grant never happens) degrades gracefully to "no Fabric context, audit proceeds" rather than "audit stops working" — the correct trade-off for a supplementary data source.
- The degraded state is visible in the audit trail (`error` key in the stored `fabric_context` entry), not silently swallowed — a future reader of the audit trail can tell Fabric context was attempted and failed, versus never attempted.
- This does not fix the underlying reachability problem (unverified tool allowlist, unprovisioned permission grant — see ADR-0006) — it only ensures those gaps degrade rather than break the system.
