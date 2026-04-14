import uvicorn
from fastapi import FastAPI

from bridge.a2a.server import build_router
from bridge.a2a.task_manager import TaskManager
from bridge.claude.runner import ClaudeRunner
from bridge.config.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title=f"claude-adk-bridge:{settings.agent_name}")
    app.include_router(
        build_router(
            settings=settings,
            runner=ClaudeRunner(settings),
            tasks=TaskManager(),
        )
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
