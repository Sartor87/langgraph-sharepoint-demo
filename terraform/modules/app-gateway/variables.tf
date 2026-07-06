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

variable "subnet_id" {
  type = string
}

variable "backend_ip_address" {
  type = string
}

variable "backend_port" {
  type = number
}

variable "ssl_cert_base64" {
  type      = string
  sensitive = true
}

variable "ssl_cert_password" {
  type      = string
  sensitive = true
}

variable "health_probe_path" {
  type    = string
  default = "/health"
}
