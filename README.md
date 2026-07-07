# LangGraph SharePoint Audit Agent

Multi-agent document audit workflow built with LangGraph, deployed to two
parallel targets from the same container image: Azure Container Instances
(ACI) + Application Gateway via Terraform, and an Azure AI Foundry Hosted
Agent via `azd`.

## Architecture

Three-agent Corrective-RAG pattern with a bounded retry loop:

```mermaid
flowchart TD

    START([START])

    A1([Agent 1<br/>search<br/>Search SharePoint via CSOM/PnP .NET])
    A4([Agent 4<br/>fabric-context<br/>Query Fabric MCP for read-only context])
    A2([Agent 2<br/>evaluate<br/>Sufficiency evaluation])
    DEC{Sufficient?<br/>OR max_iter reached?}
    LOOP([Agent 1 + Agent 4<br/>loop])
    A3([Agent 3<br/>finalize<br/>Systematize + verify sources])

    END([END])

    START --> A1 --> A2
    START --> A4 --> A2
    A2 --> DEC
    DEC -->|no| LOOP --> A1
    LOOP --> A4
    DEC -->|yes| A3 --> END

```

## Key design decisions

- **State schema**: `app/schemas/state.py` — `AuditState` TypedDict + Pydantic
  `SufficiencyVerdict` for Agent 2's structured output (no free-text parsing).
- **Loop guard**: `iteration` counter + `MAX_ITERATIONS`, escalates to Agent 3
  with a `partial_evidence` flag instead of looping forever.
- **Audit trail**: every Agent 2 verdict is appended to `verdict_history` in
  state — required for EU AI Act Annex III traceability.
- **SharePoint access**: Agent 1 does NOT call SharePoint directly from Python.
  The default backend is `sharepoint-csom-service/`, a C# Azure Function using
  PnP Core SDK's search API with Managed Identity auth. A second,
  config-selectable backend (`SHAREPOINT_TOOL_BACKEND=python`) targets an
  unimplemented .NET CSOM/PnP Framework sidecar, kept as an "explore" option.
  See `app/tools/sharepoint_tool.py` for the routing logic and
  `sharepoint-csom-service/README.md` for the Function's own docs.
- **Fabric MCP context (Agent 4)**: unlike Agents 1-3 (fixed deterministic
  function calls), Agent 4 is a real LLM tool-calling step — it connects to
  Microsoft Fabric's remote MCP server (`langchain-mcp-adapters`,
  Managed-Identity-authenticated) for additional read-only context, running
  in parallel with Agent 1 on every retry-loop iteration. Restricted to a
  fixed read-only tool allowlist (no create/update/delete/role operations)
  as a deliberate compliance boundary — see `app/nodes/agent4_fabric_context.py`.
