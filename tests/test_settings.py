import json
import pytest
from pydantic import ValidationError
from bridge.config.settings import Settings


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_NAME", "my-agent")
    for k in ["AGENT_DESCRIPTION", "AGENT_SYSTEM_PROMPT", "MCP_SERVERS"]:
        monkeypatch.delenv(k, raising=False)

    s = Settings()

    assert s.anthropic_api_key == "sk-test"
    assert s.agent_name == "my-agent"
    assert s.agent_model == "claude-sonnet-4-6"
    assert s.agent_max_turns == 10
    assert s.agent_allowed_tools == ["Read", "Bash"]
    assert s.mcp_servers == {}
    assert s.bridge_port == 8080
    assert s.bridge_host == "0.0.0.0"


def test_settings_allowed_tools_parses_csv(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_NAME", "a")
    monkeypatch.setenv("AGENT_ALLOWED_TOOLS", "Bash,Read,Write,Edit")

    s = Settings()

    assert s.agent_allowed_tools == ["Bash", "Read", "Write", "Edit"]


def test_settings_mcp_servers_parses_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_NAME", "a")
    monkeypatch.setenv("MCP_SERVERS", json.dumps({"slack": {"url": "https://x"}}))

    s = Settings()

    assert s.mcp_servers == {"slack": {"url": "https://x"}}


def test_settings_missing_required_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_NAME", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_memory_defaults(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "a")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("MEMORY_ENABLED", raising=False)

    s = Settings()

    assert s.memory_enabled is True
    assert s.redis_url == ""


def test_memory_redis_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "a")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    s = Settings()

    assert s.redis_url == "redis://localhost:6379/0"


def test_memory_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "a")
    monkeypatch.setenv("MEMORY_ENABLED", "false")

    s = Settings()

    assert s.memory_enabled is False
