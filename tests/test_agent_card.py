from bridge.a2a.agent_card import build_agent_card
from bridge.config.settings import Settings


def test_build_agent_card_from_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "sre-agent")
    monkeypatch.setenv("AGENT_DESCRIPTION", "SRE helper")
    monkeypatch.setenv("AGENT_URL", "http://sre-agent.kagent.svc:8080")
    monkeypatch.setenv("AGENT_ALLOWED_TOOLS", "Bash,Read")

    card = build_agent_card(Settings())

    assert card.name == "sre-agent"
    assert card.description == "SRE helper"
    assert card.url == "http://sre-agent.kagent.svc:8080"
    assert card.version == "1.0.0"
    assert card.capabilities.streaming is False
    tool_ids = {s.id for s in card.skills}
    assert "Bash" in tool_ids
    assert "Read" in tool_ids


def test_build_agent_card_defaults_url_when_missing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "a")
    monkeypatch.delenv("AGENT_URL", raising=False)

    card = build_agent_card(Settings())

    assert card.url.startswith("http://")
    assert "a" in card.url
