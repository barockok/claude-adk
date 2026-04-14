import uvicorn
from fastapi import FastAPI

from bridge.a2a.server import build_router
from bridge.a2a.task_manager import TaskManager
from bridge.claude.runner import ClaudeRunner
from bridge.config.settings import Settings
from bridge.memory.mcp_memory import build_memory_mcp_server
from bridge.memory.session_store import InMemorySessionStore, RedisSessionStore


def _build_session_store(settings: Settings):
    if settings.redis_url:
        from redis.asyncio import Redis
        return RedisSessionStore(Redis.from_url(settings.redis_url, decode_responses=True))
    return InMemorySessionStore()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title=f"claude-adk-bridge:{settings.agent_name}")

    if settings.memory_enabled:
        store = _build_session_store(settings)
        runner_holder: dict = {}
        memory_mcp = build_memory_mcp_server(
            store,
            context_id_provider=lambda: (
                runner_holder["runner"].current_context_id() or "default"
            ),
        )
        runner = ClaudeRunner(settings, memory_mcp_server=memory_mcp)
        runner_holder["runner"] = runner
    else:
        runner = ClaudeRunner(settings)

    app.include_router(
        build_router(settings=settings, runner=runner, tasks=TaskManager())
    )
    return app


def main() -> None:
    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.bridge_host,
        port=settings.bridge_port,
    )


if __name__ == "__main__":
    main()
