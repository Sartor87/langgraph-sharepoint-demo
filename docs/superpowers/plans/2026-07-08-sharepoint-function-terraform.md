# SharePoint Function Terraform Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision the missing Terraform infrastructure for `sharepoint-csom-service/` (the SharePoint search Azure Function) — a Consumption-plan Linux Function App, its own dedicated Managed Identity, and wire its endpoint into the Audit Agent's environment variables — closing a gap left deliberately deferred by the Function's original implementation plan.

**Architecture:** A new generic `terraform/modules/function-app/` module (Linux Function App, `.NET` isolated worker, code-deploy — no container image, since this Function has no Dockerfile) provisions its own Storage Account with `storage_uses_managed_identity = true` (no stored storage key). `terraform/environments/dev/main.tf` creates a dedicated identity for this Function (separate from the existing `audit_agent` identity — least-privilege, since only this Function ever needs SharePoint permissions) and wires the Function's hostname into the ACI container's `SHAREPOINT_FUNCTION_URL`/`SHAREPOINT_TOOL_BACKEND` environment variables, which are currently missing from that block even though `app/tools/sharepoint_tool.py` and `.env.example` already document them.

**Tech Stack:** Terraform, `hashicorp/azurerm ~> 3.0` (matches `environments/dev`'s existing pin), Azure Functions (Consumption/Y1 plan, Linux, .NET isolated worker).

## Global Constraints

- This module lives inside `terraform/environments/dev` (existing `~> 3.0` root) — NOT a separate root like `terraform/environments/foundry`.
- No container image handling — `sharepoint-csom-service/` has no Dockerfile; this is a code-deploy Function App. Actually deploying the code (`func azure functionapp publish` or CI) is out of scope — Terraform only provisions the infra shell.
- The Function's identity is dedicated (`azurerm_user_assigned_identity.sharepoint_function`), never the existing `audit_agent` identity.
- Storage access uses `storage_uses_managed_identity = true` plus role assignments — no `storage_account_access_key` in any output or app setting.
- The SharePoint `Sites.Selected` permission grant is documented as an entirely manual, human-run prerequisite — not automated via the `azuread` provider or any other Terraform resource (see the design spec for why: the site-specific-scoping half of the grant has no Terraform resource at all, so partially automating the other half would be inconsistent).
- No VNet integration for the Function App (not needed).

---

### Task 1: `modules/function-app`

**Files:**
- Create: `terraform/modules/function-app/versions.tf`
- Create: `terraform/modules/function-app/variables.tf`
- Create: `terraform/modules/function-app/main.tf`
- Create: `terraform/modules/function-app/outputs.tf`

**Interfaces:**
- Consumes: `name`, `resource_group_name`, `location`, `tags` (default `{}`), `identity_id` (required — resource ID of a user-assigned identity the caller already created), `identity_principal_id` (required — that same identity's principal ID, for the role assignments; passed separately rather than looked up via a data source, matching this repo's existing module pattern — e.g. `modules/acr`'s `pull_identity_principal_id`), `dotnet_version` (default `"10.0"`, matching `sharepoint-csom-service/SharePointSearchFunction.csproj`'s real `TargetFramework`).
- Produces: `function_app_id` (string), `default_hostname` (string) — consumed by Task 2's root wiring.

- [ ] **Step 1: Write the module**

`terraform/modules/function-app/versions.tf`:
```hcl
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}
```

`terraform/modules/function-app/variables.tf`:
```hcl
variable "name" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "identity_id" {
  description = "Resource ID of the user-assigned identity to attach to the Function App."
  type        = string
}

variable "identity_principal_id" {
  description = "Principal ID of the same identity — used for the storage role assignments."
  type        = string
}

variable "dotnet_version" {
  type    = string
  default = "10.0"
}
```

`terraform/modules/function-app/main.tf`:
```hcl
resource "azurerm_storage_account" "this" {
  name                     = "st${replace(var.name, "-", "")}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = var.tags
}

resource "azurerm_service_plan" "this" {
  name                = "asp-${var.name}"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = "Y1"
  tags                = var.tags
}

resource "azurerm_linux_function_app" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  service_plan_id     = azurerm_service_plan.this.id

  storage_account_name          = azurerm_storage_account.this.name
  storage_uses_managed_identity = true

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  site_config {
    application_stack {
      dotnet_version              = var.dotnet_version
      use_dotnet_isolated_runtime = true
    }
  }

  app_settings = {
    FUNCTIONS_WORKER_RUNTIME = "dotnet-isolated"
  }

  tags = var.tags

  depends_on = [
    azurerm_role_assignment.storage_blob,
    azurerm_role_assignment.storage_queue,
    azurerm_role_assignment.storage_table,
  ]
}

resource "azurerm_role_assignment" "storage_blob" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = var.identity_principal_id
}

resource "azurerm_role_assignment" "storage_queue" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = var.identity_principal_id
}

resource "azurerm_role_assignment" "storage_table" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = var.identity_principal_id
}
```

(The explicit `depends_on` on `azurerm_linux_function_app.this` ensures the storage role assignments exist before the Function App tries to use managed-identity storage access — Terraform's implicit dependency graph already orders the storage account's own creation correctly via `azurerm_storage_account.this.name`, but the role assignments aren't otherwise referenced by the Function App resource's arguments, so this makes the ordering explicit rather than relying on luck.)

`terraform/modules/function-app/outputs.tf`:
```hcl
output "function_app_id" {
  value = azurerm_linux_function_app.this.id
}

output "default_hostname" {
  value = azurerm_linux_function_app.this.default_hostname
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/function-app && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

If this fails specifically on `storage_uses_managed_identity` (unknown argument, or a version-related schema error), that means the installed `azurerm` provider version resolved under the `~> 3.0` constraint doesn't have this argument yet — check `terraform providers` for the resolved version and `azurerm`'s changelog for when `storage_uses_managed_identity` was added to `azurerm_linux_function_app`, and either bump the constraint (still within `~> 3.0` if possible) or fall back to `storage_account_access_key = azurerm_storage_account.this.primary_access_key` (a real secret in state, less preferred but a legitimate fallback) — report which path you took and why in your report, don't silently pick one without noting it.

- [ ] **Step 3: Format**

Run: `terraform fmt -recursive terraform/modules/function-app && terraform fmt -check terraform/modules/function-app`
Expected: second command exits 0, no output.

- [ ] **Step 4: Commit**

```bash
git add terraform/modules/function-app
git commit -m "feat(terraform): add generic function-app module (Linux, Consumption, managed-identity storage)"
```

---

### Task 2: Wire into `environments/dev`

**Files:**
- Modify: `terraform/environments/dev/main.tf`
- Modify: `terraform/environments/dev/outputs.tf`

**Interfaces:**
- Consumes: Task 1's module outputs (`default_hostname`).
- Produces: root output `sharepoint_function_hostname`; `SHAREPOINT_FUNCTION_URL`/`SHAREPOINT_TOOL_BACKEND` now present in the ACI container's `environment_variables`, matching what `app/tools/sharepoint_tool.py` and `.env.example` already document.

- [ ] **Step 1: Add the dedicated identity and module instantiation**

In `terraform/environments/dev/main.tf`, add (near the existing `azurerm_user_assigned_identity.audit_agent` resource, e.g. right after it):

```hcl
resource "azurerm_user_assigned_identity" "sharepoint_function" {
  name                = "id-sharepoint-function-dev"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  tags                = local.tags
}
```

Add a new module block (after `module.jumpbox`, before `module.audit_agent` — no ordering dependency between them, but this keeps related infra grouped):

```hcl
module "sharepoint_function" {
  source                 = "../../modules/function-app"
  name                   = "func-sharepoint-search-dev"
  resource_group_name    = module.resource_group.name
  location               = module.resource_group.location
  tags                   = local.tags
  identity_id            = azurerm_user_assigned_identity.sharepoint_function.id
  identity_principal_id  = azurerm_user_assigned_identity.sharepoint_function.principal_id
}
```

- [ ] **Step 2: Wire the Function's URL into the Audit Agent's environment variables**

In `terraform/environments/dev/main.tf`, `module "audit_agent"`'s `environment_variables` block currently reads:

```hcl
  environment_variables = {
    AZURE_OPENAI_ENDPOINT                 = var.azure_openai_endpoint
    AZURE_OPENAI_DEPLOYMENT               = var.azure_openai_deployment
    SHAREPOINT_SERVICE_URL                = var.sharepoint_service_url
    SHAREPOINT_SITE_URL                   = var.sharepoint_site_url
    DB_HOST                               = module.postgres.fqdn
    DB_NAME                               = module.postgres.database_name
    DB_USER                               = "auditagent"
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.this.connection_string
  }
```

Change it to:

```hcl
  environment_variables = {
    AZURE_OPENAI_ENDPOINT                 = var.azure_openai_endpoint
    AZURE_OPENAI_DEPLOYMENT               = var.azure_openai_deployment
    SHAREPOINT_TOOL_BACKEND               = "azure_function"
    SHAREPOINT_FUNCTION_URL               = "https://${module.sharepoint_function.default_hostname}"
    SHAREPOINT_SERVICE_URL                = var.sharepoint_service_url
    SHAREPOINT_SITE_URL                   = var.sharepoint_site_url
    DB_HOST                               = module.postgres.fqdn
    DB_NAME                               = module.postgres.database_name
    DB_USER                               = "auditagent"
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.this.connection_string
  }
```

(only the two new lines are added — `SHAREPOINT_SERVICE_URL`/`SHAREPOINT_SITE_URL` stay, since the `python` backend remains a config-selectable "explore" option per `app/tools/sharepoint_tool.py`'s design.)

- [ ] **Step 3: Add the root output**

In `terraform/environments/dev/outputs.tf`, add:

```hcl
output "sharepoint_function_hostname" {
  value = module.sharepoint_function.default_hostname
}
```

- [ ] **Step 4: Validate**

Run: `cd terraform/environments/dev && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 5: Format**

Run: `terraform fmt -recursive terraform/environments/dev && terraform fmt -check terraform/environments/dev`
Expected: second command exits 0, no output.

- [ ] **Step 6: Commit**

```bash
git add terraform/environments/dev/main.tf terraform/environments/dev/outputs.tf
git commit -m "feat(terraform): provision the SharePoint Function's infra and wire its URL into the Audit Agent"
```

---

### Task 3: Documentation — manual SharePoint permission grant

**Files:**
- Modify: `sharepoint-csom-service/README.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Add the manual grant steps**

In `sharepoint-csom-service/README.md`, find the "## Prerequisites for a real deployment" section (already mentions the permission grant as a manual step in general terms). Replace it with:

```markdown
## Prerequisites for a real deployment

Once `terraform apply` has created the Function App and its dedicated
identity (`id-sharepoint-function-dev`), grant that identity SharePoint
access — this is a two-part manual process with no Terraform equivalent for
the second part:

1. **Grant the Microsoft Graph `Sites.Selected` application permission** to
   the identity's service principal (Azure Portal → Microsoft Entra ID →
   Enterprise Applications → find `id-sharepoint-function-dev` → API
   permissions → Add a permission → Microsoft Graph → Application
   permissions → `Sites.Selected` → Grant admin consent). This can
   technically be scripted via the `azuread` Terraform provider, but is done
   manually here to keep the whole grant in one place (see step 2).

2. **Scope that permission to the specific SharePoint site** the Function
   should access — there is no Terraform/ARM resource for this at all; it's
   a Microsoft Graph API call. The standard tool is PnP PowerShell:

   ```powershell
   Install-Module -Name PnP.PowerShell -Scope CurrentUser
   Connect-PnPOnline -Url "https://<tenant>.sharepoint.com/sites/<site>" -Interactive

   Grant-PnPAzureADAppSitePermission `
     -AppId "<the identity's client/application ID, from the Enterprise Application's Overview page>" `
     -DisplayName "id-sharepoint-function-dev" `
     -Site "https://<tenant>.sharepoint.com/sites/<site>" `
     -Permissions Read
   ```

   Use `-Permissions Write` instead (or in addition) if the Function will
   ever need to write back to SharePoint — today it only searches and finds
   files, so `Read` is sufficient.

- Infrastructure (the Function App resource itself, its Storage Account, and
  its dedicated Managed Identity) is provisioned by
  `terraform/environments/dev` (`module.sharepoint_function`) — see that
  module's Terraform for what's created.
```

- [ ] **Step 2: Commit**

```bash
git add sharepoint-csom-service/README.md
git commit -m "docs: document the manual SharePoint Sites.Selected permission grant"
```
