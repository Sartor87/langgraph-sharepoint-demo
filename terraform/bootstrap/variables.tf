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
