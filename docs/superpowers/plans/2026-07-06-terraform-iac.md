# Terraform IaC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy all Azure resources for the langgraph-sharepoint-demo audit agent entirely through Terraform: networking, ACI compute, Postgres checkpointer, Key Vault, ACR, App Gateway ingress, and a jumpbox — replacing the manual `az acr build`/`az containerapp create` deployment path.

**Architecture:** Modular Terraform (`modules/` + `environments/dev/`), mirroring an internal reference ACI-based pattern: VNet with 4 delegated/dedicated subnets, public-Postgres-with-firewall, Key Vault in access-policy mode, Application Gateway doing TLS termination in front of a private ACI container group. A generic `container-group` module is instantiated once now for `audit-agent` and will be reused for the SharePoint MCP microservice in a later task.

**Tech Stack:** Terraform 1.7.x, `hashicorp/azurerm` ~> 3.0, Azure (ACI, Postgres Flexible Server, Key Vault, ACR, Application Gateway, VNet).

## Global Constraints

- Provider: `hashicorp/azurerm ~> 3.0` in every module's `versions.tf` (child modules declare `required_providers` only, never a `provider` block — that's root-only, per Terraform module convention).
- No storage account / Azure Files volume (out of scope per spec — app is stateless aside from Postgres).
- No pgvector extension on Postgres (out of scope per spec — no vector search in this architecture).
- Postgres: public network access + firewall allowlist (not private-only — resolves a contradiction found in the reference pattern).
- Key Vault: access-policy mode, not RBAC.
- Secrets (`postgres_password`, `appgw_ssl_cert_base64`, `appgw_ssl_cert_password`, `azure_openai_key`) are NEVER hardcoded or committed — supplied via `TF_VAR_*` env vars or a gitignored `secrets.auto.tfvars`.
- All resource names below are defaults in `variables.tf` — override via `terraform.tfvars` for real deployments (names like ACR and Key Vault must be globally unique in Azure).
- Every module must pass `terraform validate` standalone before being wired into the root.

---

### Task 1: Bootstrap remote state storage

**Files:**
- Create: `terraform/bootstrap/main.tf`
- Create: `terraform/bootstrap/variables.tf`
- Create: `terraform/bootstrap/outputs.tf`

**Interfaces:**
- Produces: an Azure Storage Account + blob container that `environments/dev/backend.tf` (Task 10) points to as its remote backend. No Terraform-level interface (this state is never imported into the main config) — the coupling is the storage account name/container name matching between this task's defaults and Task 10's `backend.tf`.

- [ ] **Step 1: Write the bootstrap config**

`terraform/bootstrap/variables.tf`:
```hcl
variable "location" {
  type    = string
  default = "westeurope"
}

variable "resource_group_name" {
  type    = string
  default = "rg-audit-agent-tfstate"
}

variable "storage_account_name" {
  type    = string
  default = "stauditagenttfstate"
}

variable "subscription_id" {
  type = string
}
```

`terraform/bootstrap/main.tf`:
```hcl
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

resource "azurerm_resource_group" "tfstate" {
  name     = var.resource_group_name
  location = var.location
}

resource "azurerm_storage_account" "tfstate" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.tfstate.name
  location                 = azurerm_resource_group.tfstate.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_storage_container" "tfstate" {
  name                  = "tfstate"
  storage_account_name  = azurerm_storage_account.tfstate.name
  container_access_type = "private"
}
```

`terraform/bootstrap/outputs.tf`:
```hcl
output "resource_group_name" {
  value = azurerm_resource_group.tfstate.name
}

output "storage_account_name" {
  value = azurerm_storage_account.tfstate.name
}

output "container_name" {
  value = azurerm_storage_container.tfstate.name
}
```

- [ ] **Step 2: Validate syntax**

Run: `cd terraform/bootstrap && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/bootstrap
git commit -m "feat(terraform): add remote state bootstrap"
```

**Note for whoever runs this against a real subscription:** this task's `apply` is a manual, one-time, human-run step (`az login`, then `terraform apply -var subscription_id=<...>`) — it creates real billed Azure resources, so it is deliberately not automated by this plan. Do it once before Task 10.

---

### Task 2: `modules/resource-group`

**Files:**
- Create: `terraform/modules/resource-group/main.tf`
- Create: `terraform/modules/resource-group/variables.tf`
- Create: `terraform/modules/resource-group/outputs.tf`
- Create: `terraform/modules/resource-group/versions.tf`

**Interfaces:**
- Consumes: `name` (string), `location` (string), `tags` (map(string))
- Produces: `id` (string), `name` (string), `location` (string) — consumed by every other module in Task 10's root wiring.

- [ ] **Step 1: Write the module**

`terraform/modules/resource-group/versions.tf`:
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

