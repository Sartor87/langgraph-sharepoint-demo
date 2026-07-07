using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Extensions.Logging;
using PnP.Core.Model.SharePoint;
using PnP.Core.Services;
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
        [HttpTrigger(AuthorizationLevel.Function, "post", Route = "search")] HttpRequest req)
    {
        SearchRequest? request;
        try
        {
            request = await req.ReadFromJsonAsync<SearchRequest>();
        }
        catch (System.Text.Json.JsonException)
        {
            return new BadRequestObjectResult(new { error = "invalid JSON body" });
        }

        if (request is null ||
            string.IsNullOrWhiteSpace(request.Query) ||
            string.IsNullOrWhiteSpace(request.SiteUrl))
        {
            return new BadRequestObjectResult(new { error = "query and site_url are required" });
        }

        if (!Uri.TryCreate(request.SiteUrl, UriKind.Absolute, out var siteUri))
        {
            return new BadRequestObjectResult(new { error = "site_url must be an absolute URL" });
        }

        _logger.LogInformation("Searching {SiteUrl} for '{Query}' (max {MaxResults})",
            request.SiteUrl, request.Query, request.MaxResults);

        using var context = await _pnpContextFactory.CreateAsync(siteUri);

        var searchOptions = new SearchOptions(request.Query)
        {
            TrimDuplicates = false,
            RowLimit = request.MaxResults,
            SelectProperties = new List<string>
            {
                "UniqueId", "Title", "Path", "HitHighlightedSummary", "LastModifiedTime"
            },
        };

        ISearchResult searchResult = await context.Web.SearchAsync(searchOptions);

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
        if (string.IsNullOrEmpty(path))
        {
            return "";
        }

        var uri = new Uri(path, UriKind.RelativeOrAbsolute);
        var segments = uri.IsAbsoluteUri
            ? uri.AbsolutePath.Trim('/').Split('/')
            : path.Trim('/').Split('/');
        return segments.Length >= 3 ? segments[2] : "";
    }
}
