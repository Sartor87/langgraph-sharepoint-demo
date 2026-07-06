# Terraform IaC for langgraph-sharepoint-demo — Design

Date: 2026-07-06
Status: Approved (pending spec self-review)

## Context

The project currently has no infrastructure-as-code. Deployment is described in
`README.md` as manual `az acr build` / `az containerapp create`, and the only
automation is `.github/workflows/build-and-push.yml` (image build only, no
infra provisioning).

Goal: deploy all Azure resources for this project entirely through Terraform.

**Architecture pivot**: the README's stated target (Azure Container Apps →
Azure AI Foundry Hosted Agent) is replaced, for this IaC effort, with a
pattern mirrored from a working reference project (internal Terraform for an
ACI-based deployment with VNet, private Postgres, Key Vault, and an
Application Gateway front door). This spec documents the ACI-based target;
`README.md` will be updated to reflect it (see "README changes" below).

## Scope

In scope:
- All Azure resources needed to run the audit-agent container: networking,
  compute (ACI), Postgres (LangGraph checkpointer), Key Vault, ACR, App
  Gateway (TLS termination / public ingress), managed identity, jumpbox VM.
- Single environment (`dev`) now, module structure that supports adding
  `prod`/`staging` later without refactoring.
- Terraform state bootstrap (remote backend storage account).

Out of scope (explicitly deferred):
- CI/CD automation of `terraform plan`/`apply` (stays manual for now).
- Azure AI Foundry Hosted Agent target (README's future migration path,
  unaffected by this spec).
- The SharePoint MCP microservice itself (separate spec/task) — but the
  compute module is designed to be reused for it.
- Storage account / Azure Files volume (no persistent local file need in this
  stateless FastAPI + Postgres-checkpointer app).
- pgvector extension (no vector/embeddings search in the current
  keyword-search-via-CSOM architecture).

## Repo layout

```
terraform/
├── bootstrap/                     # one-time, local state, run manually first
│   └── main.tf                    # storage account + container for remote state
├── modules/
│   ├── resource-group/
│   ├── networking/                 # vnet + 4 subnets + NSGs + private DNS zone
│   ├── keyvault/                   # access-policy mode
│   ├── acr/
│   ├── postgres/                   # flexible server, public + firewall allowlist
│   ├── jumpbox/                    # ubuntu VM, SSH key auth
│   ├── app-gateway/                # Standard_v2, TLS termination
│   └── container-group/            # generic ACI module, reused for future MCP service
└── environments/
    └── dev/
        ├── main.tf
        ├── variables.tf
        ├── terraform.tfvars        # non-secret vars only
        └── backend.tf
```

