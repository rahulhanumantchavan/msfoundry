from local_server import local_hosting_environment


def test_hosting_environment_isolated_and_restored(monkeypatch):
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "https://example.invalid")
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "test-only")
    import os
    with local_hosting_environment():
        assert "AZURE_AI_PROJECT_ENDPOINT" not in os.environ
        assert "APPLICATIONINSIGHTS_CONNECTION_STRING" not in os.environ
    assert os.environ["AZURE_AI_PROJECT_ENDPOINT"] == "https://example.invalid"
    assert os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"] == "test-only"