`terraform/modules/resource-group/variables.tf`:
```hcl
variable "name" {
  type = string
}

variable "location" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
```

`terraform/modules/resource-group/main.tf`:
```hcl
resource "azurerm_resource_group" "this" {
  name     = var.name
  location = var.location
  tags     = var.tags
}
```

`terraform/modules/resource-group/outputs.tf`:
```hcl
output "id" {
  value = azurerm_resource_group.this.id
}

output "name" {
  value = azurerm_resource_group.this.name
}

output "location" {
  value = azurerm_resource_group.this.location
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/resource-group && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/resource-group
git commit -m "feat(terraform): add resource-group module"
```

---

### Task 3: `modules/networking`

**Files:**
- Create: `terraform/modules/networking/main.tf`
- Create: `terraform/modules/networking/variables.tf`
- Create: `terraform/modules/networking/outputs.tf`
- Create: `terraform/modules/networking/versions.tf`

**Interfaces:**
- Consumes: `resource_group_name`, `location`, `tags`, `local_ip` (string, CIDR or single IP for jumpbox/dev SSH+DB allowlisting), `aci_backend_port` (number, default 8000 — matches the app's Uvicorn port from `docker/Dockerfile`).
- Produces: `vnet_id`, `aci_subnet_id`, `postgres_subnet_id`, `jumpbox_subnet_id`, `appgw_subnet_id`, `postgres_private_dns_zone_id` — consumed by Task 6 (postgres), Task 7 (jumpbox), Task 8 (app-gateway), Task 9 (container-group), and wired together in Task 10.

- [ ] **Step 1: Write the module**

`terraform/modules/networking/versions.tf`:
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

`terraform/modules/networking/variables.tf`:
```hcl
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

variable "local_ip" {
  description = "CIDR or single IP allowed to reach jumpbox SSH and Postgres (dev allowlist)."
  type        = string
}

variable "aci_backend_port" {
  description = "Port the audit-agent container listens on (must match docker/Dockerfile's uvicorn --port)."
  type        = number
  default     = 8000
}
```

`terraform/modules/networking/main.tf`:
```hcl
resource "azurerm_virtual_network" "this" {
  name                = "vnet-audit-agent"
  address_space       = ["10.0.0.0/16"]
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_subnet" "aci" {
  name                 = "snet-aci"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.0.1.0/24"]

  delegation {
    name = "aci-delegation"
    service_delegation {
      name    = "Microsoft.ContainerInstance/containerGroups"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.0.2.0/24"]

  delegation {
    name = "postgres-delegation"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "jumpbox" {
  name                 = "snet-jumpbox"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.0.3.0/24"]
}

# No NSG attached to this subnet: Application Gateway's management traffic
# (ports 65200-65535) must reach it, and attaching a restrictive NSG here
# is a common cause of App Gateway provisioning failures.
resource "azurerm_subnet" "appgw" {
  name                 = "snet-appgw"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.0.4.0/24"]
}

resource "azurerm_network_security_group" "postgres" {
  name                = "nsg-postgres"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "AllowFromLocal"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = var.local_ip
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowFromAci"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = "10.0.1.0/24"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowFromJumpbox"
    priority                   = 300
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = "10.0.3.0/24"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "postgres" {
  subnet_id                 = azurerm_subnet.postgres.id
  network_security_group_id = azurerm_network_security_group.postgres.id
}

resource "azurerm_network_security_group" "aci" {
  name                = "nsg-aci"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "AllowOutboundDNS"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Udp"
    source_port_range          = "*"
    destination_port_range     = "53"
    source_address_prefix      = "*"
    destination_address_prefix = "168.63.129.16"
  }

  security_rule {
    name                       = "AllowOutboundHTTPS"
    priority                   = 110
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowOutboundPostgres"
    priority                   = 120
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowInboundFromAppGw"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = var.aci_backend_port
    source_address_prefix      = "10.0.4.0/24"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "aci" {
  subnet_id                 = azurerm_subnet.aci.id
  network_security_group_id = azurerm_network_security_group.aci.id
}

resource "azurerm_network_security_group" "jumpbox" {
  name                = "nsg-jumpbox"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  security_rule {
    name                       = "AllowSSHFromLocal"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.local_ip
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "jumpbox" {
  subnet_id                 = azurerm_subnet.jumpbox.id
  network_security_group_id = azurerm_network_security_group.jumpbox.id
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "vnet-link-postgres"
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  resource_group_name   = var.resource_group_name
  virtual_network_id    = azurerm_virtual_network.this.id
}
```

`terraform/modules/networking/outputs.tf`:
```hcl
output "vnet_id" {
  value = azurerm_virtual_network.this.id
}

output "aci_subnet_id" {
  value = azurerm_subnet.aci.id
}

output "postgres_subnet_id" {
  value = azurerm_subnet.postgres.id
}

output "jumpbox_subnet_id" {
  value = azurerm_subnet.jumpbox.id
}

output "appgw_subnet_id" {
  value = azurerm_subnet.appgw.id
}

output "postgres_private_dns_zone_id" {
  value = azurerm_private_dns_zone.postgres.id
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/networking && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/networking
git commit -m "feat(terraform): add networking module (vnet, subnets, nsgs, private dns)"
```

---

### Task 4: `modules/keyvault`

**Files:**
- Create: `terraform/modules/keyvault/main.tf`
- Create: `terraform/modules/keyvault/variables.tf`
- Create: `terraform/modules/keyvault/outputs.tf`
- Create: `terraform/modules/keyvault/versions.tf`

**Interfaces:**
- Consumes: `name`, `resource_group_name`, `location`, `tags`, `tenant_id` (string), `caller_object_id` (string — the Terraform executor's AAD object id, gets full secret perms), `app_identity_principal_id` (string — audit-agent managed identity, gets `Get` only).
- Produces: `id` (string) — consumed by Task 10 root to create `azurerm_key_vault_secret` resources directly (not by this module — secrets are created at root, next to the values they wrap, per spec).

- [ ] **Step 1: Write the module**

`terraform/modules/keyvault/versions.tf`:
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

`terraform/modules/keyvault/variables.tf`:
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

variable "tenant_id" {
  type = string
}

variable "caller_object_id" {
  type = string
}

variable "app_identity_principal_id" {
  type = string
}
```

`terraform/modules/keyvault/main.tf`:
```hcl
resource "azurerm_key_vault" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tenant_id           = var.tenant_id
  sku_name            = "standard"
  tags                = var.tags

  access_policy {
    tenant_id = var.tenant_id
    object_id = var.caller_object_id

    secret_permissions = ["Get", "Set", "List", "Delete", "Purge"]
  }

  access_policy {
    tenant_id = var.tenant_id
    object_id = var.app_identity_principal_id

    secret_permissions = ["Get"]
  }
}
```

`terraform/modules/keyvault/outputs.tf`:
```hcl
output "id" {
  value = azurerm_key_vault.this.id
}

output "name" {
  value = azurerm_key_vault.this.name
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/keyvault && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/keyvault
git commit -m "feat(terraform): add keyvault module (access-policy mode)"
```

---

### Task 5: `modules/acr`

**Files:**
- Create: `terraform/modules/acr/main.tf`
- Create: `terraform/modules/acr/variables.tf`
- Create: `terraform/modules/acr/outputs.tf`
- Create: `terraform/modules/acr/versions.tf`

**Interfaces:**
- Consumes: `name`, `resource_group_name`, `location`, `tags`, `pull_identity_principal_id` (string — audit-agent managed identity, granted `AcrPull`).
- Produces: `login_server` (string) — consumed by Task 10 to build the container image reference passed into Task 9's `container-group` module.

- [ ] **Step 1: Write the module**

`terraform/modules/acr/versions.tf`:
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

`terraform/modules/acr/variables.tf`:
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

variable "pull_identity_principal_id" {
  type = string
}
```

`terraform/modules/acr/main.tf`:
```hcl
resource "azurerm_container_registry" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = var.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = var.pull_identity_principal_id
}
```

`terraform/modules/acr/outputs.tf`:
```hcl
output "login_server" {
  value = azurerm_container_registry.this.login_server
}

output "id" {
  value = azurerm_container_registry.this.id
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/acr && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/acr
git commit -m "feat(terraform): add acr module"
```

---

### Task 6: `modules/postgres`

**Files:**
- Create: `terraform/modules/postgres/main.tf`
- Create: `terraform/modules/postgres/variables.tf`
- Create: `terraform/modules/postgres/outputs.tf`
- Create: `terraform/modules/postgres/versions.tf`

**Interfaces:**
- Consumes: `name`, `resource_group_name`, `location`, `tags`, `administrator_password` (string, sensitive), `database_name` (string, default `"langgraph_checkpoints"`), `allowed_ip` (string — dev allowlist for the firewall rule).
- Produces: `fqdn` (string), `database_name` (string) — consumed by Task 10 to build the `DATABASE_URL`/connection env var passed into Task 9's `container-group` module.

- [ ] **Step 1: Write the module**

`terraform/modules/postgres/versions.tf`:
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

`terraform/modules/postgres/variables.tf`:
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

variable "administrator_password" {
  type      = string
  sensitive = true
}

variable "database_name" {
  type    = string
  default = "langgraph_checkpoints"
}

variable "allowed_ip" {
  description = "Dev IP allowed through the Postgres firewall (public access model)."
  type        = string
}
```

`terraform/modules/postgres/main.tf`:
```hcl
resource "azurerm_postgresql_flexible_server" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  version             = "16"

  public_network_access_enabled = true

  administrator_login    = "auditagent"
  administrator_password = var.administrator_password
  sku_name                = "B_Standard_B1ms"
  storage_mb               = 32768
  backup_retention_days    = 7

  authentication {
    active_directory_auth_enabled = false
    password_auth_enabled         = true
  }

  tags = var.tags
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_dev" {
  name             = "AllowDevIp"
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = var.allowed_ip
  end_ip_address   = var.allowed_ip
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "this" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "utf8"
}
```

`terraform/modules/postgres/outputs.tf`:
```hcl
output "fqdn" {
  value = azurerm_postgresql_flexible_server.this.fqdn
}

output "database_name" {
  value = azurerm_postgresql_flexible_server_database.this.name
}
```

**Note:** `AllowAzureServices` (the `0.0.0.0`/`0.0.0.0` rule) is Azure's documented convention for "allow other Azure resources" — required because the ACI container group's outbound IP isn't static/predictable. This is the standard trade-off of the public+firewall model chosen in the spec (vs. a private-only Postgres, which would need VNet integration for ACI's egress instead).

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/postgres && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/postgres
git commit -m "feat(terraform): add postgres module (public + firewall allowlist)"
```

---

### Task 7: `modules/jumpbox`

**Files:**
- Create: `terraform/modules/jumpbox/main.tf`
- Create: `terraform/modules/jumpbox/variables.tf`
- Create: `terraform/modules/jumpbox/outputs.tf`
- Create: `terraform/modules/jumpbox/versions.tf`

**Interfaces:**
- Consumes: `name`, `resource_group_name`, `location`, `tags`, `subnet_id` (string, from Task 3's `jumpbox_subnet_id` output), `admin_username` (string, default `"azureuser"`), `ssh_public_key` (string — paste-in OpenSSH public key content, no local file dependency).
- Produces: `public_ip_address` (string) — informational output for whoever needs to SSH in; not consumed by other modules.

- [ ] **Step 1: Write the module**

`terraform/modules/jumpbox/versions.tf`:
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

`terraform/modules/jumpbox/variables.tf`:
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

variable "subnet_id" {
  type = string
}

variable "admin_username" {
  type    = string
  default = "azureuser"
}

variable "ssh_public_key" {
  description = "OpenSSH public key content (e.g. contents of ~/.ssh/id_rsa.pub) — not a file path."
  type        = string
}
```

`terraform/modules/jumpbox/main.tf`:
```hcl
resource "azurerm_public_ip" "this" {
  name                = "pip-${var.name}"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

resource "azurerm_network_interface" "this" {
  name                = "nic-${var.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = var.subnet_id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.this.id
  }
}

resource "azurerm_linux_virtual_machine" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  size                = "Standard_B1s"
  admin_username      = var.admin_username
  tags                = var.tags

  network_interface_ids = [azurerm_network_interface.this.id]

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }
}
```

`terraform/modules/jumpbox/outputs.tf`:
```hcl
output "public_ip_address" {
  value = azurerm_public_ip.this.ip_address
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/jumpbox && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/jumpbox
git commit -m "feat(terraform): add jumpbox module"
```

---

### Task 8: `modules/container-group` (generic ACI module)

**Files:**
- Create: `terraform/modules/container-group/main.tf`
- Create: `terraform/modules/container-group/variables.tf`
- Create: `terraform/modules/container-group/outputs.tf`
- Create: `terraform/modules/container-group/versions.tf`

**Interfaces:**
- Consumes: `name`, `resource_group_name`, `location`, `tags`, `subnet_id`, `identity_id` (string, user-assigned identity resource ID — used both for ACR image pull and as the container group's identity), `image` (string, full image ref e.g. `"<login_server>/audit-agent:latest"`), `port` (number), `cpu` (number, default `1`), `memory_gb` (number, default `2`), `environment_variables` (map(string), default `{}`), `secure_environment_variables` (map(string), sensitive, default `{}`).
- Produces: `private_ip_address` (string) — consumed by Task 10 to feed Task 9's (app-gateway) backend pool.

This module is intentionally generic (no `audit-agent`-specific naming inside it) so it can be instantiated a second time for the SharePoint MCP microservice in a later task.

- [ ] **Step 1: Write the module**

`terraform/modules/container-group/versions.tf`:
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

`terraform/modules/container-group/variables.tf`:
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

variable "subnet_id" {
  type = string
}

variable "identity_id" {
  type = string
}

variable "image" {
  type = string
}

variable "port" {
  type = number
}

variable "cpu" {
  type    = number
  default = 1
}

variable "memory_gb" {
  type    = number
  default = 2
}

variable "environment_variables" {
  type    = map(string)
  default = {}
}

variable "secure_environment_variables" {
  type      = map(string)
  default   = {}
  sensitive = true
}
```

`terraform/modules/container-group/main.tf`:
```hcl
resource "azurerm_container_group" "this" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  os_type             = "Linux"
  restart_policy      = "Always"
  tags                = var.tags

  subnet_ids = [var.subnet_id]

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  image_registry_credential {
    server                    = split("/", var.image)[0]
    user_assigned_identity_id = var.identity_id
  }

  ip_address_type = "Private"

  exposed_port {
    port     = var.port
    protocol = "TCP"
  }

  container {
    name   = "app"
    image  = var.image
    cpu    = var.cpu
    memory = var.memory_gb

    ports {
      port     = var.port
      protocol = "TCP"
    }

    environment_variables         = var.environment_variables
    secure_environment_variables  = var.secure_environment_variables
  }
}
```

`terraform/modules/container-group/outputs.tf`:
```hcl
output "private_ip_address" {
  value = azurerm_container_group.this.ip_address
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/container-group && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/container-group
git commit -m "feat(terraform): add generic container-group module"
```

---

### Task 9: `modules/app-gateway`

**Files:**
- Create: `terraform/modules/app-gateway/main.tf`
- Create: `terraform/modules/app-gateway/variables.tf`
- Create: `terraform/modules/app-gateway/outputs.tf`
- Create: `terraform/modules/app-gateway/versions.tf`

**Interfaces:**
- Consumes: `name`, `resource_group_name`, `location`, `tags`, `subnet_id` (from Task 3's `appgw_subnet_id`), `backend_ip_address` (string, from Task 8's `private_ip_address` output), `backend_port` (number), `ssl_cert_base64` (string, sensitive), `ssl_cert_password` (string, sensitive), `health_probe_path` (string, default `"/health"`).
- Produces: `public_ip_address` (string) — the audit-agent's public HTTPS endpoint, printed as a root output in Task 10.

- [ ] **Step 1: Write the module**

`terraform/modules/app-gateway/versions.tf`:
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

`terraform/modules/app-gateway/variables.tf`:
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

variable "subnet_id" {
  type = string
}

variable "backend_ip_address" {
  type = string
}

variable "backend_port" {
  type = number
}

variable "ssl_cert_base64" {
  type      = string
  sensitive = true
}

variable "ssl_cert_password" {
  type      = string
  sensitive = true
}

variable "health_probe_path" {
  type    = string
  default = "/health"
}
```

`terraform/modules/app-gateway/main.tf`:
```hcl
resource "azurerm_public_ip" "this" {
  name                = "pip-${var.name}"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

locals {
  backend_pool_name        = "backend-audit-agent"
  frontend_port_http_name  = "frontend-port-80"
  frontend_port_https_name = "frontend-port-443"
  frontend_ip_name         = "frontend-ip-public"
  http_setting_name        = "http-setting-audit-agent"
  listener_http_name       = "listener-http"
  listener_https_name      = "listener-https"
  redirect_config_name     = "redirect-http-to-https"
  routing_rule_http_name   = "rule-http-redirect"
  routing_rule_https_name  = "rule-https-to-audit-agent"
  health_probe_name        = "probe-audit-agent"
  ssl_cert_name             = "audit-agent-cert"
}

resource "azurerm_application_gateway" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags

  sku {
    name     = "Standard_v2"
    tier     = "Standard_v2"
    capacity = 1
  }

  ssl_policy {
    policy_type = "Predefined"
    policy_name = "AppGwSslPolicy20220101"
  }

  gateway_ip_configuration {
    name      = "appgw-ip-config"
    subnet_id = var.subnet_id
  }

  frontend_ip_configuration {
    name                 = local.frontend_ip_name
    public_ip_address_id = azurerm_public_ip.this.id
  }

  frontend_port {
    name = local.frontend_port_http_name
    port = 80
  }

  frontend_port {
    name = local.frontend_port_https_name
    port = 443
  }

  ssl_certificate {
    name     = local.ssl_cert_name
    data     = var.ssl_cert_base64
    password = var.ssl_cert_password
  }

  backend_address_pool {
    name         = local.backend_pool_name
    ip_addresses = [var.backend_ip_address]
  }

  probe {
    name                = local.health_probe_name
    protocol            = "Http"
    host                = "127.0.0.1"
    path                = var.health_probe_path
    interval            = 30
    timeout             = 10
    unhealthy_threshold = 3

    match {
      status_code = ["200-399"]
    }
  }

  backend_http_settings {
    name                  = local.http_setting_name
    cookie_based_affinity = "Disabled"
    port                  = var.backend_port
    protocol              = "Http"
    request_timeout       = 60

    pick_host_name_from_backend_address = true
    probe_name                          = local.health_probe_name
  }

  http_listener {
    name                           = local.listener_http_name
    frontend_ip_configuration_name = local.frontend_ip_name
    frontend_port_name             = local.frontend_port_http_name
    protocol                       = "Http"
  }

  http_listener {
    name                           = local.listener_https_name
    frontend_ip_configuration_name = local.frontend_ip_name
    frontend_port_name             = local.frontend_port_https_name
    protocol                       = "Https"
    ssl_certificate_name           = local.ssl_cert_name
  }

  redirect_configuration {
    name                 = local.redirect_config_name
    redirect_type        = "Permanent"
    target_listener_name = local.listener_https_name
    include_path         = true
    include_query_string = true
  }

  request_routing_rule {
    name                        = local.routing_rule_http_name
    rule_type                   = "Basic"
    priority                    = 100
    http_listener_name          = local.listener_http_name
    redirect_configuration_name = local.redirect_config_name
  }

  request_routing_rule {
    name                        = local.routing_rule_https_name
    rule_type                   = "Basic"
    priority                    = 200
    http_listener_name          = local.listener_https_name
    backend_address_pool_name   = local.backend_pool_name
    backend_http_settings_name  = local.http_setting_name
  }
}
```

`terraform/modules/app-gateway/outputs.tf`:
```hcl
output "public_ip_address" {
  value = azurerm_public_ip.this.ip_address
}
```

- [ ] **Step 2: Validate**

Run: `cd terraform/modules/app-gateway && terraform init && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add terraform/modules/app-gateway
git commit -m "feat(terraform): add app-gateway module (TLS termination)"
```

---

### Task 10: `environments/dev` root — wire all modules together

**Files:**
- Create: `terraform/environments/dev/backend.tf`
- Create: `terraform/environments/dev/versions.tf`
- Create: `terraform/environments/dev/variables.tf`
- Create: `terraform/environments/dev/main.tf`
- Create: `terraform/environments/dev/outputs.tf`
- Create: `terraform/environments/dev/terraform.tfvars` (non-secret values only)

**Interfaces:**
- Consumes: every module's outputs from Tasks 2-9.
- Produces: the fully wired `dev` environment — the deliverable this whole plan builds toward. `public_endpoint` output is the URL a human hits to smoke-test the deployment (see Task 11).

- [ ] **Step 1: Write backend + provider config**

`terraform/environments/dev/backend.tf`:
```hcl
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-audit-agent-tfstate"
    storage_account_name = "stauditagenttfstate"
    container_name       = "tfstate"
    key                   = "dev.tfstate"
  }
}
```

`terraform/environments/dev/versions.tf`:
```hcl
terraform {
  required_version = ">= 1.7.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = true
    }
  }
  subscription_id = var.subscription_id
}

