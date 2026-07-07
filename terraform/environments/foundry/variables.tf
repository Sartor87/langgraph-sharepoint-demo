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
