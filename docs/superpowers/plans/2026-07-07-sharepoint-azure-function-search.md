# SharePoint Azure Function Search Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real C# Azure Function (`sharepoint-csom-service/`) implementing SharePoint search via PnP Core SDK, authenticating with Managed Identity, matching the existing Python stub's HTTP contract exactly — and make the Python-side tool config-selectable between this new backend and the existing (still-unimplemented) `.NET CSOM/PnP Framework sidecar` stub.

**Architecture:** An Azure Functions isolated-worker (.NET, `net10.0`) HTTP-triggered function calls PnP Core SDK's `Web.SearchAsync()` against a site, mapping results into the existing `documents[]` contract. Since PnP Core SDK's Auth package has no built-in Managed Identity provider, auth goes through `PnP.Core.Auth.ExternalAuthenticationProvider` — PnP Core SDK's documented escape hatch for plugging in an arbitrary token-acquisition callback — wired to `Azure.Identity`'s `ManagedIdentityCredential`. `app/tools/sharepoint_tool.py` gains a `backend` parameter (env-var-driven, not LLM-tool-calling-driven) routing to either this Function or the existing stub, both sharing one HTTP-calling code path since the contract is identical.

**Tech Stack:** Azure Functions Core Tools 4.x, .NET `net10.0` isolated worker, `PnP.Core` 1.16.0, `PnP.Core.Auth` 1.16.0, `Azure.Identity`, Python `httpx` (existing dependency), pytest.

## Global Constraints

- Response/request contract for BOTH backends is identical: `POST /search {query, site_url, max_results} -> {documents: [{doc_id, title, url, content_snippet, last_modified, library, metadata}]}`.
- Azure Function's HTTP route must be exactly `/search` (no `/api` prefix) — set via `host.json`'s `extensions.http.routePrefix = ""`.
- Auth: Managed Identity via PnP Core SDK's `ExternalAuthenticationProvider` (confirmed via real package inspection — `PnP.Core.Auth` 1.16.0 has NO built-in `ManagedIdentity*` provider class; available providers are `Certificate`, `CredentialManager`, `DeviceCode`, `External`, `Interactive`, `OnBehalfOf`, `UsernamePassword`, `AspNetCore`. `External` is the correct, PnP-documented mechanism for supplying a custom token callback).
- No cert/secret management — the Function's own Managed Identity is what SharePoint sees, once granted a `Sites.Selected`/`Sites.Read.All` permission (manual, human-run Entra admin-consent step — not automated by any task here).
- `backend` selection in `app/tools/sharepoint_tool.py` is env-var-driven (`SHAREPOINT_TOOL_BACKEND`, default `"azure_function"`), NOT LLM tool-calling — `app/nodes/agent1_search.py` stays an unmodified, fixed deterministic node.
- Public repo — `local.settings.json.example` and all committed files use placeholder values only, no real tenant/site/subscription identifiers.
- Terraform/infrastructure for deploying the Function App is explicitly out of scope — a separate, later spec/plan.
- No AWS Lambda implementation — `sharepoint-csom-service/README.md` gets a documentation-only note that this PnP Core SDK code is portable to Lambda for AWS-hosted deployments.

---

### Task 1: Scaffold the Azure Function project (real tooling, not hand-authored)

**Files:**
- Create: `sharepoint-csom-service/SharePointSearchFunction.csproj`
- Create: `sharepoint-csom-service/host.json`
- Create: `sharepoint-csom-service/local.settings.json.example`
- Create: `sharepoint-csom-service/Program.cs`
- Create: `sharepoint-csom-service/.gitignore` (Azure Functions Core Tools generates one; keep it — it excludes `bin/`, `obj/`, `local.settings.json`)

