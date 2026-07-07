# Foundry Hosted Agent deployment

Second, parallel deploy target alongside the ACI + Terraform path
(`terraform/README.md`) — same container image, different runtime.

## Prerequisites

- An Azure AI Foundry project with a deployed chat model (e.g. `gpt-4.1`).
- `az login` (for `DefaultAzureCredential`).
- `azd` CLI with the AI agent extension: `azd ext install azure.ai.agents`.
- Docker running locally (azd builds the image from `docker/Dockerfile`).

## Local test

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_MODEL_NAME="gpt-4.1"
python -m app.main
```

In another terminal:

```bash
curl -sS -H "Content-Type: application/json" \
  -X POST http://localhost:8088/responses \
  -d '{"input":"Audit retention policy docs for case #4471","stream":false}'
```

## `agent.yaml`

`agent.yaml` in this directory is the `azd` agent manifest for this app,
adapted from the real `azd ai agent init` scaffold output (not hand-authored
from documentation — see `.superpowers/sdd/task-9-report.md` for the exact
scaffold run and raw generated output). It declares:

- `kind: hosted` and a `responses` v1 protocol, matching this app's
  `ResponsesHostServer` adapter (`app/main.py`).
- No `environment_variables` block — `FOUNDRY_PROJECT_ENDPOINT` and
  `FOUNDRY_MODEL_NAME` are injected automatically by the Foundry runtime and
  must not be set here.

**Gap discovered while adapting the scaffold**: the real `agent.yaml` schema
has no field for pointing at a Dockerfile or entrypoint — that wiring lives in
`azd`'s own `azure.yaml` project file (`services.<name>.docker.path`, per the
official azd project schema), which `azd ai agent init` generates alongside
`agent.yaml` when run inside a project directory. That `azure.yaml` (plus the
`infra/` Bicep it references) is intentionally not checked into this repo —
this repo's infra is Terraform (`terraform/`), and `azure.yaml`/`infra/` would
be scaffold-managed, environment-specific artifacts. Before running `azd
provision`/`azd deploy` for real, run `azd ai agent init` inside this
directory (or point its `-m`/`--src` flags here) to generate a local
`azure.yaml` whose service's `docker.path` you then repoint at
`../docker/Dockerfile` (this repo's real image, not a scaffold sample).

## Deploy (manual — real, billed Azure actions)

```bash
cd foundry
azd auth login
azd provision   # only if this is a brand-new Foundry project/model deployment
azd deploy
```

Requires the **Foundry Project Manager** role on the target project.

## Checkpointer note

This deploy target uses `MemorySaver` (non-durable) — Foundry's managed
runtime can't reach the private-VNet-only Postgres the ACI path uses. See
`docs/superpowers/specs/2026-07-06-foundry-hosted-agent-design.md` and
README.md's Open items (Cosmos DB checkpointer, tracked as future work).
