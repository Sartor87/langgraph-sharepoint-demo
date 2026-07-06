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
