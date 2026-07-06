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

variable "local_ip" {
  description = "CIDR or single IP allowed to reach jumpbox SSH and Postgres (dev allowlist)."
  type        = string
}

variable "aci_backend_port" {
  description = "Port the audit-agent container listens on (must match docker/Dockerfile's uvicorn --port)."
  type        = number
  default     = 8000
}
