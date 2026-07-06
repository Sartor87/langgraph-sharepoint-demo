# Azure AI Foundry Hosted Agent Integration — Design

Date: 2026-07-06
Status: Approved (pending spec self-review)

## Context

`README.md`'s Deployment path item 2 has always named Azure AI Foundry Hosted
Agent as a future migration target, and `app/main.py` already has a
try/except fallback that attempts to import a hosting adapter. That adapter
is broken: it imports `azure.ai.agentserver.langgraph.from_langgraph`, which
is not part of the real `langchain-azure-ai[hosting]` package (already
correctly declared in `pyproject.toml`'s `azure` extra). The real package
exposes `langchain_azure_ai.agents.hosting.ResponsesHostServer` /
`InvocationsHostServer`, per Microsoft's own documentation (user-provided).
This spec makes that hosting adapter real, and adds the `azd`-based deploy
flow for Foundry Hosted Agent as a second, parallel deployment target
alongside the ACI + Application Gateway path built via Terraform
(`docs/superpowers/specs/2026-07-06-terraform-iac-design.md`).

## Scope

In scope:
- Fix `app/main.py`'s hosting adapter to use the real
  `langchain_azure_ai.agents.hosting.ResponsesHostServer`, subclassed to
  handle `AuditState` (which has no `messages` field, unlike the default
  chat-shaped graphs the package expects).
- Branch `app/graph.py`'s `_build_llm()` on `FOUNDRY_PROJECT_ENDPOINT`
  presence, so the same container image builds the right LLM client for
  either target.
- Add a durable checkpointer for the ACI path (`AsyncPostgresSaver`,
  `app/checkpointer.py`), replacing `MemorySaver`, against the private-VNet
  Postgres instance the Terraform IaC already provisions. The Foundry path
  keeps `MemorySaver` (Foundry's runtime can't reach a private-VNet-only
  Postgres — see "Checkpointer" below).
- Add `DB_USER` to the ACI container's env vars (small Terraform addition —
  currently missing, flagged in the Terraform work's final review).
- Change `docker/Dockerfile`'s `CMD` to run `app/main.py` as a script
  instead of importing `app.main:app` via uvicorn (the hosting servers
  self-manage their run loop via `.run()`, not an ASGI-importable app).
- Scaffold `foundry/` (azd-generated `agent.yaml` + supporting files,
  customized to point at this repo's existing app/Dockerfile).
- Update `README.md`'s Foundry Hosted Agent section with real commands.

Out of scope (explicitly deferred):
- SharePoint MCP microservice (separate task, per earlier decision).
- Human-in-the-loop / `interrupt()` wiring for `requires_human_review` —
  kept as an explicit TODO (the graph branch for it doesn't exist yet).
- Real token-level streaming of intermediate agent output — `stream=true`
  gets one full delta + `response.completed`, not incremental generation.
- Running `azd provision` / `azd deploy` against a real Foundry project —
  manual, user-run steps (billed, cloud-affecting, requires the Foundry
  Project Manager role).
- Migrating the ACI path off Terraform, or retiring either deployment
  target — both stay live in parallel.

## Architecture

```
app/
├── graph.py                 # _build_llm() branches on FOUNDRY_PROJECT_ENDPOINT:
│                             #   present  -> AIProjectClient + DefaultAzureCredential
│                             #               bearer-token provider -> ChatOpenAI
│                             #               pointed at the Foundry project's
│                             #               OpenAI-compatible base_url
│                             #   absent   -> existing AzureChatOpenAI (ACI path,
│                             #               unchanged)
├── checkpointer.py           # NEW: build_checkpointer() branches on
│                             #   FOUNDRY_PROJECT_ENDPOINT same as _build_llm():
│                             #   absent -> AsyncPostgresSaver (DB_HOST/DB_NAME/
│                             #     DB_USER/DB_PASSWORD, sslmode=require, .setup()
│                             #     once at startup)
│                             #   present -> MemorySaver (Foundry can't reach the
│                             #     private-VNet Postgres; TODO: Cosmos DB later)
└── main.py                  # Rewritten: real ResponsesHostServer subclass for
                              #   AuditState (see "Hosting adapter behavior" below).
                              #   Falls back to the existing local FastAPI /invoke
                              #   endpoint when the azure extra isn't installed
                              #   (local dev without Foundry/ACI extras, unchanged).

docker/Dockerfile             # CMD: `uvicorn app.main:app ...` -> run app/main.py
                              #   directly as a script. Same image serves both
                              #   deploy targets; behavior is env-var-driven.

foundry/                      # NEW
├── agent.yaml                # azd agent definition — scaffolded via `azd ai
│                             #   agent init`, then customized (see below)
└── README.md                 # Foundry-specific setup/deploy notes

pyproject.toml                # azure extra gains: langgraph-checkpoint-postgres,
                              #   psycopg[binary,pool]

terraform/environments/dev/main.tf   # add DB_USER = "auditagent" to
                                      #   module.audit_agent's environment_variables
```

Both deploy targets run the *same* container image. Nothing in the image
knows at build time which target it's running on — `FOUNDRY_PROJECT_ENDPOINT`
being set (Foundry-injected) vs. unset (ACI, where Terraform sets
`AZURE_OPENAI_ENDPOINT` instead) is the only branch point, checked in exactly
two places: `_build_llm()` (which LLM client) and `build_checkpointer()`
(which checkpointer). The Responses hosting adapter itself runs identically
regardless of target — Foundry talks to it over its managed ingress, ACI
talks to it over the Application Gateway.

## Hosting adapter behavior (Responses protocol, custom `AuditState`)

- **Input**: Responses `input` (a plain string, or the last user message's
  text if `input` is a list of message-like items) becomes
  `initial_state(task=<text>)` (reusing `app/graph.py`'s existing
  `initial_state` function unchanged).
- **Thread continuity**: `previous_response_id` (or a `conversation` id, if
  present) maps to the LangGraph `thread_id` used in the checkpointer's
  `config`, so a follow-up request resumes accumulated state instead of
  starting a fresh audit run — this only works because of the
  `AsyncPostgresSaver` checkpointer this spec also adds.
- **Output**: response text is built from `final_report`. If
  `partial_evidence` is `true`, the text is prefixed noting the result is
  partial (iteration budget was exhausted before Agent 2 returned
  "sufficient"). `source_verification` and `verdict_history` are appended as
  a formatted trailing section of the same output text — no custom Responses
  output-item schema is assumed; this is the simplest mapping that doesn't
  require reverse-engineering undocumented API surface.
- **Streaming**: `stream=true` emits one full delta followed by
  `response.completed`. This project's graph is a bounded multi-agent batch
  workflow (search → evaluate → finalize, with a bounded retry loop), not a
  token-by-token chat completion — true incremental streaming isn't a
  meaningful concept here, so it's not built.
- **Human-in-the-loop**: explicitly kept as an open TODO in this spec (not
  silently dropped) — seeded into the Terraform/README "Open items" list.
  `interrupt()`/`requires_human_review` wiring depends on a graph branch that
  doesn't exist yet; the Responses protocol's `mcp_approval_request`/
  `function_call_output` resume mechanism becomes relevant once it does.
- **Implementation-time discovery required**: the exact override surface
  (`build_input`, `handle_create`, and whether a separate output-extraction
  hook exists) isn't fully specified in the documentation available for this
  design — the first implementation task must inspect the installed
  `langchain_azure_ai.agents.hosting` package source to confirm real method
  names/signatures before writing the subclass. The behavior contract above
  is fixed; only the exact hook names are a discovery item.

## Checkpointer

Postgres is private-VNet-only (delegated subnet, `public_network_access_enabled
= false`, reachable only from inside the VNet or via the jumpbox tunnel — see
the Terraform IaC's most recent revision). Foundry Hosted Agent's runtime is
*not* inside that VNet and has no path to reach it. The two deploy targets
therefore get **different checkpointers**, branching on the same
`FOUNDRY_PROJECT_ENDPOINT` env var as `_build_llm()`:

- **ACI path** (`FOUNDRY_PROJECT_ENDPOINT` unset): `app/checkpointer.py`'s
  `build_checkpointer()` returns an `AsyncPostgresSaver`, reading `DB_HOST`,
  `DB_NAME`, `DB_USER`, `DB_PASSWORD` from the environment (all but `DB_USER`
  are already set by Terraform's `container-group` module instantiation in
  `environments/dev/main.tf`; `DB_USER` is a one-line addition this spec
  makes, value `"auditagent"`, matching the hardcoded `administrator_login`
  in `terraform/modules/postgres/main.tf`). Builds a connection string with
  `sslmode=require` (mandatory for Azure Postgres Flexible Server). Runs
  `.setup()` (idempotent schema migration) once at process startup, before
  the hosting server starts serving requests.
  - **Known integration risk, flagged for implementation, not resolved
    here**: `AsyncPostgresSaver`'s connection-pool lifecycle interacting with
    the hosting server's own blocking `.run()` call is a real wrinkle —
    whether the pool can be constructed once and reused across the "run
    setup, then start serving" boundary, or needs to be opened lazily inside
    whatever event loop `.run()` ends up using, depends on the exact
    installed version of `langgraph-checkpoint-postgres`. The implementation
    task must verify this against the real package rather than assume a
    specific pattern.
- **Foundry path** (`FOUNDRY_PROJECT_ENDPOINT` set): `build_checkpointer()`
  returns `MemorySaver()` — not production-durable (state doesn't survive a
  restart), but unblocks this integration without reopening Postgres to the
  public internet. Tracked as an explicit TODO (README "Open items"): wire a
  Cosmos DB checkpointer for the Foundry path specifically, since Cosmos DB
  (unlike Postgres Flexible Server here) doesn't need VNet delegation to stay
  reachable from Foundry's managed runtime.

## azd scaffold and deployment

The documentation available for this design shows `azd ai agent init -m
<github-manifest-url>` scaffolding a *new* folder from a remote sample
manifest — it does not show the `agent.yaml` schema for wiring an *existing*
app into azd. Rather than hand-authoring a guessed schema (which would
violate this project's "no fabricated/placeholder content" standard), the
first azd-related implementation task runs the real scaffold tooling
locally, inspects what it generates, and then customizes those generated
files to point at this repo's existing `app/`, `docker/Dockerfile`, and a
real Foundry project — adapting the canonical scaffold rather than
reverse-engineering it from partial docs.

**Testing order** (each step gates the next):
1. `python -m app.main` locally, `FOUNDRY_PROJECT_ENDPOINT` unset — confirms
   the ACI/local-fallback path still works unchanged.
2. `python -m app.main` locally, `FOUNDRY_PROJECT_ENDPOINT` /
   `FOUNDRY_MODEL_NAME` set against a real dev Foundry project — hit
   `/responses` with the docs' curl example, confirm `final_report` appears
   in the output text.
3. `azd ai agent run --local` — same container, azd-managed local run.
4. `azd provision` / `azd deploy` — **manual, user-run steps.** These are
   real, billed, cloud-affecting actions requiring the Foundry Project
   Manager role on the target project. Not automated by this plan, same
   treatment as `terraform apply` in the earlier IaC work.

## Documentation

- `README.md`'s Deployment path item 2 (currently a one-liner) expands into
  a short "Azure AI Foundry Hosted Agent" subsection: what's needed
  (Foundry project, model deployment, `azd` CLI + extension), the local test
  commands from "Testing order" above, and a pointer to `foundry/README.md`
  for the full walkthrough.
- `foundry/README.md`: `azd ai agent init`/`provision`/`deploy` commands,
  required env vars (`FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL_NAME`,
  `APPLICATIONINSIGHTS_CONNECTION_STRING` — all Foundry-injected at runtime,
  not set by us), and the shared-Postgres note from above.
- `README.md`'s "Open items / TODO" gains two items: "Wire human-in-the-loop
  (`interrupt()`) once the `requires_human_review` graph branch exists —
  Responses protocol already supports resuming via
  `function_call_output`/`mcp_approval_response`" and "Wire a Cosmos DB
  checkpointer for the Foundry Hosted Agent path (currently `MemorySaver`,
  non-durable — Postgres isn't reachable from Foundry's runtime since it's
  private-VNet-only)."

## Open questions (carried into implementation, not blocking this spec)

- None — the Postgres-reachability question this section originally raised
  is resolved above (Checkpointer section): Foundry gets `MemorySaver`, ACI
  keeps `AsyncPostgresSaver`, Postgres stays private-VNet-only. A Cosmos DB
  checkpointer for the Foundry path is tracked as a README TODO, not part of
  this spec.
