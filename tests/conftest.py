import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bridge.a2a.server import build_router
from bridge.a2a.task_manager import TaskManager
from bridge.claude.runner import RunResult
from bridge.config.settings import Settings


class FakeRunner:
    def __init__(self, final_text: str = "fake-response", should_raise: Exception | None = None):
        self.final_text = final_text
        self.should_raise = should_raise
        self.calls: list[str] = []

    async def run(self, prompt: str) -> RunResult:
        self.calls.append(prompt)
        if self.should_raise:
            raise self.should_raise
        return RunResult(final_text=self.final_text, messages=[])


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "test-agent")
    monkeypatch.setenv("AGENT_DESCRIPTION", "test")
    return Settings()


@pytest.fixture
def fake_runner():
    return FakeRunner()


@pytest.fixture
def task_manager():
    return TaskManager()


@pytest.fixture
def client(settings, fake_runner, task_manager):
    app = FastAPI()
    app.include_router(build_router(settings=settings, runner=fake_runner, tasks=task_manager))
    return TestClient(app)
