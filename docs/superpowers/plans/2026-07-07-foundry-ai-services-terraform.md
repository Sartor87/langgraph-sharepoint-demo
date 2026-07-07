# Foundry AI Services Terraform Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring an already-existing Azure AI Foundry account + project under this repo's Terraform management (via `terraform import`, not re-creation), and wire its endpoint into the existing Foundry Hosted Agent deploy docs so it no longer requires manual copy-paste from the Azure portal.

**Architecture:** A new reusable module `terraform/modules/foundry-ai-services/` (provider `~> 4.0`, independent of this repo's other `~> 3.0` modules) wraps `azurerm_cognitive_account` (kind `AIServices`) + `azurerm_cognitive_account_project`. A new root `terraform/environments/foundry/` (own state file) instantiates it against a resource group referenced read-only via a data source (never owned/imported as a Terraform resource). `foundry/README.md` is updated to source `FOUNDRY_PROJECT_ENDPOINT` from `terraform output` instead of manual copy-paste.

**Tech Stack:** Terraform 1.7.x, `hashicorp/azurerm ~> 4.0` (this root only — `azurerm_cognitive_account_project` requires v4.x), Azure Cognitive Services / AI Foundry.

## Global Constraints

- **Public repo — no real subscription ID, resource group name, account name, or project name appears anywhere in tracked files.** All of these are required Terraform variables with no defaults, supplied only via `TF_VAR_*` env vars or a gitignored `terraform.tfvars`/`secrets.auto.tfvars` at apply time.
- `azurerm_cognitive_account_project` requires provider `~> 4.0` — this is a fully separate Terraform root from `environments/dev` (own backend key, own provider version), so there is no version-constraint conflict with the rest of this repo's `~> 3.0` modules.
- The target resource group is referenced via `data "azurerm_resource_group"` only — never created, imported, or owned by this Terraform. It may contain other resources; nothing here may ever modify or destroy it.
- No model deployment resources (`azurerm_cognitive_deployment` or similar) — out of scope for this plan.
- `terraform import` and `terraform apply` against the real resources are manual, human-run steps — never automated by any task in this plan.

---

### Task 1: `modules/foundry-ai-services`

**Files:**
- Create: `terraform/modules/foundry-ai-services/versions.tf`
- Create: `terraform/modules/foundry-ai-services/variables.tf`
- Create: `terraform/modules/foundry-ai-services/main.tf`
- Create: `terraform/modules/foundry-ai-services/outputs.tf`

**Interfaces:**
- Consumes: `account_name`, `project_name`, `resource_group_name`, `location`, `custom_subdomain_name` (all required strings, no defaults — real values are environment-specific and never committed), `sku_name` (default `"S0"`), `public_network_access_enabled` (default `true`), `local_auth_enabled` (default `true`), `dynamic_throttling_enabled` (default `false`), `project_management_enabled` (default `true`), `outbound_network_access_restricted` (default `false`), `network_acls_bypass` (default `"AzureServices"`), `network_acls_default_action` (default `"Allow"`), `project_description` (default `""`), `project_display_name` (default `""`), `tags` (default `{}`).
- Produces: `cognitive_account_id` (string), `foundry_project_endpoint` (string) — consumed by Task 2's root wiring.

- [ ] **Step 1: Write the module**

`terraform/modules/foundry-ai-services/versions.tf`:
```hcl
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}
```

`terraform/modules/foundry-ai-services/variables.tf`:
```hcl
variable "account_name" {
  description = "Name of the existing Cognitive Services (AIServices) account to import."
  type        = string
}

variable "project_name" {
  description = "Name of the existing Foundry project under the account to import."
  type        = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "custom_subdomain_name" {
  description = "The account's custom subdomain (usually matches account_name) — used to construct the Foundry project endpoint."
  type        = string
}

variable "sku_name" {
  type    = string
  default = "S0"
}

variable "public_network_access_enabled" {
  type    = bool
  default = true
}

variable "local_auth_enabled" {
  type    = bool
  default = true
}

variable "dynamic_throttling_enabled" {
  type    = bool
  default = false
}

variable "project_management_enabled" {
  type    = bool
  default = true
}

variable "outbound_network_access_restricted" {
  type    = bool
  default = false
}

variable "network_acls_bypass" {
  description = "Azure's real default is \"AzureServices\" — the exported config's empty string is not a valid value for this field."
  type        = string
  default     = "AzureServices"
}

variable "network_acls_default_action" {
  type    = string
  default = "Allow"
}

variable "project_description" {
  type    = string
  default = ""
}

variable "project_display_name" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
```

`terraform/modules/foundry-ai-services/main.tf`:
```hcl
resource "azurerm_cognitive_account" "this" {
  name                = var.account_name
  resource_group_name = var.resource_group_name
  location            = var.location
  kind                = "AIServices"
  sku_name            = var.sku_name

  custom_subdomain_name               = var.custom_subdomain_name
  public_network_access_enabled       = var.public_network_access_enabled
  local_auth_enabled                  = var.local_auth_enabled
  dynamic_throttling_enabled          = var.dynamic_throttling_enabled
  project_management_enabled          = var.project_management_enabled
  outbound_network_access_restricted  = var.outbound_network_access_restricted

  identity {
    type = "SystemAssigned"
  }

  network_acls {
    default_action = var.network_acls_default_action
    bypass         = var.network_acls_bypass
  }

  tags = var.tags
}

resource "azurerm_cognitive_account_project" "this" {
  name                 = var.project_name
  cognitive_account_id = azurerm_cognitive_account.this.id
  location             = var.location
  display_name         = var.project_display_name
  description          = var.project_description
  tags                 = var.tags

  identity {
    type = "SystemAssigned"
  }
}
```

`terraform/modules/foundry-ai-services/outputs.tf`:
```hcl
output "cognitive_account_id" {
  value = azurerm_cognitive_account.this.id
}

output "foundry_project_endpoint" {
  value = "https://${var.custom_subdomain_name}.services.ai.azure.com/api/projects/${var.project_name}"
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/foundry-ai-services && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Format check**

Run: `terraform fmt -recursive terraform/modules/foundry-ai-services && terraform fmt -check terraform/modules/foundry-ai-services`
Expected: second command exits 0, no output.

- [ ] **Step 4: Commit**

```bash
git add terraform/modules/foundry-ai-services
git commit -m "feat(terraform): add foundry-ai-services module (import-ready, provider ~> 4.0)"
```

---

### Task 2: `environments/foundry` root

**Files:**
- Create: `terraform/environments/foundry/backend.tf`
- Create: `terraform/environments/foundry/versions.tf`
- Create: `terraform/environments/foundry/variables.tf`
- Create: `terraform/environments/foundry/main.tf`
- Create: `terraform/environments/foundry/outputs.tf`
- Create: `terraform/environments/foundry/README.md`

**Interfaces:**
- Consumes: Task 1's module outputs (`cognitive_account_id`, `foundry_project_endpoint`).
- Produces: root-level output `foundry_project_endpoint` — consumed by Task 3's `foundry/README.md` update (`terraform output -raw foundry_project_endpoint` from this directory).

- [ ] **Step 1: Write backend + provider config**

`terraform/environments/foundry/backend.tf`:
```hcl
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-audit-agent-tfstate"
    storage_account_name = "stauditagenttfstate"
    container_name       = "tfstate"
    key                  = "foundry.tfstate"
  }
}
```

`terraform/environments/foundry/versions.tf`:
```hcl
terraform {
  required_version = ">= 1.7.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}
```

- [ ] **Step 2: Write variables**

`terraform/environments/foundry/variables.tf`:
```hcl
variable "subscription_id" {
  type = string
}

variable "resource_group_name" {
  description = "Name of the existing resource group containing the Foundry AI Services account. Not owned by this Terraform — referenced read-only via a data source."
  type        = string
}

variable "location" {
  type    = string
  default = "swedencentral"
}

variable "account_name" {
  description = "Name of the existing Cognitive Services (AIServices) account to import."
  type        = string
}

variable "custom_subdomain_name" {
  description = "The account's custom subdomain (usually matches account_name)."
  type        = string
}

variable "project_name" {
  description = "Name of the existing Foundry project under the account to import."
  type        = string
}
```

- [ ] **Step 3: Write root wiring**

`terraform/environments/foundry/main.tf`:
```hcl
data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

module "foundry_ai_services" {
  source                = "../../modules/foundry-ai-services"
  account_name          = var.account_name
  project_name          = var.project_name
  resource_group_name   = data.azurerm_resource_group.this.name
  location              = var.location
  custom_subdomain_name = var.custom_subdomain_name
}
```

`terraform/environments/foundry/outputs.tf`:
```hcl
output "foundry_project_endpoint" {
  value = module.foundry_ai_services.foundry_project_endpoint
}
```

- [ ] **Step 4: Write the import/usage README**

`terraform/environments/foundry/README.md`:
```markdown
# Foundry AI Services — Terraform import

Brings an **already-existing** Azure AI Foundry account + project under
Terraform management. Does not create new resources — the account/project
must already exist in Azure.

## Prerequisites

- The Foundry AI Services account and project already exist in Azure.
- `az login` with access to the target subscription.

## One-time setup

\`\`\`bash
cd terraform/environments/foundry
export TF_VAR_subscription_id=<your-subscription-id>
export TF_VAR_resource_group_name=<your-resource-group-name>
export TF_VAR_account_name=<your-account-name>
export TF_VAR_custom_subdomain_name=<your-account-custom-subdomain>
export TF_VAR_project_name=<your-project-name>

terraform init
\`\`\`

## Import the existing resources

\`\`\`bash
terraform import module.foundry_ai_services.azurerm_cognitive_account.this \
  /subscriptions/<subscription-id>/resourceGroups/<resource-group-name>/providers/Microsoft.CognitiveServices/accounts/<account-name>

terraform import module.foundry_ai_services.azurerm_cognitive_account_project.this \
  /subscriptions/<subscription-id>/resourceGroups/<resource-group-name>/providers/Microsoft.CognitiveServices/accounts/<account-name>/projects/<project-name>
\`\`\`

Find the account's real resource ID with:
\`\`\`bash
az cognitiveservices account show --name <account-name> --resource-group <resource-group-name> --query id -o tsv
\`\`\`

## After import

\`\`\`bash
terraform plan
\`\`\`

Expected: no changes, or only the intentional corrections this module makes
to the account's exported config (e.g. `network_acls.bypass` moving from
unset/empty to `"AzureServices"` — Azure's real default; the export tool's
empty string isn't a valid value). Any other diff means a variable default
doesn't match the real resource yet — fix the variable value, don't apply
blindly.

\`\`\`bash
terraform output -raw foundry_project_endpoint
\`\`\`

This is the value `foundry/README.md` uses for `FOUNDRY_PROJECT_ENDPOINT`.
```

- [ ] **Step 5: Validate (no backend, no real credentials needed)**

Run: `cd terraform/environments/foundry && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 6: Format check**

Run: `terraform fmt -recursive terraform/environments/foundry && terraform fmt -check terraform/environments/foundry`
Expected: second command exits 0, no output.

- [ ] **Step 7: Commit**

```bash
git add terraform/environments/foundry
git commit -m "feat(terraform): add environments/foundry root for importing existing Foundry AI Services resources"
```

**Note for whoever runs this against real Azure resources:** `terraform import` and any subsequent `terraform apply` are manual, human-run steps — they touch real, already-existing production-ish resources. Not automated by this plan. Do them only after confirming the variable values above exactly match the real account.

---

### Task 3: Wire `foundry_project_endpoint` into `foundry/README.md`

**Files:**
- Modify: `foundry/README.md:13-19` (the "Local test" section)

**Interfaces:** None — documentation only.

- [ ] **Step 1: Replace the manual export instructions**

In `foundry/README.md`, replace:

```markdown
## Local test

```bash
export FOUNDRY_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export FOUNDRY_MODEL_NAME="gpt-4.1"
python -m app.main
```
```

with:

```markdown
## Local test

```bash
cd terraform/environments/foundry
export FOUNDRY_PROJECT_ENDPOINT=$(terraform output -raw foundry_project_endpoint)
cd -

export FOUNDRY_MODEL_NAME="gpt-4.1"
python -m app.main
```

(See `terraform/environments/foundry/README.md` if you haven't imported the
Foundry account/project into Terraform yet — until then, set
`FOUNDRY_PROJECT_ENDPOINT` manually from the Azure portal instead.)
```

- [ ] **Step 2: Commit**

```bash
git add foundry/README.md
git commit -m "docs: source FOUNDRY_PROJECT_ENDPOINT from terraform output"
```
