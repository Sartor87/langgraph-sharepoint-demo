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
  source                    = "../../modules/keyvault"
  name                      = var.key_vault_name
  resource_group_name       = module.resource_group.name
  location                  = module.resource_group.location
  tags                      = local.tags
  tenant_id                 = data.azurerm_client_config.current.tenant_id
  caller_object_id          = data.azurerm_client_config.current.object_id
  app_identity_principal_id = azurerm_user_assigned_identity.audit_agent.principal_id
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
  source                     = "../../modules/acr"
  name                       = var.acr_name
  resource_group_name        = module.resource_group.name
  location                   = module.resource_group.location
  tags                       = local.tags
  pull_identity_principal_id = azurerm_user_assigned_identity.audit_agent.principal_id
}

module "postgres" {
  source                 = "../../modules/postgres"
  name                   = var.postgres_server_name
  resource_group_name    = module.resource_group.name
  location               = module.resource_group.location
  tags                   = local.tags
  administrator_password = var.postgres_admin_password
  subnet_id              = module.networking.postgres_subnet_id
  private_dns_zone_id    = module.networking.postgres_private_dns_zone_id

  depends_on = [module.networking]
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
    AZURE_OPENAI_ENDPOINT                 = var.azure_openai_endpoint
    AZURE_OPENAI_DEPLOYMENT               = var.azure_openai_deployment
    SHAREPOINT_SERVICE_URL                = var.sharepoint_service_url
    SHAREPOINT_SITE_URL                   = var.sharepoint_site_url
    DB_HOST                               = module.postgres.fqdn
    DB_NAME                               = module.postgres.database_name
    APPLICATIONINSIGHTS_CONNECTION_STRING = azurerm_application_insights.this.connection_string
  }

  secure_environment_variables = {
    AZURE_OPENAI_API_KEY = var.azure_openai_key
    DB_PASSWORD          = var.postgres_admin_password
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
