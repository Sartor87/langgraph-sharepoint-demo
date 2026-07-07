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
