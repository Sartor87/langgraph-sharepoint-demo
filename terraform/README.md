# Terraform — langgraph-sharepoint-demo infrastructure

## One-time setup

1. Bootstrap remote state (creates the storage account Terraform itself will
   use — run once, ever, per subscription):

   ```bash
   cd terraform/bootstrap
   terraform init
   terraform apply -var subscription_id=<your-subscription-id>
   ```

2. Generate a self-signed TLS cert for the dev App Gateway:

   ```bash
   openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes \
     -subj "/CN=audit-agent-dev"
   openssl pkcs12 -export -out cert.pfx -inkey key.pem -in cert.pem -passout pass:<choose-a-password>
   base64 -w0 cert.pfx  # -> use as TF_VAR_appgw_ssl_cert_base64
   ```

   Delete `key.pem`, `cert.pem`, `cert.pfx` after copying the base64 output —
   don't commit them.

## Deploying `dev`

```bash
cd terraform/environments/dev
az login
export TF_VAR_subscription_id=<your-subscription-id>
export TF_VAR_local_ip=<your-public-ip>
export TF_VAR_postgres_admin_password=<...>
export TF_VAR_azure_openai_endpoint=<...>
export TF_VAR_azure_openai_key=<...>
export TF_VAR_sharepoint_service_url=<...>
export TF_VAR_sharepoint_site_url=<...>
export TF_VAR_jumpbox_ssh_public_key="$(cat ~/.ssh/id_rsa.pub)"
export TF_VAR_appgw_ssl_cert_base64=<from step 2>
export TF_VAR_appgw_ssl_cert_password=<from step 2>

terraform init
terraform plan
terraform apply
```

## Validating any module standalone

```bash
cd terraform/modules/<module-name>
terraform init
terraform validate
```

## Adding a new environment (e.g. `prod`)

Copy `environments/dev/` to `environments/prod/`, change `backend.tf`'s `key`
to `prod.tfstate`, adjust `terraform.tfvars`. No changes needed in `modules/`.
