# Fabric MCP Context Agent — Design

Date: 2026-07-07
Status: Approved (pending spec self-review)

Note: `docs/superpowers/` is gitignored in this repo (per the user's own
`.gitignore` policy) — this file stays on disk as the design record but is
not committed to git, same treatment as the SharePoint Azure Function spec
written earlier the same day.

## Context

This project is a LangGraph SharePoint document audit workflow: three fixed,
deterministic agents (search → evaluate → finalize) with a bounded retry
loop. Microsoft Fabric's remote MCP server
(`https://api.fabric.microsoft.com/v1/mcp/core`, OAuth 2.0/Entra ID,
~27 tools spanning workspaces/items/folders/capacities/permissions) is a
new, unrelated data platform this project has no existing connection to.
This spec adds a fourth graph node that queries Fabric via that MCP server
as an LLM tool-calling step, to pull in additional context alongside each
SharePoint search iteration — not to store audit output, not as a
standalone/unrelated PoC.

## Scope

In scope:
- New graph node `app/nodes/agent4_fabric_context.py`: an LLM tool-calling
  step (unlike this project's other three agents, which are fixed
  deterministic function calls) using `langchain-mcp-adapters`'
  `MultiServerMCPClient` to connect to the Fabric MCP server, filtered to a
  fixed **read-only tool allowlist**.
- `AuditState` gains `fabric_context: list[dict]` (append-only reducer,
  same pattern as `verdict_history`).
- Graph wiring (`app/graph.py`): the new node runs **in parallel with Agent
  1 on every iteration of the retry loop** (not just once at the start),
  using the same `task`/`query` state Agent 1 already uses — no separate
  Fabric-specific query input. Both feed into Agent 2's evaluation step.
- Auth: **Managed Identity** (same mechanism already used elsewhere in this
  project for other Azure resources) acquiring a token for scope
  `https://api.fabric.microsoft.com/.default`, not the interactive
  browser/device-code flow the Fabric MCP docs describe for VS Code (this
  agent runs headless, on ACI/Foundry).
- Bounded tool-calling: one LLM call with tools bound → execute any
  requested tool calls → one follow-up LLM call to synthesize a short
  context summary → append to `fabric_context`. Not an open-ended
  ReAct-style loop — consistent with this project's existing
  `MAX_ITERATIONS`-bounded design philosophy elsewhere in the graph.

Out of scope (explicitly deferred):
- Any mutating Fabric tool (`create_workspace`, `delete_item`,
  `add_workspace_role`, etc.) — the allowlist is read-only only. This is a
  deliberate compliance/safety boundary for an automated audit-context step
  (this project already tracks EU AI Act Annex III traceability
  requirements elsewhere — an audit tool silently able to mutate a data
  platform's workspaces/permissions would undermine that).
- `get_operation_state`/`get_operation_result` — these exist for
  long-running mutating operations, not relevant to read-only queries.
- Microsoft Graph MCP Server (mentioned in the Fabric docs as an optional
  add-on for resolving email addresses to user principal IDs) — not needed,
  since the read-only allowlist has no role/permission operations that
  would need principal-ID resolution.
- Provisioning the Managed Identity's Fabric API permission grant — a
  manual, human-run prerequisite (Entra/Fabric admin portal), same
  treatment as the SharePoint Managed Identity's `Sites.Selected` grant in
  the sibling spec written the same day. Not automated by this spec's
  implementation.
- Any Terraform/infrastructure changes — this spec is app-code only.

## Architecture

```
app/nodes/agent4_fabric_context.py   # NEW
app/schemas/state.py                 # MODIFY: AuditState += fabric_context
app/graph.py                         # MODIFY: graph wiring
```

Graph flow (new parallel branch on every retry-loop iteration, not just
once):

```
START --> {Agent1 search, Agent4 fabric-context} --> Agent2 evaluate --> DEC
DEC -->|no|  {Agent1 (loop), Agent4 (loop)} --> Agent2
DEC -->|yes| Agent3 finalize --> END
```

LangGraph's native fan-out/fan-in handles this: two edges from the same
source node(s) into two parallel targets, both of which edge into the same
next node (`agent2_evaluate`) — LangGraph waits for both branches to
complete within the same superstep. `sharepoint_docs` (Agent 1's output)
and `fabric_context` (Agent 4's output) are different `AuditState` keys with
independent reducers, so the two nodes' concurrent writes don't conflict.

## MCP client, auth, and tool filtering

- `MultiServerMCPClient` configured with one entry: `"fabric": {"url":
  "https://api.fabric.microsoft.com/v1/mcp/core", "transport":
  "streamable_http", ...}`.
- **Auth — implementation-time discovery item**: a Managed-Identity-acquired
  bearer token (via `azure.identity.aio.ManagedIdentityCredential`, scope
  `https://api.fabric.microsoft.com/.default`) expires (~1 hour) and must be
  refreshed, not supplied as a single static header. Whether
  `MultiServerMCPClient`/its `streamable_http` transport supports a
  dynamic, per-request auth callback (vs. only a fixed headers dict at
  construction time) must be verified against the actually-installed
  `langchain-mcp-adapters` version before implementation — same "verify
  against the real package" discipline this project applied to
  `langchain_azure_ai.agents.hosting` and PnP Core SDK earlier. The
  behavior contract is fixed regardless of the exact mechanism: tokens must
  be refreshed as needed, never allowed to silently expire mid-session.
- **Tool filtering**: after `await client.get_tools()` returns all ~27
  Fabric tools as LangChain tool objects, filter by name to the read-only
  allowlist: `search_catalog`, `list_workspaces`, `get_workspace`,
  `list_items`, `get_item`, `get_item_definition`, `list_folders`,
  `get_folder`, `list_capacities`, `get_knowledge`.
- **Bounded tool-calling loop**: `llm.bind_tools(filtered_tools)` → one
  invocation with a prompt built from `state["task"]`/`state["query"]` → if
  the response has tool calls, execute all of them (async) and feed the
  results back as `ToolMessage`s → one more LLM invocation to synthesize a
  short summary of what was found → that summary (plus raw tool results, if
  useful for the audit trail) becomes the entry appended to
  `fabric_context`.

## State schema

`app/schemas/state.py`'s `AuditState` gains:

```python
fabric_context: Annotated[list[dict], _append]
```

(reusing the existing `_append` reducer already defined for
`verdict_history`).

## Testing

No real Fabric tenant/Managed Identity is available for full integration
testing. Test strategy:
- Pure/mockable pieces get real unit tests: the read-only tool-name filter
  function, and the context-summary formatting logic.
- The tool-calling loop itself is tested with a mocked
  `MultiServerMCPClient` / stub tool objects returning canned data,
  asserting the loop correctly executes requested tool calls and produces
  a summary — same pattern already used in this project for testing
  `AuditResponsesHostServer.handle_create` with an `AsyncMock` graph.
- No live network call to `https://api.fabric.microsoft.com` in any
  automated test.

## Documentation

- `README.md`'s "Key design decisions" gains a bullet describing Agent 4 /
  the Fabric context node: what it does, why it's read-only-restricted, and
  that it runs in parallel with Agent 1 every iteration.
- If the auth-callback discovery item can't be resolved cleanly against the
  real `langchain-mcp-adapters` API, that becomes a README "Open items"
  entry rather than a blocked implementation — same escalation pattern used
  for open items elsewhere in this project.

## Open questions

None — all scope/design decisions (purpose, graph placement/timing,
read-only tool restriction, Managed Identity auth, langchain-mcp-adapters,
query source, bounded tool-calling) were confirmed with the user during
brainstorming.
