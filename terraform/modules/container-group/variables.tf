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

variable "identity_id" {
  type = string
}

variable "image" {
  type = string
}

variable "port" {
  type = number
}

variable "cpu" {
  type    = number
  default = 1
}

variable "memory_gb" {
  type    = number
  default = 2
}

variable "environment_variables" {
  type    = map(string)
  default = {}
}

variable "secure_environment_variables" {
  type      = map(string)
  default   = {}
  sensitive = true
}
