from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

from bridge.config.settings import Settings


def build_options(
    settings: Settings,
    memory_mcp_server: Any | None = None,
) -> ClaudeAgentOptions:
    mcp_servers: dict[str, Any] = dict(settings.mcp_servers) if settings.mcp_servers else {}
    if memory_mcp_server is not None:
        mcp_servers["bridge-memory"] = memory_mcp_server

    kwargs: dict[str, Any] = {
        "model": settings.agent_model,
        "max_turns": settings.agent_max_turns,
        "allowed_tools": list(settings.agent_allowed_tools),
        "include_partial_messages": True,
    }
    if settings.agent_system_prompt:
        kwargs["system_prompt"] = settings.agent_system_prompt
    if mcp_servers:
        kwargs["mcp_servers"] = mcp_servers

    return ClaudeAgentOptions(**kwargs)
