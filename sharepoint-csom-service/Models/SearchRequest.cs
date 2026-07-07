namespace SharePointSearchFunction.Models;

public class SearchRequest
{
    public string Query { get; set; } = string.Empty;
    public string SiteUrl { get; set; } = string.Empty;
    public int MaxResults { get; set; } = 20;
}
