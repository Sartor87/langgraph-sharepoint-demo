using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Azure.Functions.Worker;
using Microsoft.Extensions.Logging;
using PnP.Core.Model.SharePoint;
using PnP.Core.QueryModel;
using PnP.Core.Services;
using SharePointSearchFunction.Models;

namespace SharePointSearchFunction.Functions;

public class FilesFunction
{
    private readonly ILogger<FilesFunction> _logger;
    private readonly IPnPContextFactory _pnpContextFactory;

    public FilesFunction(ILogger<FilesFunction> logger, IPnPContextFactory pnpContextFactory)
    {
        _logger = logger;
        _pnpContextFactory = pnpContextFactory;
    }

    [Function("FindFiles")]
    public async Task<IActionResult> Run(
        [HttpTrigger(AuthorizationLevel.Function, "post", Route = "files/find")] HttpRequest req)
    {
        FindFilesRequest? request;
        try
        {
            request = await req.ReadFromJsonAsync<FindFilesRequest>();
        }
        catch (System.Text.Json.JsonException)
        {
            return new BadRequestObjectResult(new { error = "invalid JSON body" });
        }

        if (request is null ||
            string.IsNullOrWhiteSpace(request.Library) ||
            string.IsNullOrWhiteSpace(request.FileNamePattern) ||
            string.IsNullOrWhiteSpace(request.SiteUrl))
        {
            return new BadRequestObjectResult(new { error = "library, file_name_pattern and site_url are required" });
        }

        if (!Uri.TryCreate(request.SiteUrl, UriKind.Absolute, out var siteUri))
        {
            return new BadRequestObjectResult(new { error = "site_url must be an absolute URL" });
        }

        _logger.LogInformation("Finding files matching '{Pattern}' in library '{Library}' at {SiteUrl}",
            request.FileNamePattern, request.Library, request.SiteUrl);

        using var context = await _pnpContextFactory.CreateAsync(siteUri);

        // Explicit Queryable.Where(...) call, not the .Where(...) extension-method
        // syntax: .NET 10's new built-in System.Linq.AsyncEnumerable.Where overload
        // is otherwise ambiguous with PnP Core SDK's IQueryable-based LINQ provider.
        IFolder? folder = await Queryable
            .Where(context.Web.Folders, f => f.Name == request.Library)
            .FirstOrDefaultAsync();

        if (folder is null)
        {
            return new NotFoundObjectResult(new { error = $"library/folder '{request.Library}' not found" });
        }

        List<IFile> foundFiles = await folder.FindFilesAsync(request.FileNamePattern);

        var files = new List<DocumentResult>();
        foreach (var file in foundFiles)
        {
            files.Add(new DocumentResult
            {
                DocId = file.UniqueId.ToString(),
                Title = file.Name,
                Url = file.ServerRelativeUrl,
                ContentSnippet = "",
                LastModified = file.TimeLastModified.ToString("O"),
                Library = request.Library,
                Metadata = new Dictionary<string, object?>
                {
                    ["Length"] = file.Length,
                    ["TimeCreated"] = file.TimeCreated,
                },
            });
        }

        return new OkObjectResult(new FindFilesResponse { Files = files });
    }
}