data "azurerm_client_config" "current" {}
```

- [ ] **Step 2: Write variables**

`terraform/environments/dev/variables.tf`:
```hcl
variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "westeurope"
}

variable "local_ip" {
  description = "Your current dev machine's public IP — allowlisted for jumpbox SSH and Postgres."
  type        = string
}

variable "acr_name" {
  description = "Must be globally unique across Azure, alphanumeric only."
  type        = string
  default     = "acrauditagentdev"
}

variable "key_vault_name" {
  description = "Must be globally unique across Azure."
  type        = string
  default     = "kv-auditagent-dev"
}

variable "postgres_server_name" {
  description = "Must be globally unique across Azure."
  type        = string
  default     = "psql-audit-agent-dev"
}

variable "postgres_admin_password" {
  type      = string
  sensitive = true
}

variable "azure_openai_endpoint" {
  type = string
}

variable "azure_openai_key" {
  type      = string
  sensitive = true
}

variable "azure_openai_deployment" {
  type    = string
  default = "gpt-4.1"
}

variable "sharepoint_service_url" {
  description = "URL of the .NET CSOM sidecar (or, later, the MCP service)."
  type        = string
}

variable "sharepoint_site_url" {
  type = string
}

variable "container_image_tag" {
  description = "Tag of the audit-agent image already pushed to ACR (see .github/workflows/build-and-push.yml)."
  type        = string
  default     = "latest"
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "jumpbox_ssh_public_key" {
  description = "Contents of your SSH public key (e.g. `cat ~/.ssh/id_rsa.pub`), not a file path."
  type        = string
}

variable "appgw_ssl_cert_base64" {
  description = "Base64-encoded PFX certificate for App Gateway TLS termination. See terraform/README.md for how to generate a self-signed one for dev."
  type        = string
  sensitive   = true
}

variable "appgw_ssl_cert_password" {
  type      = string
  sensitive = true
}
```

- [ ] **Step 3: Write root wiring**

`terraform/environments/dev/main.tf`:
```hcl
locals {
  tags = {
    project     = "langgraph-sharepoint-demo"
    environment = "dev"
  }
}

module "resource_group" {
  source   = "../../modules/resource-group"
  name     = "rg-audit-agent-dev"
  location = var.location
  tags     = local.tags
}

resource "azurerm_user_assigned_identity" "audit_agent" {
  name                = "id-audit-agent-dev"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  tags                = local.tags
}

module "networking" {
  source              = "../../modules/networking"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  tags                = local.tags
  local_ip            = var.local_ip
  aci_backend_port    = var.container_port
}

module "keyvault" {
  source                     = "../../modules/keyvault"
  name                       = var.key_vault_name
  resource_group_name        = module.resource_group.name
  location                   = module.resource_group.location
  tags                       = local.tags
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  caller_object_id           = data.azurerm_client_config.current.object_id
  app_identity_principal_id  = azurerm_user_assigned_identity.audit_agent.principal_id
}

resource "azurerm_key_vault_secret" "postgres_password" {
  name         = "postgres-password"
  value        = var.postgres_admin_password
  key_vault_id = module.keyvault.id
}

resource "azurerm_key_vault_secret" "azure_openai_key" {
  name         = "azure-openai-key"
  value        = var.azure_openai_key
  key_vault_id = module.keyvault.id
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-audit-agent-dev"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_application_insights" "this" {
  name                = "appi-audit-agent-dev"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"
  tags                = local.tags
}

resource "azurerm_key_vault_secret" "appinsights_connection_string" {
  name         = "appinsights-connection-string"
  value        = azurerm_application_insights.this.connection_string
  key_vault_id = module.keyvault.id
}

module "acr" {
  source                      = "../../modules/acr"
  name                        = var.acr_name
  resource_group_name         = module.resource_group.name
  location                    = module.resource_group.location
  tags                        = local.tags
  pull_identity_principal_id  = azurerm_user_assigned_identity.audit_agent.principal_id
}

module "postgres" {
  source                  = "../../modules/postgres"
  name                    = var.postgres_server_name
  resource_group_name     = module.resource_group.name
  location                = module.resource_group.location
  tags                    = local.tags
  administrator_password  = var.postgres_admin_password
  allowed_ip              = var.local_ip
}

module "jumpbox" {
  source              = "../../modules/jumpbox"
  name                = "vm-jumpbox-audit-agent-dev"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  tags                = local.tags
  subnet_id           = module.networking.jumpbox_subnet_id
  ssh_public_key      = var.jumpbox_ssh_public_key
}

module "audit_agent" {
  source              = "../../modules/container-group"
  name                = "aci-audit-agent-dev"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  tags                = local.tags
  subnet_id           = module.networking.aci_subnet_id
  identity_id         = azurerm_user_assigned_identity.audit_agent.id
  image               = "${module.acr.login_server}/audit-agent:${var.container_image_tag}"
  port                = var.container_port

  environment_variables = {
    AZURE_OPENAI_ENDPOINT   = var.azure_openai_endpoint
    AZURE_OPENAI_DEPLOYMENT = var.azure_openai_deployment
    SHAREPOINT_SERVICE_URL  = var.sharepoint_service_url
    SHAREPOINT_SITE_URL     = var.sharepoint_site_url
    DB_HOST                 = module.postgres.fqdn
    DB_NAME                 = module.postgres.database_name
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.this.connection_string
  }

  secure_environment_variables = {
    AZURE_OPENAI_API_KEY = var.azure_openai_key
    DB_PASSWORD           = var.postgres_admin_password
  }
}

module "app_gateway" {
  source              = "../../modules/app-gateway"
  name                = "agw-audit-agent-dev"
  resource_group_name = module.resource_group.name
  location            = module.resource_group.location
  tags                = local.tags
  subnet_id           = module.networking.appgw_subnet_id
  backend_ip_address  = module.audit_agent.private_ip_address
  backend_port        = var.container_port
  ssl_cert_base64     = var.appgw_ssl_cert_base64
  ssl_cert_password   = var.appgw_ssl_cert_password
}
```

- [ ] **Step 4: Write outputs and non-secret tfvars**

`terraform/environments/dev/outputs.tf`:
```hcl
output "public_endpoint" {
  value = "https://${module.app_gateway.public_ip_address}"
}

output "jumpbox_public_ip" {
  value = module.jumpbox.public_ip_address
}

output "acr_login_server" {
  value = module.acr.login_server
}
```

`terraform/environments/dev/terraform.tfvars`:
```hcl
location                = "westeurope"
acr_name                = "acrauditagentdev"
key_vault_name          = "kv-auditagent-dev"
postgres_server_name    = "psql-audit-agent-dev"
azure_openai_deployment = "gpt-4.1"
container_image_tag     = "latest"
container_port          = 8000
```

- [ ] **Step 5: Validate (no backend, no real credentials needed)**

Run: `cd terraform/environments/dev && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 6: Commit**

```bash
git add terraform/environments/dev
git commit -m "feat(terraform): wire dev environment from all modules"
```

**Note:** `terraform plan`/`apply` against the real backend and a real Azure subscription is a manual, human-run step — it requires `az login`, the secret-valued vars (`postgres_admin_password`, `azure_openai_key`, `jumpbox_ssh_public_key`, `appgw_ssl_cert_base64`, `appgw_ssl_cert_password`, `local_ip`, `azure_openai_endpoint`, `sharepoint_service_url`, `sharepoint_site_url`) supplied via `TF_VAR_*` or a gitignored `secrets.auto.tfvars`, and Task 1's bootstrap already applied. This plan does not execute it.

---

### Task 11: Docs — `terraform/README.md` + update project `README.md`

**Files:**
- Create: `terraform/README.md`
- Modify: `README.md` (the "Deployment path" section, currently lines 102-110)

**Interfaces:** None — documentation only, no code interfaces.

- [ ] **Step 1: Write `terraform/README.md`**

```markdown
# Terraform — langgraph-sharepoint-demo infrastructure

## One-time setup

1. Bootstrap remote state (creates the storage account Terraform itself will
   use — run once, ever, per subscription):

   \`\`\`bash
   cd terraform/bootstrap
   terraform init
   terraform apply -var subscription_id=<your-subscription-id>
   \`\`\`

2. Generate a self-signed TLS cert for the dev App Gateway:

   \`\`\`bash
   openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes \
     -subj "/CN=audit-agent-dev"
   openssl pkcs12 -export -out cert.pfx -inkey key.pem -in cert.pem -passout pass:<choose-a-password>
   base64 -w0 cert.pfx  # -> use as TF_VAR_appgw_ssl_cert_base64
   \`\`\`

   Delete `key.pem`, `cert.pem`, `cert.pfx` after copying the base64 output —
   don't commit them.

## Deploying `dev`

\`\`\`bash
cd terraform/environments/dev
az login
export TF_VAR_subscription_id=<your-subscription-id>
export TF_VAR_local_ip=<your-public-ip>
export TF_VAR_postgres_admin_password=<...>
export TF_VAR_azure_openai_endpoint=<...>
export TF_VAR_azure_openai_key=<...>
export TF_VAR_sharepoint_service_url=<...>
export TF_VAR_sharepoint_site_url=<...>
export TF_VAR_jumpbox_ssh_public_key="$(cat ~/.ssh/id_rsa.pub)"
export TF_VAR_appgw_ssl_cert_base64=<from step 2>
export TF_VAR_appgw_ssl_cert_password=<from step 2>

terraform init
terraform plan
terraform apply
```

## Validating any module standalone

\`\`\`bash
cd terraform/modules/<module-name>
terraform init
terraform validate
\`\`\`

## Adding a new environment (e.g. `prod`)

Copy `environments/dev/` to `environments/prod/`, change `backend.tf`'s `key`
to `prod.tfstate`, adjust `terraform.tfvars`. No changes needed in `modules/`.
```

- [ ] **Step 2: Update `README.md`'s Deployment path section**

Replace the existing "## Deployment path" section (lines 102-110) with:

```markdown
## Deployment path

1. **Azure Container Instances + Application Gateway** (current stage) — all
   infrastructure is provisioned via Terraform (`terraform/`, see
   `terraform/README.md`). The container image is built and pushed to ACR by
   `.github/workflows/build-and-push.yml`; Terraform then deploys it into an
   ACI container group fronted by an Application Gateway (TLS termination,
   public ingress), with a private-VNet Postgres-backed checkpointer and
   secrets in Key Vault.
2. **Azure AI Foundry Hosted Agent** (future migration, currently preview) —
   same image, redeploy via `az cognitiveservices agent` / `azd ai agent
   init`, swap `AZURE_OPENAI_ENDPOINT` env var for the Foundry-injected
   `FOUNDRY_PROJECT_ENDPOINT`, and move SharePoint access behind the Foundry
   Toolbox MCP endpoint instead of a direct service call.
```

- [ ] **Step 3: Commit**

```bash
git add terraform/README.md README.md
git commit -m "docs: document terraform deployment, update README deployment path"
```

---

## Post-plan follow-ups (not part of this plan)

- Swap `MemorySaver` for `AsyncPostgresSaver` in `app/graph.py` so the
  container actually uses the Postgres instance this plan provisions
  (tracked in README's existing TODO list — app-code change, not IaC).
- SharePoint MCP microservice: a second instantiation of
  `modules/container-group` in `environments/dev/main.tf`, plus its own image
  build pipeline — separate spec/plan per the earlier scope decision.
- CI automation of `terraform plan`/`apply` — explicitly deferred per the
  design spec.
