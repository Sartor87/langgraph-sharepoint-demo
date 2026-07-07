namespace SharePointSearchFunction.Models;

public class FindFilesRequest
{
    public string Library { get; set; } = string.Empty;
    public string FileNamePattern { get; set; } = string.Empty;
    public string SiteUrl { get; set; } = string.Empty;
}
