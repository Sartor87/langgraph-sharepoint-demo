namespace SharePointSearchFunction.Models;

public class SearchResponse
{
    public List<DocumentResult> Documents { get; set; } = new();
}
