resource "azurerm_cognitive_account" "this" {
  name                = var.account_name
  resource_group_name = var.resource_group_name
  location            = var.location
  kind                = "AIServices"
  sku_name            = var.sku_name

  custom_subdomain_name              = var.custom_subdomain_name
  public_network_access_enabled      = var.public_network_access_enabled
  local_auth_enabled                 = var.local_auth_enabled
  dynamic_throttling_enabled         = var.dynamic_throttling_enabled
  project_management_enabled         = var.project_management_enabled
  outbound_network_access_restricted = var.outbound_network_access_restricted

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
