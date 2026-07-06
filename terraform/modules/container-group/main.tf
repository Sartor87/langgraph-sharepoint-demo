resource "azurerm_container_group" "this" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  os_type             = "Linux"
  restart_policy      = "Always"
  tags                = var.tags

  subnet_ids = [var.subnet_id]

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  image_registry_credential {
    server                    = split("/", var.image)[0]
    user_assigned_identity_id = var.identity_id
  }

  ip_address_type = "Private"

  exposed_port {
    port     = var.port
    protocol = "TCP"
  }

  container {
    name   = "app"
    image  = var.image
    cpu    = var.cpu
    memory = var.memory_gb

    ports {
      port     = var.port
      protocol = "TCP"
    }

    environment_variables        = var.environment_variables
    secure_environment_variables = var.secure_environment_variables
  }
}
