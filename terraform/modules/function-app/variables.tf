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

variable "identity_id" {
  description = "Resource ID of the user-assigned identity to attach to the Function App."
  type        = string
}

variable "identity_principal_id" {
  description = "Principal ID of the same identity — used for the storage role assignments."
  type        = string
}

variable "dotnet_version" {
  type    = string
  default = "10.0"
}