- **Hosting adapter**: `app/main.py`'s `_serve()` tries to import
  `langchain_azure_ai.agents.hosting`; if present, it serves via
  `AuditResponsesHostServer` (`app/responses_adapter.py`), a `ResponsesHostServer`
  subclass that overrides schema validation and `handle_create` to drive
  `AuditState` (which has no `messages` field) instead of the chat-shaped state
  the base class expects. If the azure hosting extra isn't installed, it falls
  back to a minimal local FastAPI app (`/invoke`, `/health`). The same image and
  the same code path serve both the ACI and Foundry deploy targets — it's the
  `FOUNDRY_PROJECT_ENDPOINT` env var at runtime, not which package is
  installed, that distinguishes them (see `app/graph.py`'s `_build_llm()`).
- **Checkpointer**: `app/checkpointer.py`'s `build_checkpointer()` branches on
  `FOUNDRY_PROJECT_ENDPOINT` — `AsyncPostgresSaver` against the private-VNet
  Postgres Terraform provisions for the ACI path (durable), or in-memory
  `MemorySaver` for the Foundry path, since Foundry's managed runtime can't
  reach that private-VNet-only Postgres (non-durable; see Open items below).

## Project layout

```
langgraph-sharepoint-demo/
├── app/
│   ├── main.py                  # Entrypoint — Foundry Responses host or local FastAPI fallback
│   ├── graph.py                 # StateGraph assembly, routing, LLM selection
│   ├── checkpointer.py          # build_checkpointer() — Postgres (ACI) vs MemorySaver (Foundry)
│   ├── responses_adapter.py     # AuditState <-> Foundry Responses protocol mapping
│   ├── schemas/
│   │   └── state.py             # AuditState, SufficiencyVerdict, enums
│   ├── nodes/
│   │   ├── agent1_search.py
│   │   ├── agent2_evaluate.py
│   │   └── agent3_finalize.py
│   └── tools/
│       └── sharepoint_tool.py   # Stub — calls out to .NET CSOM/PnP service
├── tests/
│   ├── test_graph_routing.py
│   └── test_state_schema.py
├── docker/
│   └── Dockerfile
├── .github/workflows/
│   └── build-and-push.yml       # ACR build placeholder
├── .env.example
├── pyproject.toml
└── README.md
```

## Local development

```bash
pip install -e ".[dev]"
cp .env.example .env  # fill in Azure OpenAI + SharePoint service endpoint
python -m app.main
```

`pip install -e ".[dev]"` does not pull in the `azure` extra, so this runs the
local FastAPI fallback (`/invoke`, `/health`) rather than the Responses
protocol — test it with:

```bash
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"task": "Audit retention policy docs for case #4471"}'
```

To test the real Responses protocol locally instead, install the `azure`
extra (`pip install -e ".[azure]"`) — see `foundry/README.md`'s "Local test"
section for the corresponding `curl` example against `/responses`.

## Deployment path

1. **Azure Container Instances + Application Gateway** (current stage) — all
   infrastructure is provisioned via Terraform (`terraform/`, see
   `terraform/README.md`). The container image is built and pushed to ACR by
   `.github/workflows/build-and-push.yml`; Terraform then deploys it into an
   ACI container group fronted by an Application Gateway (TLS termination,
   public ingress), with a private-VNet Postgres-backed checkpointer (no
   public endpoint) and secrets in Key Vault. A jumpbox VM in the same VNet
   is the only way to reach Postgres directly (see below).
2. **Azure AI Foundry Hosted Agent** (second, parallel deploy target,
   currently preview) — same container image as the ACI path above; Foundry
   injects `FOUNDRY_PROJECT_ENDPOINT`/`FOUNDRY_MODEL_NAME` at runtime, which
   `app/graph.py`'s `_build_llm()` and `app/checkpointer.py`'s
   `build_checkpointer()` both branch on. Deploy via `azd` — see
   `foundry/README.md`. This path uses `MemorySaver` (non-durable) since
   Foundry's runtime can't reach the ACI path's private-VNet Postgres.

## Connecting to Postgres (jumpbox tunnel)

Postgres has no public endpoint — it's only reachable from inside the VNet
(the ACI container, or the jumpbox VM). To run `psql`, a migration, or any
other admin task from your local machine, open an SSH tunnel through the
jumpbox first:

```bash
# Get the jumpbox public IP and Postgres FQDN from Terraform outputs:
cd terraform/environments/dev
terraform output -raw jumpbox_public_ip
terraform output -raw postgres_fqdn

# Open a local port-forward through the jumpbox (leave this running):
ssh -L 5432:<postgres_fqdn>:5432 azureuser@<jumpbox_public_ip>

# In another terminal, connect through the tunnel:
psql "host=localhost port=5432 dbname=langgraph_checkpoints user=auditagent sslmode=require"
```

The jumpbox only accepts SSH (port 22) from the IP set in `local_ip` — see
`terraform/README.md`. No other inbound path to Postgres exists.

## Open items / TODO

- [ ] Scaffold the .NET CSOM/PnP Framework sidecar service that Agent 1 calls.
- [ ] Add `requires_human_review` as an explicit graph branch (interrupt) once
      the human-in-the-loop reviewer flow is defined.
- [ ] Wrap SharePoint tool as an MCP server for the future Foundry Toolbox
      migration.
- [ ] Wire human-in-the-loop (`interrupt()`) once the `requires_human_review`
      graph branch exists — the Responses protocol already supports resuming
      via `function_call_output`/`mcp_approval_response`.
- [ ] Wire a Cosmos DB checkpointer for the Foundry Hosted Agent path
      (currently `MemorySaver`, non-durable — Postgres isn't reachable from
      Foundry's runtime since it's private-VNet-only).
- [ ] Verify `READ_ONLY_TOOL_NAMES` in `app/nodes/agent4_fabric_context.py`
      against a live Fabric MCP server. It was built from Microsoft's
      published tool names but hasn't been checked against a real server; if
      the real server namespaces/prefixes tool names differently,
      `agent4_fabric_context` will silently return an empty `fabric_context`
      on every run (no error, since the graceful-degradation only catches
      exceptions, not "zero tools matched"). Also still needs verification
      against a real tenant: the Managed Identity's Fabric API permission
      grant is a manual prerequisite that isn't yet provisioned/verified.
