output "public_endpoint" {
  value = "https://${module.app_gateway.public_ip_address}"
}

output "jumpbox_public_ip" {
  value = module.jumpbox.public_ip_address
}

output "postgres_fqdn" {
  value = module.postgres.fqdn
}

output "acr_login_server" {
  value = module.acr.login_server
}

output "sharepoint_function_hostname" {
  value = module.sharepoint_function.default_hostname
}