**Interfaces:**
- Produces: a buildable Azure Functions isolated-worker project skeleton (no PnP Core SDK yet — that's Task 2) that Task 2 adds an HTTP-triggered function to.

- [ ] **Step 1: Scaffold with the real Azure Functions Core Tools**

Run (from the repo root):
```bash
mkdir sharepoint-csom-service
cd sharepoint-csom-service
func init . --worker-runtime dotnet-isolated --target-framework net10.0
```

This generates `SharePointSearchFunction.csproj` (or a name derived from the directory — rename the `.csproj` file to `SharePointSearchFunction.csproj` and update its `RootNamespace` if `func init` picked a different name), `host.json`, `local.settings.json`, `Program.cs`, `.gitignore`, and a `Properties/` folder. The generated `.csproj` will look like this (confirmed by actually running this scaffold command during planning):

```xml
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <AzureFunctionsVersion>v4</AzureFunctionsVersion>
    <OutputType>Exe</OutputType>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <RootNamespace>SharePointSearchFunction</RootNamespace>
  </PropertyGroup>

  <ItemGroup>
    <FrameworkReference Include="Microsoft.AspNetCore.App" />
    <PackageReference Include="Microsoft.ApplicationInsights.WorkerService" Version="2.23.0" />
    <PackageReference Include="Microsoft.Azure.Functions.Worker" Version="2.51.0" />
    <PackageReference Include="Microsoft.Azure.Functions.Worker.ApplicationInsights" Version="2.50.0" />
    <PackageReference Include="Microsoft.Azure.Functions.Worker.Extensions.Http.AspNetCore" Version="2.1.0" />
    <PackageReference Include="Microsoft.Azure.Functions.Worker.Sdk" Version="2.0.7" />
  </ItemGroup>

</Project>
```

(Package versions may have moved forward slightly since this plan was written — that's fine, `func init` always pulls current versions; don't hand-edit them to match this exact snapshot.)

- [ ] **Step 2: Set `routePrefix` to empty in `host.json`**

Replace the generated `host.json` with:

```json
{
    "version": "2.0",
    "extensions": {
        "http": {
            "routePrefix": ""
        }
    },
    "logging": {
        "applicationInsights": {
            "samplingSettings": {
                "isEnabled": true,
                "excludedTypes": "Request"
            },
            "enableLiveMetricsFilters": true
        }
    }
}
```

(This makes the eventual `Search` function's route exactly `/search`, not `/api/search` — required for contract parity with the Python stub's `{base_url}/search` calling convention.)

- [ ] **Step 3: Create `local.settings.json.example`, gitignore the real one**

`func init` already generates `local.settings.json` with local-only dummy values (`AzureWebJobsStorage: "UseDevelopmentStorage=true"`) — copy it to `local.settings.json.example` for the repo (this file IS meant to be committed, as a template), and confirm `local.settings.json` itself is in `.gitignore` (it is, by default, from `func init`'s generated `.gitignore` — verify this, don't assume).

`sharepoint-csom-service/local.settings.json.example`:
```json
{
    "IsEncrypted": false,
    "Values": {
        "AzureWebJobsStorage": "UseDevelopmentStorage=true",
        "FUNCTIONS_WORKER_RUNTIME": "dotnet-isolated"
    }
}
```

- [ ] **Step 4: Build to confirm the skeleton compiles**

Run: `cd sharepoint-csom-service && dotnet build`
Expected: `Build succeeded.` with 0 errors.

- [ ] **Step 5: Commit**

```bash
git add sharepoint-csom-service/SharePointSearchFunction.csproj sharepoint-csom-service/host.json sharepoint-csom-service/local.settings.json.example sharepoint-csom-service/Program.cs sharepoint-csom-service/.gitignore sharepoint-csom-service/Properties
git commit -m "feat: scaffold sharepoint-csom-service Azure Function (isolated worker, net10.0)"
```

(Do NOT add `bin/`, `obj/`, or `local.settings.json` — confirm `git status` shows none of these as staged before committing; `sharepoint-csom-service/.gitignore` should already exclude them.)

---

### Task 2: PnP Core SDK search function with Managed Identity auth (discovery-heavy)

**Files:**
- Modify: `sharepoint-csom-service/SharePointSearchFunction.csproj` (add `PnP.Core`, `PnP.Core.Auth`, `Azure.Identity` package references)
- Create: `sharepoint-csom-service/Models/SearchRequest.cs`
- Create: `sharepoint-csom-service/Models/SearchResponse.cs`
- Create: `sharepoint-csom-service/Models/DocumentResult.cs`
- Create: `sharepoint-csom-service/Functions/SearchFunction.cs`
- Modify: `sharepoint-csom-service/Program.cs` (register PnP Core SDK + the Managed Identity auth bridge in DI)

**Interfaces:**
- Produces: `POST /search` matching the Python stub's exact contract — consumed by Task 3.

**Why this task looks different from the others:** PnP Core SDK's `PnP.Core.Auth` package (confirmed via direct inspection of the real 1.16.0 assembly during planning — grepping `PnP.Core.Auth.dll`'s metadata strings for provider type names) has **no built-in Managed Identity authentication provider**. The real available provider types are: `CertificateAuthenticationProvider`, `CredentialManagerAuthenticationProvider`, `DeviceCodeAuthenticationProvider`, `ExternalAuthenticationProvider`, `InteractiveAuthenticationProvider`, `OnBehalfOfAuthenticationProvider`, `UsernamePasswordAuthenticationProvider`, `AspNetCoreAuthenticationProvider`. `ExternalAuthenticationProvider` is PnP Core SDK's documented mechanism for bridging in an arbitrary token-acquisition callback — this is the one to use, wrapping `Azure.Identity`'s `ManagedIdentityCredential`. Its exact constructor/delegate signature was NOT fully confirmed during planning (the reflection check to pin it down didn't complete in time) — **Step 1 below has the implementer confirm it against the real installed package before writing the DI registration code.**

- [ ] **Step 1: Add the packages and inspect `ExternalAuthenticationProvider`'s real API**

Run:
```bash
cd sharepoint-csom-service
dotnet add package PnP.Core --version 1.16.0
dotnet add package PnP.Core.Auth --version 1.16.0
dotnet add package Azure.Identity
```

Then inspect the real constructor/delegate signature. The most reliable way: write a tiny throwaway console snippet (NOT committed) that reflects over the type, e.g.:

```bash
mkdir /tmp/pnp-inspect && cd /tmp/pnp-inspect
dotnet new console
dotnet add package PnP.Core.Auth --version 1.16.0
```

Replace the generated `Program.cs` with:
```csharp
using System.Reflection;
var asm = Assembly.Load("PnP.Core.Auth");
var type = asm.GetType("PnP.Core.Auth.ExternalAuthenticationProvider")!;
foreach (var ctor in type.GetConstructors())
    Console.WriteLine("CTOR: " + ctor);
foreach (var m in type.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly))
    Console.WriteLine("METHOD: " + m);
```

Run: `dotnet run`
Record the printed constructor/method signatures in your task report — this tells you the exact delegate type `ExternalAuthenticationProvider` expects for its token-acquisition callback (PnP Core SDK's own docs describe this pattern as taking a callback shaped like `Func<string, string[], CancellationToken, Task<string>>` — a resource/scopes-in, access-token-out function — but confirm the REAL signature from the reflection output rather than trusting that description). Delete `/tmp/pnp-inspect` when done — it's not part of this repo.

If `ExternalAuthenticationProvider` turns out not to exist or not to work this way in the real 1.16.0 package (contradicting what was found during planning), report BLOCKED with what you actually found — don't fabricate a workaround.

- [ ] **Step 2: Write the models**

`sharepoint-csom-service/Models/SearchRequest.cs`:
```csharp
namespace SharePointSearchFunction.Models;

public class SearchRequest
{
    public string Query { get; set; } = string.Empty;
    public string SiteUrl { get; set; } = string.Empty;
    public int MaxResults { get; set; } = 20;
}
```

`sharepoint-csom-service/Models/DocumentResult.cs`:
```csharp
namespace SharePointSearchFunction.Models;

public class DocumentResult
{
    public string DocId { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string Url { get; set; } = string.Empty;
    public string ContentSnippet { get; set; } = string.Empty;
    public string LastModified { get; set; } = string.Empty;
    public string Library { get; set; } = string.Empty;
    public Dictionary<string, object?> Metadata { get; set; } = new();
}
```

`sharepoint-csom-service/Models/SearchResponse.cs`:
```csharp
namespace SharePointSearchFunction.Models;

public class SearchResponse
{
    public List<DocumentResult> Documents { get; set; } = new();
}
```

Note: the Python side expects JSON keys in `snake_case` (`doc_id`, `content_snippet`, `last_modified`, matching the existing stub's documented contract in `app/tools/sharepoint_tool.py`'s docstring) — Step 4 of this task configures the JSON serializer to convert C#'s `PascalCase` properties to `snake_case` on the wire, so these model classes stay idiomatic C# and don't need `[JsonPropertyName]` attributes on every property.

- [ ] **Step 3: Write the search function**

`sharepoint-csom-service/Functions/SearchFunction.cs`:
```csharp
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Extensions.Logging;
using PnP.Core.Services;
using PnP.Core.QueryModel;
using SharePointSearchFunction.Models;

namespace SharePointSearchFunction.Functions;

public class SearchFunction
{
    private readonly ILogger<SearchFunction> _logger;
    private readonly IPnPContextFactory _pnpContextFactory;

    public SearchFunction(ILogger<SearchFunction> logger, IPnPContextFactory pnpContextFactory)
    {
        _logger = logger;
        _pnpContextFactory = pnpContextFactory;
    }

    [Function("Search")]
    public async Task<IActionResult> Run(
        [HttpTrigger(AuthorizationLevel.Function, "post", Route = "search")] HttpRequest req,
        [FromBody] SearchRequest request)
    {
        if (string.IsNullOrWhiteSpace(request.Query) || string.IsNullOrWhiteSpace(request.SiteUrl))
        {
            return new BadRequestObjectResult(new { error = "query and site_url are required" });
        }

        _logger.LogInformation("Searching {SiteUrl} for '{Query}' (max {MaxResults})",
            request.SiteUrl, request.Query, request.MaxResults);

        using var context = await _pnpContextFactory.CreateAsync(new Uri(request.SiteUrl));

        var searchOptions = new SearchOptions(request.Query)
        {
            TrimDuplicates = false,
            RowLimit = request.MaxResults,
            SelectProperties = new List<string>
            {
                "UniqueId", "Title", "Path", "HitHighlightedSummary", "LastModifiedTime"
            },
        };

        var searchResult = await context.Web.SearchAsync(searchOptions);

        var documents = new List<DocumentResult>();
        foreach (var row in searchResult.Rows)
        {
            var path = row.TryGetValue("Path", out var p) ? p?.ToString() ?? "" : "";
            documents.Add(new DocumentResult
            {
                DocId = row.TryGetValue("UniqueId", out var id) ? id?.ToString() ?? "" : "",
                Title = row.TryGetValue("Title", out var t) ? t?.ToString() ?? "" : "",
                Url = path,
                ContentSnippet = row.TryGetValue("HitHighlightedSummary", out var s) ? s?.ToString() ?? "" : "",
                LastModified = row.TryGetValue("LastModifiedTime", out var lm) ? lm?.ToString() ?? "" : "",
                Library = ExtractLibraryFromPath(path),
                Metadata = row.ToDictionary(kv => kv.Key, kv => (object?)kv.Value),
            });
        }

        return new OkObjectResult(new SearchResponse { Documents = documents });
    }

    private static string ExtractLibraryFromPath(string path)
    {
        // Path shape: https://tenant.sharepoint.com/sites/<site>/<Library>/<file>
        // Extract the library segment; return "" if the path doesn't have enough segments.
        var uri = new Uri(path, UriKind.RelativeOrAbsolute);
        var segments = uri.IsAbsoluteUri
            ? uri.AbsolutePath.Trim('/').Split('/')
            : path.Trim('/').Split('/');
        return segments.Length >= 3 ? segments[2] : "";
    }
}
```

**Note on this step's own discovery risk**: the exact managed property names (`UniqueId`, `Title`, `Path`, `HitHighlightedSummary`, `LastModifiedTime`) and whether `context.Web.SearchAsync` returns rows as `Dictionary<string, object>` with exactly these key casings depends on the real tenant's search schema and the real PnP Core SDK 1.16.0 API — if `dotnet build` (Step 5) fails because `SearchOptions`/`ISearchResult`/`Web.SearchAsync` have different real signatures than shown here, fix based on the actual compiler errors and IntelliSense/`dotnet build` output, not by guessing further — this code is a best-effort based on the PnP Core SDK documentation provided for this project, not independently verified against the real 1.16.0 API surface the way Task 1's Step 1 discovery was.

- [ ] **Step 4: Wire PnP Core SDK + Managed Identity auth in `Program.cs`**

Update `sharepoint-csom-service/Program.cs`. Use the constructor/delegate signature you found in Step 1 to wire `ExternalAuthenticationProvider` to `ManagedIdentityCredential`. The shape should be approximately:

```csharp
using Azure.Identity;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Azure.Functions.Worker.Builder;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using PnP.Core.Auth;
using PnP.Core.Services.Builder.Configuration;
using System.Text.Json;

var builder = FunctionsApplication.CreateBuilder(args);

builder.ConfigureFunctionsWebApplication();

// snake_case JSON to match the Python-side contract
builder.Services.Configure<Microsoft.Azure.Functions.Worker.Http.JsonOptions>(options =>
{
    options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
});

builder.Services
    .AddApplicationInsightsTelemetryWorkerService()
    .ConfigureFunctionsApplicationInsights();

var managedIdentityCredential = new ManagedIdentityCredential();

builder.Services.AddPnPCore(options =>
{
    options.PnPContext.GraphFirst = false;
})
.Services.AddSingleton<IAuthenticationProvider>(sp =>
{
    // Wire this up using the real constructor signature found in Task 2 Step 1 —
    // this is a best-effort sketch, not confirmed against the real API.
    return new ExternalAuthenticationProvider(async (resource, scopes, cancellationToken) =>
    {
        var scopeList = scopes is { Length: > 0 } ? scopes : new[] { $"{resource}/.default" };
        var token = await managedIdentityCredential.GetTokenAsync(
            new Azure.Core.TokenRequestContext(scopeList), cancellationToken);
        return token.Token;
    });
});

builder.Build().Run();
```

Adjust this based on what Step 1's reflection actually found — the callback's parameter types/order, and whether `AddPnPCore()` takes the auth provider via a builder option instead of a separate DI registration, are the specific things likely to differ from this sketch.

- [ ] **Step 5: Build**

Run: `cd sharepoint-csom-service && dotnet build`
Expected: `Build succeeded.` If it fails on the PnP Core SDK/auth wiring specifically (not a typo elsewhere), that's expected friction from this task's discovery-heavy nature — fix based on the real compiler errors, re-run, don't guess repeatedly past 2-3 attempts without re-reading the actual PnP Core SDK types available (`dotnet build` errors list valid overloads).

- [ ] **Step 6: Manual local smoke test**

Requires: Azure Functions Core Tools running locally, and either a real SharePoint tenant + Managed-Identity-equivalent local credential (e.g. `az login` as a user/service principal PnP Core SDK's `ExternalAuthenticationProvider` callback can also use via `DefaultAzureCredential` for **local testing only** — note in your report if you substitute this locally, since `ManagedIdentityCredential` itself typically only works when actually running in Azure) — or, if no real tenant is available, confirm at minimum that `func start` boots without a startup exception (DI registration succeeds) and that `curl -X POST http://localhost:7071/search -d '{"query":"test","site_url":"https://example.sharepoint.com","max_results":5}'` returns SOME response (even an auth error) rather than crashing the host process. Report which level of testing you were able to do and why.

- [ ] **Step 7: Commit**

```bash
git add sharepoint-csom-service/SharePointSearchFunction.csproj sharepoint-csom-service/Models sharepoint-csom-service/Functions sharepoint-csom-service/Program.cs
git commit -m "feat: implement SharePoint search via PnP Core SDK with Managed Identity auth"
```

---

### Task 3: Python-side backend routing

**Files:**
- Modify: `app/tools/sharepoint_tool.py`
- Test: `tests/test_sharepoint_tool.py`

**Interfaces:**
- Consumes: nothing new from other tasks (this task is independent of Tasks 1-2's actual C# implementation — it only needs the HTTP contract, which is already fixed).
- Produces: `search_sharepoint(query, site_url, max_results=20, backend=None) -> list[dict]` — unchanged call signature is backward-compatible for `app/nodes/agent1_search.py` (which never passes `backend`, so it always gets the env-var default).

- [ ] **Step 1: Write the failing tests**

`tests/test_sharepoint_tool.py`:
```python
import httpx
import pytest
import respx

from app.tools.sharepoint_tool import search_sharepoint


@pytest.mark.asyncio
async def test_search_sharepoint_uses_azure_function_by_default(monkeypatch):
    monkeypatch.delenv("SHAREPOINT_TOOL_BACKEND", raising=False)
    monkeypatch.setenv("SHAREPOINT_FUNCTION_URL", "https://func.example.azurewebsites.net")

    with respx.mock:
        route = respx.post("https://func.example.azurewebsites.net/search").mock(
            return_value=httpx.Response(200, json={"documents": [{"doc_id": "1"}]})
        )
        result = await search_sharepoint(query="q", site_url="https://s.example.com")

    assert route.called
    assert result == [{"doc_id": "1"}]


@pytest.mark.asyncio
async def test_search_sharepoint_python_backend_explicit(monkeypatch):
    monkeypatch.setenv("SHAREPOINT_SERVICE_URL", "https://sidecar.example.com")

    with respx.mock:
        route = respx.post("https://sidecar.example.com/search").mock(
            return_value=httpx.Response(200, json={"documents": [{"doc_id": "2"}]})
        )
        result = await search_sharepoint(
            query="q", site_url="https://s.example.com", backend="python"
        )

    assert route.called
    assert result == [{"doc_id": "2"}]


@pytest.mark.asyncio
async def test_search_sharepoint_raises_when_azure_function_url_unset(monkeypatch):
    monkeypatch.delenv("SHAREPOINT_FUNCTION_URL", raising=False)

    with pytest.raises(NotImplementedError):
        await search_sharepoint(
            query="q", site_url="https://s.example.com", backend="azure_function"
        )


@pytest.mark.asyncio
async def test_search_sharepoint_raises_when_python_url_unset(monkeypatch):
    monkeypatch.delenv("SHAREPOINT_SERVICE_URL", raising=False)

    with pytest.raises(NotImplementedError):
        await search_sharepoint(query="q", site_url="https://s.example.com", backend="python")


@pytest.mark.asyncio
async def test_search_sharepoint_invalid_backend_raises_value_error():
    with pytest.raises(ValueError, match="invalid_backend_name"):
        await search_sharepoint(
            query="q", site_url="https://s.example.com", backend="invalid_backend_name"
        )
```

This test suite uses `respx` (an httpx-mocking library) — check if it's already a dependency; if not, this task adds it.

- [ ] **Step 2: Add `respx` as a dev dependency if not already present**

Run: `grep -q respx pyproject.toml || echo "not present"`

If not present, add `"respx>=0.21"` to the `dev` extra in `pyproject.toml`, then run `pip install -e ".[dev]"`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_sharepoint_tool.py -v`
Expected: FAIL — `search_sharepoint` doesn't yet accept a `backend` parameter, and `SHAREPOINT_FUNCTION_URL` doesn't exist yet.

- [ ] **Step 4: Write the implementation**

Replace `app/tools/sharepoint_tool.py`'s contents with:

```python
"""
SharePoint search tool used by Agent 1.

Two interchangeable backends, both implementing the same HTTP contract
(POST {base_url}/search -> {"documents": [...]})  — selected via the
`backend` parameter, defaulting from SHAREPOINT_TOOL_BACKEND (not an LLM
tool-calling decision; app/nodes/agent1_search.py calls this function
directly and never passes `backend`, so it always gets the env-var
default):

  "azure_function" (default) — sharepoint-csom-service/, a real C# Azure
      Function using PnP Core SDK, authenticated via Managed Identity.
  "python" — the original planned .NET CSOM/PnP Framework sidecar. Kept as
      an "explore" option; still unimplemented (SHAREPOINT_SERVICE_URL
      unset raises NotImplementedError, same as before this change).

Request:  {"query": "string", "site_url": "string", "max_results": 20}
Response: {"documents": [{"doc_id", "title", "url", "content_snippet",
                           "last_modified", "library", "metadata"}]}
"""

from __future__ import annotations

import os

import httpx

SHAREPOINT_SERVICE_URL = os.environ.get("SHAREPOINT_SERVICE_URL")
SHAREPOINT_FUNCTION_URL = os.environ.get("SHAREPOINT_FUNCTION_URL")

_VALID_BACKENDS = ("python", "azure_function")


async def _post_search(base_url: str, query: str, site_url: str, max_results: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url}/search",
            json={"query": query, "site_url": site_url, "max_results": max_results},
        )
        response.raise_for_status()
        return response.json()["documents"]


async def search_sharepoint(
    query: str,
    site_url: str,
    max_results: int = 20,
    backend: str | None = None,
) -> list[dict]:
    """Search SharePoint via one of two interchangeable backends.

    Raises:
        ValueError: if `backend` isn't "python" or "azure_function".
        NotImplementedError: if the selected backend's URL env var isn't set.
        httpx.HTTPStatusError: on non-2xx response from the backend.
    """
    if backend is None:
        backend = os.environ.get("SHAREPOINT_TOOL_BACKEND", "azure_function")

    if backend not in _VALID_BACKENDS:
        raise ValueError(
            f"invalid_backend_name: {backend!r} is not a valid SharePoint tool "
            f"backend — must be one of {_VALID_BACKENDS}"
        )

    if backend == "azure_function":
        if not SHAREPOINT_FUNCTION_URL:
            raise NotImplementedError(
                "SHAREPOINT_FUNCTION_URL is not set. The sharepoint-csom-service "
                "Azure Function has not been deployed yet."
            )
        return await _post_search(SHAREPOINT_FUNCTION_URL, query, site_url, max_results)

    if not SHAREPOINT_SERVICE_URL:
        raise NotImplementedError(
            "SHAREPOINT_SERVICE_URL is not set. The .NET CSOM/PnP Framework "
            "sidecar has not been scaffolded/deployed yet — this is the "
            "'python' backend, kept as an explore option."
        )
    return await _post_search(SHAREPOINT_SERVICE_URL, query, site_url, max_results)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_sharepoint_tool.py -v`
Expected: PASS (5/5)

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `pytest tests/ -v`
Expected: all tests pass (existing suite plus these 5 new ones).

- [ ] **Step 7: Commit**

```bash
git add app/tools/sharepoint_tool.py tests/test_sharepoint_tool.py pyproject.toml
git commit -m "feat: add backend-selectable routing to search_sharepoint (azure_function default, python explore option)"
```

---

### Task 4: Documentation

**Files:**
- Create: `sharepoint-csom-service/README.md`
- Modify: `README.md` (the "SharePoint access" bullet in "Key design decisions")

**Interfaces:** None — documentation only.

- [ ] **Step 1: Write `sharepoint-csom-service/README.md`**

```markdown
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
```

- [ ] **Step 2: Update `README.md`'s "SharePoint access" bullet**

Find the bullet in "Key design decisions" that currently reads:

```markdown
- **SharePoint access**: Agent 1 does NOT call SharePoint directly from Python.
  CSOM via PnP Framework is .NET-only, so the actual extraction happens in a
  small .NET sidecar/service (`sharepoint-csom-service/`, not yet scaffolded)
  that Agent 1 calls over HTTP. See `app/tools/sharepoint_tool.py` for the
  Python-side interface stub and the integration note at the top of that file.
```

Replace it with:

```markdown
- **SharePoint access**: Agent 1 does NOT call SharePoint directly from Python.
  The default backend is `sharepoint-csom-service/`, a C# Azure Function using
  PnP Core SDK's search API with Managed Identity auth. A second,
  config-selectable backend (`SHAREPOINT_TOOL_BACKEND=python`) targets an
  unimplemented .NET CSOM/PnP Framework sidecar, kept as an "explore" option.
  See `app/tools/sharepoint_tool.py` for the routing logic and
  `sharepoint-csom-service/README.md` for the Function's own docs.
```

- [ ] **Step 3: Commit**

```bash
git add sharepoint-csom-service/README.md README.md
git commit -m "docs: document sharepoint-csom-service Azure Function and backend selection"
```
