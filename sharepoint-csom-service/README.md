# sharepoint-csom-service

Azure Function (isolated worker, .NET) implementing SharePoint search for
this project's audit agent, using PnP Core SDK's search API
(`context.Web.SearchAsync`), authenticated via the Function's Managed
Identity.

This is the default backend for `app/tools/sharepoint_tool.py`
(`SHAREPOINT_TOOL_BACKEND=azure_function`, the default). A second,
unimplemented ".NET CSOM/PnP Framework sidecar" path is kept as a
config-selectable "explore" alternative — see that module's docstring.

## Local development

```bash
cd sharepoint-csom-service
cp local.settings.json.example local.settings.json
func start
```

`func start` serves on `http://localhost:7071`. The route is `/search`
(not `/api/search` — `host.json` sets `routePrefix` to empty for contract
parity with the Python-side stub).

Note: if you instead run/debug via `dotnet run` or F5 (see
`Properties/launchSettings.json`), the function serves on port `7012`
instead of `7071` — adjust the URL below accordingly.

```bash
curl -X POST http://localhost:7071/search \
  -H "Content-Type: application/json" \
  -d '{"query":"policy","site_url":"https://tenant.sharepoint.com/sites/example","max_results":5}'
```

## Prerequisites for a real deployment

Once `terraform apply` has created the Function App and its dedicated
identity (`id-sharepoint-function-dev`), grant that identity SharePoint
access — this is a two-part manual process with no Terraform equivalent for
the second part:

1. **Grant the Microsoft Graph `Sites.Selected` application permission** to
   the identity's service principal (Azure Portal → Microsoft Entra ID →
   Enterprise Applications → find `id-sharepoint-function-dev` → API
   permissions → Add a permission → Microsoft Graph → Application
   permissions → `Sites.Selected` → Grant admin consent). This can
   technically be scripted via the `azuread` Terraform provider, but is done
   manually here to keep the whole grant in one place (see step 2).

2. **Scope that permission to the specific SharePoint site** the Function
   should access — there is no Terraform/ARM resource for this at all; it's
   a Microsoft Graph API call. The standard tool is PnP PowerShell:

   ```powershell
   Install-Module -Name PnP.PowerShell -Scope CurrentUser
   Connect-PnPOnline -Url "https://<tenant>.sharepoint.com/sites/<site>" -Interactive

   Grant-PnPAzureADAppSitePermission `
     -AppId "<the identity's client/application ID, from the Enterprise Application's Overview page>" `
     -DisplayName "id-sharepoint-function-dev" `
     -Site "https://<tenant>.sharepoint.com/sites/<site>" `
     -Permissions Read
   ```

   Use `-Permissions Write` instead (or in addition) if the Function will
   ever need to write back to SharePoint — today it only searches and finds
   files, so `Read` is sufficient.

- Infrastructure (the Function App resource itself, its Storage Account, and
  its dedicated Managed Identity) is provisioned by
  `terraform/environments/dev` (`module.sharepoint_function`) — see that
  module's Terraform for what's created.
- The HTTP trigger declares `AuthorizationLevel.Function`, so once this
  Function is actually deployed, every inbound call must present a
  function key (`x-functions-key` header or `?code=` query param) or it
  will 401. `app/tools/sharepoint_tool.py`'s `search_sharepoint()` does
  not currently send one — wiring a `SHAREPOINT_FUNCTION_KEY` env var
  through as an `x-functions-key` header is separate, not-yet-implemented
  work. This is latent today only because both tool backends raise
  `NotImplementedError` before any HTTP call is made.

## AWS Lambda alternative

This project deploys to Azure, so this function targets Azure Functions.
The PnP Core SDK code itself (the search logic in `Functions/SearchFunction.cs`)
isn't Azure-Functions-specific — the same PnP Core SDK calls would work
inside an AWS Lambda handler for an AWS-hosted deployment of this project,
swapping the HTTP trigger binding and the Managed-Identity auth bridge for
Lambda's equivalent (e.g. an IAM role via an AWS-side credential bridge, or
a different auth provider entirely, since Managed Identity is Azure-specific).
This is a documentation note only — no Lambda implementation exists in
this repo.
