variable "account_name" {
  description = "Name of the existing Cognitive Services (AIServices) account to import."
  type        = string
}

variable "project_name" {
  description = "Name of the existing Foundry project under the account to import."
  type        = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "custom_subdomain_name" {
  description = "The account's custom subdomain (usually matches account_name) — used to construct the Foundry project endpoint."
  type        = string
}

variable "sku_name" {
  type    = string
  default = "S0"
}

variable "public_network_access_enabled" {
  type    = bool
  default = true
}

variable "local_auth_enabled" {
  type    = bool
  default = true
}

variable "dynamic_throttling_enabled" {
  type    = bool
  default = false
}

variable "project_management_enabled" {
  type    = bool
  default = true
}

variable "outbound_network_access_restricted" {
  type    = bool
  default = false
}

variable "network_acls_bypass" {
  description = "Azure's real default is \"AzureServices\" — the exported config's empty string is not a valid value for this field."
  type        = string
  default     = "AzureServices"
}

variable "network_acls_default_action" {
  type    = string
  default = "Allow"
}

variable "project_description" {
  type    = string
  default = ""
}

variable "project_display_name" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
