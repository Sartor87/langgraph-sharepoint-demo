import sys
from unittest.mock import MagicMock, patch


def test_build_llm_uses_azure_openai_without_foundry_endpoint(monkeypatch):
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")
    # openai>=2.x enforces credential presence at client construction time;
    # set a dummy key so this test exercises the AzureChatOpenAI branch
    # rather than an unrelated "missing credentials" validation error.
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

    from app.graph import _build_llm
    from langchain_openai import AzureChatOpenAI

    llm = _build_llm()

    assert isinstance(llm, AzureChatOpenAI)


def test_build_llm_uses_foundry_client_with_foundry_endpoint(monkeypatch):
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/demo",
    )
    monkeypatch.setenv("FOUNDRY_MODEL_NAME", "gpt-4.1")

    mock_projects_module = MagicMock()
    mock_identity_module = MagicMock()
    mock_credential = MagicMock()
    mock_identity_module.DefaultAzureCredential.return_value = mock_credential
    mock_identity_module.get_bearer_token_provider.return_value = lambda: "fake-token"

    mock_project_client = MagicMock()
    mock_openai_client = MagicMock()
    mock_openai_client.base_url = "https://example.services.ai.azure.com/api/projects/demo/openai/"
    mock_project_client.get_openai_client.return_value = mock_openai_client
    mock_projects_module.AIProjectClient.return_value = mock_project_client

    with patch.dict(
        sys.modules,
        {"azure.ai.projects": mock_projects_module, "azure.identity": mock_identity_module},
    ):
        from app.graph import _build_llm
        from langchain_openai import ChatOpenAI

        llm = _build_llm()

    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "gpt-4.1"
    mock_projects_module.AIProjectClient.assert_called_once_with(
        endpoint="https://example.services.ai.azure.com/api/projects/demo",
        credential=mock_credential,
    )
