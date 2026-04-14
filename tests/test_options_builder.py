from bridge.claude.options import build_options
from bridge.config.settings import Settings


def test_build_options_from_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")
    monkeypatch.setenv("AGENT_SYSTEM_PROMPT", "You are helpful.")
    monkeypatch.setenv("AGENT_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("AGENT_MAX_TURNS", "5")
    monkeypatch.setenv("AGENT_ALLOWED_TOOLS", "Bash,Read")

    opts = build_options(Settings())

    assert opts.system_prompt == "You are helpful."
    assert opts.model == "claude-sonnet-4-6"
    assert opts.max_turns == 5
    assert opts.allowed_tools == ["Bash", "Read"]


def test_build_options_omits_empty_system_prompt(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")
    monkeypatch.delenv("AGENT_SYSTEM_PROMPT", raising=False)

    opts = build_options(Settings())

    assert opts.system_prompt in (None, "")


def test_build_options_injects_memory_mcp_when_provided(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")

    sentinel = object()
    opts = build_options(Settings(), memory_mcp_server=sentinel)

    assert "bridge-memory" in opts.mcp_servers
    assert opts.mcp_servers["bridge-memory"] is sentinel


def test_build_options_omits_memory_mcp_when_not_provided(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")

    opts = build_options(Settings())

    mcp = getattr(opts, "mcp_servers", {}) or {}
    assert "bridge-memory" not in mcp
