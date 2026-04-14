from bridge.a2a.models import AgentCapabilities, AgentCard, AgentSkill
from bridge.config.settings import Settings


def build_agent_card(settings: Settings) -> AgentCard:
    url = settings.agent_url or f"http://{settings.agent_name}.local:{settings.bridge_port}"

    skills = [
        AgentSkill(
            id=tool,
            name=tool,
            description=f"Claude built-in tool: {tool}",
        )
        for tool in settings.agent_allowed_tools
    ]

    return AgentCard(
        name=settings.agent_name,
        description=settings.agent_description or f"Claude-powered agent: {settings.agent_name}",
        url=url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=skills,
    )