Rationale: modular structure pays for itself immediately — the
`container-group` module will be instantiated a second time for the SharePoint
MCP microservice in a follow-up task, with no rework. `bootstrap/` solves the
chicken-and-egg problem of remote state (the storage account holding state
can't itself be described by that same state); it runs once, manually, with
local state.

## Resources per module

- **resource-group** — `rg-audit-agent-dev`, single location variable.
- **networking** — VNet `10.0.0.0/16` with 4 subnets:
  - `snet-aci` — delegated to `Microsoft.ContainerInstance/containerGroups`
  - `snet-postgres` — delegated to `Microsoft.DBforPostgreSQL/flexibleServers`
  - `snet-jumpbox` — plain subnet for the admin VM
  - `snet-appgw` — dedicated subnet for Application Gateway (no NSG attached —
    App Gateway's management traffic on ports 65200-65535 must reach it)
  - NSGs on aci/postgres/jumpbox subnets: deny-all-inbound by default, allow
    only what's needed (App Gateway → ACI on 80, jumpbox SSH from
    `var.local_ip`, Postgres from ACI subnet + jumpbox subnet + dev IP
    allowlist).
  - Private DNS zone `privatelink.postgres.database.azure.com` + VNet link
    (kept for future private-Postgres option even though Postgres itself is
    public+firewall in this iteration — see "Postgres access" below).
- **keyvault** — access-policy mode (not RBAC), matching the reference
  pattern: one policy for the Terraform caller (full secret permissions), one
  for the audit-agent managed identity (`Get` only). Secrets stored:
  `postgres-password`, `azure-openai-key`, `appinsights-connection-string`.
  Azure OpenAI uses key-based auth (matches the current `AzureChatOpenAI`
  usage in `app/graph.py`, which expects an API key) rather than a
  `Cognitive Services OpenAI User` role assignment — switching to
  managed-identity auth for Azure OpenAI is a separate, app-code-level
  change out of scope for this IaC spec.
- **acr** — Basic SKU, `admin_enabled = false`. `AcrPull` role assignment to
  the audit-agent user-assigned managed identity (no admin credentials used).
- **postgres** — Azure Database for PostgreSQL Flexible Server, **public
  network access enabled + firewall rule allowlisting `var.local_ip`** (see
  decision below), database `langgraph_checkpoints` for the
  `AsyncPostgresSaver` checkpointer. No pgvector extension.
- **jumpbox** — Ubuntu Linux VM in `snet-jumpbox`, public IP, SSH-key-only
  auth (no password auth), NSG allows port 22 only from `var.local_ip`. Kept
  for general admin/debug access to private subnets even though it is not
  strictly required for Postgres access in this iteration.
- **app-gateway** — Standard_v2 SKU, TLS termination with a self-signed
  certificate (base64 PFX passed as a sensitive variable — acceptable for
  `dev`; swap for a real cert when a prod environment is added), HTTP(80) →
  HTTPS(443) redirect, backend pool = ACI container group's private IP,
  health probe against `/health`.
- **container-group** — generic ACI module (params: name, image, cpu/memory,
  environment_variables, secure_environment_variables, subnet_id). One
  instance deployed now (`audit-agent`); the SharePoint MCP microservice will
  be a second instance of this same module in a later task.

## Identity / secrets flow

A single user-assigned managed identity (`id-audit-agent-dev`) is:
- Granted `AcrPull` on the ACR (image pull, no admin credentials).
- Granted a Key Vault access policy (`Get` on secrets).

**Known ACI limitation**: unlike Azure Container Apps, ACI has no native
runtime Key Vault reference for container secrets. Secrets are read from Key
Vault *at apply time* by Terraform (via `azurerm_key_vault_secret` data
sources) and injected into the container group's `secure_environment_variables`
block. This means secret values pass through the Terraform plan/state (state
must be treated as sensitive — the remote backend storage account should have
public access restricted and encryption at rest, which Azure Storage provides
by default). This is an accepted trade-off of the ACI-based architecture
chosen for this spec.

## Decisions made during review (deviations from the reference project)

1. **Postgres: public + firewall allowlist**, not private-only. The reference
   project's `public_network_access_enabled = false` combined with a
   `azurerm_postgresql_flexible_server_firewall_rule` is self-contradictory
   (firewall rules have no effect when public access is disabled). This spec
   resolves it by choosing public+firewall, which is simpler for `dev` admin
   access.
2. **Jumpbox retained** even though it's not required for Postgres access
   under the public+firewall model, per explicit user decision — kept
   available for future admin/debug access to private subnets (e.g. if the
   MCP service ends up private-only).
3. **No storage account/Azure Files volume** — the reference project needed
   it for its app's file storage; this project's app is stateless aside from
   the Postgres checkpointer.
4. **No pgvector** — the reference project's Postgres hosted an app with
   RAG/embeddings; this project's Agent 1 does keyword search via the .NET
   CSOM sidecar, not vector search.

## README changes

Update `README.md`'s "Deployment path" section to describe the ACI + App
Gateway target as the current implementation (replacing the ACA description),
keeping the Azure AI Foundry Hosted Agent line as a future migration note
(unchanged in spirit, just no longer implying ACA is the current stepping
stone).

## Variables / environments

- `environments/dev/terraform.tfvars` — non-secret variables only (location,
  VM/DB sizes, ACR name, `local_ip` allowlist, resource name prefixes).
- Secret-valued variables (Postgres admin password, App Gateway cert +
  password) are supplied via `TF_VAR_*` environment variables or a
  gitignored `secrets.auto.tfvars` — never committed.
- To add `prod`/`staging` later: copy `environments/dev/` to a new directory,
  adjust `terraform.tfvars` and the backend state key (e.g. `prod.tfstate`).
  No changes needed to `modules/`.

## Validation / testing

- `terraform fmt -check` and `terraform validate` run locally before every
  `apply`. Documented in a new `terraform/README.md`.
- No CI automation of `plan`/`apply` in this iteration (explicit scope
  decision — `apply` stays manual via CLI for now).

## Testing this spec's implementation

Since this is infrastructure code, "testing" means:
- `terraform validate` passes for every module and the `dev` environment root.
- `terraform plan` against a real (or sandbox) Azure subscription produces the
  expected resource list with no errors.
- Manual smoke test after `apply`: reach the audit-agent's `/health` endpoint
  through the App Gateway's public IP over HTTPS, confirm the ACI container
  can pull from ACR (managed identity works), confirm the container can reach
  Postgres (checkpointer connects) and Key Vault (secrets resolved at
  Terraform apply time, present as env vars in the running container).
