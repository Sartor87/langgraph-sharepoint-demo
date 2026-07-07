using Azure.Core;
using Azure.Identity;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Azure.Functions.Worker.Builder;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using PnP.Core.Auth;
using System.Text.Json;

var builder = FunctionsApplication.CreateBuilder(args);

builder.ConfigureFunctionsWebApplication();

// snake_case JSON on the wire to match the Python-side contract
// (doc_id, content_snippet, last_modified, site_url, max_results ...).
// The HTTP AspNetCore integration serializes IActionResult responses via MVC's
// JsonOptions and reads request bodies (ReadFromJsonAsync) via Http.Json's
// JsonOptions, so both are configured here.
builder.Services.Configure<Microsoft.AspNetCore.Mvc.JsonOptions>(options =>
{
    options.JsonSerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
    options.JsonSerializerOptions.PropertyNameCaseInsensitive = true;
});
builder.Services.Configure<Microsoft.AspNetCore.Http.Json.JsonOptions>(options =>
{
    options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
    options.SerializerOptions.PropertyNameCaseInsensitive = true;
});

builder.Services
    .AddApplicationInsightsTelemetryWorkerService()
    .ConfigureFunctionsApplicationInsights();

// ManagedIdentityCredential works when running in Azure with a (system- or
// user-assigned) managed identity. For local development it will fail to
// acquire a token; swap to DefaultAzureCredential locally if you need to hit a
// real tenant (see task report / README).
var credential = new ManagedIdentityCredential(ManagedIdentityId.SystemAssigned);

builder.Services.AddPnPCore(options =>
{
    options.PnPContext.GraphFirst = false;

    // PnP.Core.Auth 1.16.0 has NO Managed Identity provider. ExternalAuthenticationProvider
    // is PnP Core SDK's bridge for an arbitrary token-acquisition callback. Confirmed
    // constructor (via reflection over the installed assembly):
    //   ExternalAuthenticationProvider(Func<Uri, string[], Task<string>> accessTokenProvider)
    // The callback receives the resource Uri and the scopes PnP computed, and returns
    // the raw access token string.
    options.DefaultAuthenticationProvider = new ExternalAuthenticationProvider(
        async (Uri resource, string[] scopes) =>
        {
            var requestedScopes = scopes is { Length: > 0 }
                ? scopes
                : new[] { $"{resource.GetLeftPart(UriPartial.Authority)}/.default" };

            AccessToken token = await credential.GetTokenAsync(
                new TokenRequestContext(requestedScopes),
                CancellationToken.None);

            return token.Token;
        });
});

builder.Build().Run();
