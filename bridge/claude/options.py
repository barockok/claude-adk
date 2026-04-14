from claude_agent_sdk import ClaudeAgentOptions

from bridge.config.settings import Settings


def build_options(settings: Settings) -> ClaudeAgentOptions:
    kwargs: dict = {
        "model": settings.agent_model,
        "max_turns": settings.agent_max_turns,
        "allowed_tools": list(settings.agent_allowed_tools),
    }
    if settings.agent_system_prompt:
        kwargs["system_prompt"] = settings.agent_system_prompt
    if settings.mcp_servers:
        kwargs["mcp_servers"] = settings.mcp_servers

    return ClaudeAgentOptions(**kwargs)
