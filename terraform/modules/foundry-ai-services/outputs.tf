output "cognitive_account_id" {
  value = azurerm_cognitive_account.this.id
}

output "foundry_project_endpoint" {
  value = "https://${var.custom_subdomain_name}.services.ai.azure.com/api/projects/${var.project_name}"
}
