resource "azurerm_storage_account" "this" {
  # Storage account names are capped at 24 lowercase-alphanumeric chars;
  # truncate rather than fail for longer function-app names.
  name                     = substr("st${replace(var.name, "-", "")}", 0, 24)
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
