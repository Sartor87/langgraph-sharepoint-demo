variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "westeurope"
}

variable "local_ip" {
  description = "Your current dev machine's public IP — allowlisted for jumpbox SSH. Postgres has no public endpoint; reach it through the jumpbox tunnel (see README.md)."
  type        = string
}

variable "acr_name" {
  description = "Must be globally unique across Azure, alphanumeric only."
  type        = string
  default     = "acrauditagentdev"
}

variable "key_vault_name" {
  description = "Must be globally unique across Azure."
  type        = string
  default     = "kv-auditagent-dev"
}

variable "postgres_server_name" {
  description = "Must be globally unique across Azure."
  type        = string
  default     = "psql-audit-agent-dev"
}

variable "postgres_admin_password" {
  type      = string
  sensitive = true
}

variable "azure_openai_endpoint" {
  type = string
}

variable "azure_openai_key" {
  type      = string
  sensitive = true
}

variable "azure_openai_deployment" {
  type    = string
  default = "gpt-4.1"
}

variable "sharepoint_service_url" {
  description = "URL of the .NET CSOM sidecar (or, later, the MCP service)."
  type        = string
}

variable "sharepoint_site_url" {
  type = string
}

variable "container_image_tag" {
  description = "Tag of the audit-agent image already pushed to ACR (see .github/workflows/build-and-push.yml)."
  type        = string
  default     = "latest"
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "jumpbox_ssh_public_key" {
  description = "Contents of your SSH public key (e.g. `cat ~/.ssh/id_rsa.pub`), not a file path."
  type        = string
}

variable "appgw_ssl_cert_base64" {
  description = "Base64-encoded PFX certificate for App Gateway TLS termination. See terraform/README.md for how to generate a self-signed one for dev."
  type        = string
  sensitive   = true
}

variable "appgw_ssl_cert_password" {
  type      = string
  sensitive = true
}
