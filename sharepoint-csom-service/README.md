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

```bash
curl -X POST http://localhost:7071/search \
  -H "Content-Type: application/json" \
  -d '{"query":"policy","site_url":"https://tenant.sharepoint.com/sites/example","max_results":5}'
```

## Prerequisites for a real deployment

- The Function App's Managed Identity must be granted a SharePoint API
  permission (`Sites.Selected` or `Sites.Read.All`) — a manual Entra admin
  consent step, not automated here.
- Infrastructure (the Function App resource itself, Managed Identity
  assignment) is a separate, later piece of work — this repo currently
  only has the function's code.

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
