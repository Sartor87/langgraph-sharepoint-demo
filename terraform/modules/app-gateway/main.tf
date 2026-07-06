resource "azurerm_public_ip" "this" {
  name                = "pip-${var.name}"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

locals {
  backend_pool_name        = "backend-audit-agent"
  frontend_port_http_name  = "frontend-port-80"
  frontend_port_https_name = "frontend-port-443"
  frontend_ip_name         = "frontend-ip-public"
  http_setting_name        = "http-setting-audit-agent"
  listener_http_name       = "listener-http"
  listener_https_name      = "listener-https"
  redirect_config_name     = "redirect-http-to-https"
  routing_rule_http_name   = "rule-http-redirect"
  routing_rule_https_name  = "rule-https-to-audit-agent"
  health_probe_name        = "probe-audit-agent"
  ssl_cert_name            = "audit-agent-cert"
}

resource "azurerm_application_gateway" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags

  sku {
    name     = "Standard_v2"
    tier     = "Standard_v2"
    capacity = 1
  }

  ssl_policy {
    policy_type = "Predefined"
    policy_name = "AppGwSslPolicy20220101"
  }

  gateway_ip_configuration {
    name      = "appgw-ip-config"
    subnet_id = var.subnet_id
  }

  frontend_ip_configuration {
    name                 = local.frontend_ip_name
    public_ip_address_id = azurerm_public_ip.this.id
  }

  frontend_port {
    name = local.frontend_port_http_name
    port = 80
  }

  frontend_port {
    name = local.frontend_port_https_name
    port = 443
  }

  ssl_certificate {
    name     = local.ssl_cert_name
    data     = var.ssl_cert_base64
    password = var.ssl_cert_password
  }

  backend_address_pool {
    name         = local.backend_pool_name
    ip_addresses = [var.backend_ip_address]
  }

  probe {
    name                = local.health_probe_name
    protocol            = "Http"
    host                = "127.0.0.1"
    path                = var.health_probe_path
    interval            = 30
    timeout             = 10
    unhealthy_threshold = 3

    match {
      status_code = ["200-399"]
    }
  }

  backend_http_settings {
    name                  = local.http_setting_name
    cookie_based_affinity = "Disabled"
    port                  = var.backend_port
    protocol              = "Http"
    request_timeout       = 60

    pick_host_name_from_backend_address = true
    probe_name                          = local.health_probe_name
  }

  http_listener {
    name                           = local.listener_http_name
    frontend_ip_configuration_name = local.frontend_ip_name
    frontend_port_name             = local.frontend_port_http_name
    protocol                       = "Http"
  }

  http_listener {
    name                           = local.listener_https_name
    frontend_ip_configuration_name = local.frontend_ip_name
    frontend_port_name             = local.frontend_port_https_name
    protocol                       = "Https"
    ssl_certificate_name           = local.ssl_cert_name
  }

  redirect_configuration {
    name                 = local.redirect_config_name
    redirect_type        = "Permanent"
    target_listener_name = local.listener_https_name
    include_path         = true
    include_query_string = true
  }

  request_routing_rule {
    name                        = local.routing_rule_http_name
    rule_type                   = "Basic"
    priority                    = 100
    http_listener_name          = local.listener_http_name
    redirect_configuration_name = local.redirect_config_name
  }

  request_routing_rule {
    name                       = local.routing_rule_https_name
    rule_type                  = "Basic"
    priority                   = 200
    http_listener_name         = local.listener_https_name
    backend_address_pool_name  = local.backend_pool_name
    backend_http_settings_name = local.http_setting_name
  }
}
