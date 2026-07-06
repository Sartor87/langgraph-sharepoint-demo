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

variable "administrator_password" {
  type      = string
  sensitive = true
}

variable "database_name" {
  type    = string
  default = "langgraph_checkpoints"
}

variable "subnet_id" {
  description = "Delegated subnet (Microsoft.DBforPostgreSQL/flexibleServers) for private VNet integration."
  type        = string
}

variable "private_dns_zone_id" {
  description = "Private DNS zone (privatelink.postgres.database.azure.com) linked to the VNet."
  type        = string
}
