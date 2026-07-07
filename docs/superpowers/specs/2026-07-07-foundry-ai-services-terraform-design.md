# Foundry AI Services Terraform Import — Design

Date: 2026-07-07
Status: Approved (pending spec self-review)

## Context

A Foundry AI Services account (`kind = "AIServices"`) and a Foundry project
under it already exist in Azure, created outside Terraform, in a resource
group not owned by this repo's other Terraform (region `swedencentral` in
the example the user shared). The user exported their current config via
Azure's Terraform export tooling (`Microsoft.AzureTerraform` resource
provider / `aztfexport`, which requires that provider registered at
subscription scope — that's what "activate Terraform at Subscription level"
referred to; it's a one-time prerequisite for the *export* process the user
already ran, not something this module depends on at apply-time).

**This repo is/will be public — no subscription ID, tenant ID, resource
group name, or account/project name from the user's real environment
appears anywhere in this spec, the module, or the root config.** All of
those are required variables with no defaults (see Architecture), supplied
only via `TF_VAR_*` env vars or a gitignored `terraform.tfvars`/
`secrets.auto.tfvars` at apply time — same treatment this repo already
gives `postgres_admin_password` and friends in `environments/dev`.

This spec brings that existing account+project under this repo's Terraform
management (via `terraform import`, not re-creation) and connects its
endpoint to the existing Foundry Hosted Agent deploy path (`foundry/README.md`,
`app/graph.py`'s `FOUNDRY_PROJECT_ENDPOINT` usage), which currently requires
copying the endpoint by hand from the Azure portal.

## Scope

In scope:
- New reusable module `terraform/modules/foundry-ai-services/` wrapping
  `azurerm_cognitive_account` (kind `AIServices`) + `azurerm_cognitive_account_project`.
- New root `terraform/environments/foundry/` (own state file, own provider
  version) instantiating that module against the real existing resource
  group, prepared for `terraform import`.
- `foundry_project_endpoint` output, and an update to `foundry/README.md` to
  source `FOUNDRY_PROJECT_ENDPOINT` from `terraform output` instead of manual
  copy-paste.
- Documented, manual `terraform import` commands (two resources) — like
  `terraform apply`/`azd deploy` elsewhere in this repo, imports are a
  human-run step, not automated by any task.

Out of scope (explicitly deferred):
- Model deployment resources (`azurerm_cognitive_deployment` or similar) —
  the user confirmed none are needed in this pass; if one exists it stays
  manually managed for now.
- Managing the target resource group itself as a Terraform-owned resource
  — referenced via `data "azurerm_resource_group"` only (see Architecture).
  It may contain other resources unrelated to this project; Terraform must
  never be able to modify or destroy it.
- Merging this into `terraform/environments/dev`'s state — kept as a fully
  separate root/state on purpose (see Architecture).
- Any QnA Maker / Metrics Advisor integration fields present in the
  exported HCL — this account doesn't use those features (see "Attribute
  cleanup" below).

## Architecture

```
terraform/modules/foundry-ai-services/
├── versions.tf       # azurerm ~> 4.0 — azurerm_cognitive_account_project
│                     #   requires provider v4.x; independent of the rest of
│                     #   this repo's ~> 3.0 modules since this is a fully
│                     #   separate root/state, no version conflict possible
├── variables.tf      # account_name, project_name, resource_group_name,
│                     #   location, sku_name (default "S0"),
│                     #   public_network_access_enabled (default true),
│                     #   local_auth_enabled (default true),
│                     #   network_acls_bypass (default "AzureServices"),
│                     #   network_acls_default_action (default "Allow"), tags
├── main.tf            # azurerm_cognitive_account.this (kind = "AIServices")
│                     #   + azurerm_cognitive_account_project.this
└── outputs.tf         # cognitive_account_id, foundry_project_endpoint
                       #   (constructed: https://<custom_subdomain_name>
                       #    .services.ai.azure.com/api/projects/<project_name>)

terraform/environments/foundry/
├── backend.tf         # same storage account/container as environments/dev
│                       #   (stauditagenttfstate / tfstate), key = "foundry.tfstate"
├── versions.tf         # provider "azurerm" (~> 4.0), features {}, subscription_id var
├── variables.tf        # subscription_id, resource_group_name, account_name,
│                       #   project_name — ALL required, no defaults (real
│                       #   values are environment-specific and never
│                       #   committed); location has a default of
│                       #   "swedencentral" since region isn't identifying
│                       #   on its own, but can be overridden
├── main.tf             # data "azurerm_resource_group" "this" (existing RG,
│                       #   read-only reference — Terraform never creates,
│                       #   modifies, or destroys this resource group) +
│                       #   module "foundry_ai_services"
├── outputs.tf          # foundry_project_endpoint (passthrough from the module)
└── README.md           # prerequisites, the two terraform import commands,
                       #   terraform plan/apply notes (manual, human-run)
```

Kept as a separate root (own backend key, own provider version) rather than
folded into `environments/dev`, because: (1) it targets a different resource
group not owned by the audit-agent's Terraform, representing a
broader/shared "LangChain Orchestrator" platform resource rather than
something scoped to this one app's dev environment; (2)
`azurerm_cognitive_account_project` needs provider `~> 4.0`, while
`environments/dev` and all its modules are pinned to `~> 3.0` — a separate
root sidesteps any version-constraint conflict entirely, since each
Terraform root resolves its own provider version independently.

The resource group itself is referenced via `data "azurerm_resource_group"`,
never imported as a managed `azurerm_resource_group` resource — this is a
deliberate safety boundary. If the RG contains anything else (now or later),
Terraform must have no path to modify or destroy it; only the two resources
inside it that this module owns are importable/manageable.

## Attribute cleanup (exported HCL → module)

The user's exported HCL is Azure's Terraform-export output, not hand-written
config — it includes several fields that are either pure computed
attributes (not valid as input arguments) or unused integration points. The
module keeps only real, meaningful configuration:

**Dropped as computed/not-a-real-input** (regardless of the export tool
showing them as empty-string assignments):
- `primary_access_key`, `secondary_access_key` — read-only computed outputs
  of the account resource, never settable.
- `qna_runtime_endpoint` — computed, QnA Maker-specific.

**Dropped as unused integration points** (this account doesn't use these
features):
- `custom_question_answering_search_service_id` / `_key`
- `metrics_advisor_aad_client_id` / `_tenant_id` / `_super_user_name` / `_website_name`

**Corrected from export-tool artifacts to real values:**
- `identity.identity_ids = []` → dropped entirely; `identity_ids` is only
  meaningful for `UserAssigned` identities, and this account uses
  `SystemAssigned` (just `type = "SystemAssigned"`, no `identity_ids` field).
- `network_acls.bypass = ""` → `"AzureServices"` (Azure's real default;
  empty string is not a valid value for this field), exposed as a variable
  with that default so it can be overridden if a stricter posture is ever
  needed.

**Kept as real, meaningful configuration** (parameterized as module
variables rather than hardcoded, following this repo's existing module
pattern): `kind = "AIServices"` (not parameterized — this module is
specifically for AI Services/Foundry accounts, not general Cognitive
Services), `sku_name`, `custom_subdomain_name`, `public_network_access_enabled`,
`local_auth_enabled`, `dynamic_throttling_enabled`, `project_management_enabled`,
`outbound_network_access_restricted`, `network_acls.default_action`, `tags`.

## Import procedure

Documented in `terraform/environments/foundry/README.md`, run manually by a
human after `terraform init` (never automated — same treatment as
`terraform apply`/`azd deploy` elsewhere in this repo):

```bash
terraform import module.foundry_ai_services.azurerm_cognitive_account.this \
  /subscriptions/<subscription-id>/resourceGroups/<resource-group-name>/providers/Microsoft.CognitiveServices/accounts/<account-name>

terraform import module.foundry_ai_services.azurerm_cognitive_account_project.this \
  /subscriptions/<subscription-id>/resourceGroups/<resource-group-name>/providers/Microsoft.CognitiveServices/accounts/<account-name>/projects/<project-name>
```

(`terraform/environments/foundry/README.md` will show the operator how to
substitute their own real values — via `terraform output`-friendly copies of
the variables they already supplied, e.g. `az cognitiveservices account show
... --query id -o tsv`, not by hardcoding anything in a tracked file.)

After import, `terraform plan` must show no changes (or only the
attribute-cleanup deltas listed above, which reflect real drift between the
exported artifact and this module's intentionally-corrected config — e.g.
`network_acls.bypass` moving from unset/empty to `"AzureServices"`). Any
other diff means the module's variable defaults don't yet match the real
resource and must be adjusted before applying.

## Documentation

- `terraform/environments/foundry/README.md`: prerequisites (existing
  Foundry account+project, subscription access), the two import commands
  above, `terraform plan`/`apply` notes (manual).
- `foundry/README.md` (existing file, from the earlier Foundry Hosted Agent
  plan): change the "Local test" section's `export FOUNDRY_PROJECT_ENDPOINT=...`
  step to:
  ```bash
  cd terraform/environments/foundry
  export FOUNDRY_PROJECT_ENDPOINT=$(terraform output -raw foundry_project_endpoint)
  ```
  replacing the manual portal-copy instruction.

## Open questions

None — all scope/design decisions were confirmed with the user during
brainstorming (import not re-create; separate root; data-source-only RG
reference; no model deployment in this pass; endpoint wired into
`foundry/README.md`).
