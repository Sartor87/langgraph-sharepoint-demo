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
