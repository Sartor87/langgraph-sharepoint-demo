output "vnet_id" {
  value = azurerm_virtual_network.this.id
}

output "aci_subnet_id" {
  value = azurerm_subnet.aci.id
}

output "postgres_subnet_id" {
  value = azurerm_subnet.postgres.id
}

output "jumpbox_subnet_id" {
  value = azurerm_subnet.jumpbox.id
}

output "appgw_subnet_id" {
  value = azurerm_subnet.appgw.id
}

output "postgres_private_dns_zone_id" {
  value = azurerm_private_dns_zone.postgres.id
}
