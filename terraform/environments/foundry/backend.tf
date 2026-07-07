terraform {
  backend "azurerm" {
    resource_group_name  = "rg-audit-agent-tfstate"
    storage_account_name = "stauditagenttfstate"
    container_name       = "tfstate"
    key                  = "foundry.tfstate"
  }
}
