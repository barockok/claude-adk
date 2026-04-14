# Claude ADK Bridge — Phase 1 (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal FastAPI-based bridge that exposes the Claude Agent SDK as an A2A-compliant HTTP server, deployable as a Kagent BYO agent.

**Architecture:** A single FastAPI process reads configuration from environment variables, builds a `ClaudeAgentOptions` object, and exposes four A2A endpoints (`GET /.well-known/agent-card.json`, `POST /` for `message/send`, `GET /tasks/{id}`, `GET /health`). `message/send` calls `claude_agent_sdk.query()`, collects all SDK messages, and returns a JSON-RPC `Task` response. Task state is held in an in-memory dict (single-replica MVP).

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, `claude-agent-sdk`, Pydantic v2, pytest + pytest-asyncio, Docker.

**Scope (Phase 1 only):**
- Synchronous `message/send` only — no streaming (Phase 2)
- In-memory task store — no Redis (Phase 2)
- No memory MCP, no hooks, no OTel — (Phases 2–3)
- No auth — (Phase 4)

---

## File Structure

```
claude-adk-bridge/
├── pyproject.toml
├── Dockerfile
├── .gitignore
├── README.md
├── bridge/
│   ├── __init__.py
│   ├── main.py                     # Uvicorn entrypoint + FastAPI app wiring
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py             # Pydantic BaseSettings from env vars
│   ├── a2a/
│   │   ├── __init__.py
│   │   ├── models.py               # JSON-RPC + A2A Pydantic models
│   │   ├── agent_card.py           # Agent Card builder
│   │   ├── task_manager.py         # In-memory task store
│   │   └── server.py               # APIRouter with A2A endpoints
│   └── claude/
│       ├── __init__.py
│       ├── options.py              # ClaudeAgentOptions builder from Settings
│       └── runner.py               # async run(prompt) -> collected messages
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_settings.py
    ├── test_agent_card.py
    ├── test_task_manager.py
    ├── test_options_builder.py
    ├── test_runner.py              # uses monkeypatched claude_agent_sdk.query
    └── test_a2a_server.py          # FastAPI TestClient end-to-end
```

Responsibility boundaries:
- `config/settings.py` — only env-var parsing + validation. No logic.
- `a2a/models.py` — only data shapes (Pydantic). No behavior.
- `a2a/agent_card.py` — only the Agent Card builder (pure function of Settings).
- `a2a/task_manager.py` — only the in-memory task dict + getters/setters.
- `a2a/server.py` — HTTP routing; delegates to `claude/runner.py` + `task_manager.py`.
- `claude/options.py` — builds `ClaudeAgentOptions` from Settings (pure function).
- `claude/runner.py` — wraps `claude_agent_sdk.query()`; collects messages.
- `main.py` — wires Settings → app → uvicorn.

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `bridge/__init__.py`
- Create: `bridge/config/__init__.py`
- Create: `bridge/a2a/__init__.py`
- Create: `bridge/claude/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "claude-adk-bridge"
version = "0.1.0"
description = "A2A-compliant bridge exposing Claude Agent SDK as an ADK-compatible agent"
requires-python = ">=3.11"

dependencies = [
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "claude-agent-sdk>=0.2.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "anyio>=4.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
]

[build-system]
requires = ["setuptools>=68.0.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["bridge*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.venv/
venv/
.env
dist/
build/
```

- [ ] **Step 3: Create empty `__init__.py` files**

Create `bridge/__init__.py`, `bridge/config/__init__.py`, `bridge/a2a/__init__.py`, `bridge/claude/__init__.py`, `tests/__init__.py` — each empty.

- [ ] **Step 4: Install deps and verify**

Run: `python -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'`
Expected: Install succeeds; `pytest --collect-only` reports `0 tests collected` with no errors.

- [ ] **Step 5: Commit**

```bash
git init
git add pyproject.toml .gitignore bridge tests
git commit -m "chore: scaffold claude-adk-bridge project structure"
```

---

## Task 2: Settings module (config from env vars)

**Files:**
- Create: `bridge/config/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings.py`:

```python
import json
import pytest
from bridge.config.settings import Settings


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_NAME", "my-agent")
    # Clear any inherited optional env vars
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
    with pytest.raises(Exception):
        Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bridge.config.settings'`.

- [ ] **Step 3: Implement `bridge/config/settings.py`**

```python
import json
from typing import Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    agent_name: str = Field(..., alias="AGENT_NAME")
    agent_description: str = Field(default="", alias="AGENT_DESCRIPTION")
    agent_system_prompt: str = Field(default="", alias="AGENT_SYSTEM_PROMPT")
    agent_model: str = Field(default="claude-sonnet-4-6", alias="AGENT_MODEL")
    agent_max_turns: int = Field(default=10, alias="AGENT_MAX_TURNS")
    agent_allowed_tools: list[str] = Field(
        default_factory=lambda: ["Read", "Bash"], alias="AGENT_ALLOWED_TOOLS"
    )
    mcp_servers: dict[str, Any] = Field(default_factory=dict, alias="MCP_SERVERS")
    bridge_port: int = Field(default=8080, alias="BRIDGE_PORT")
    bridge_host: str = Field(default="0.0.0.0", alias="BRIDGE_HOST")
    agent_url: str = Field(default="", alias="AGENT_URL")

    @field_validator("agent_allowed_tools", mode="before")
    @classmethod
    def _parse_tools(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("mcp_servers", mode="before")
    @classmethod
    def _parse_mcp(cls, v: Any) -> Any:
        if isinstance(v, str):
            if not v.strip():
                return {}
            return json.loads(v)
        return v
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_settings.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add bridge/config/settings.py tests/test_settings.py
git commit -m "feat(config): add Settings module loading from environment variables"
```

---

## Task 3: A2A Pydantic models

**Files:**
- Create: `bridge/a2a/models.py`
- Test: `tests/test_a2a_models.py`

The A2A protocol is JSON-RPC 2.0 with specific params/result shapes. We model the minimum surface needed for `message/send`, the Agent Card, and the Task object.

- [ ] **Step 1: Write the failing test**

Create `tests/test_a2a_models.py`:

```python
from bridge.a2a.models import (
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcError,
    Message,
    TextPart,
    Task,
    TaskStatus,
    TaskState,
    AgentCard,
)


def test_jsonrpc_request_parses_message_send():
    raw = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "hello"}],
            }
        },
    }
    req = JsonRpcRequest.model_validate(raw)
    assert req.method == "message/send"
    assert req.params["message"]["parts"][0]["text"] == "hello"


def test_message_and_textpart_roundtrip():
    msg = Message(role="agent", parts=[TextPart(text="hi")])
    dumped = msg.model_dump()
    assert dumped["role"] == "agent"
    assert dumped["parts"][0]["kind"] == "text"
    assert dumped["parts"][0]["text"] == "hi"


def test_task_has_status_and_id():
    task = Task(
        id="t-1",
        contextId="ctx-1",
        status=TaskStatus(state=TaskState.completed),
        history=[Message(role="agent", parts=[TextPart(text="done")])],
    )
    assert task.status.state == TaskState.completed
    assert task.id == "t-1"


def test_jsonrpc_error_response_shape():
    resp = JsonRpcResponse(
        id="req-1",
        error=JsonRpcError(code=-32601, message="Method not found"),
    )
    dumped = resp.model_dump(exclude_none=True)
    assert dumped["jsonrpc"] == "2.0"
    assert dumped["error"]["code"] == -32601
    assert "result" not in dumped


def test_agent_card_serializes():
    card = AgentCard(
        name="x",
        description="y",
        url="http://x",
        version="1.0.0",
    )
    dumped = card.model_dump()
    assert dumped["name"] == "x"
    assert dumped["capabilities"]["streaming"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_a2a_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bridge.a2a.models'`.

- [ ] **Step 3: Implement `bridge/a2a/models.py`**

```python
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class TaskState(str, Enum):
    submitted = "submitted"
    working = "working"
    input_required = "input-required"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[TextPart]
    messageId: str | None = None


class TaskStatus(BaseModel):
    state: TaskState
    message: Message | None = None
    timestamp: str | None = None


class Task(BaseModel):
    id: str
    contextId: str
    status: TaskStatus
    history: list[Message] = Field(default_factory=list)
    kind: Literal["task"] = "task"


class AgentCapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False
    stateTransitionHistory: bool = False


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = Field(default_factory=list)
    defaultInputModes: list[str] = Field(default_factory=lambda: ["text"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["text"])


class JsonRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    result: Any | None = None
    error: JsonRpcError | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_a2a_models.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add bridge/a2a/models.py tests/test_a2a_models.py
git commit -m "feat(a2a): add JSON-RPC + A2A Pydantic models"
```

---

## Task 4: Agent Card builder

**Files:**
- Create: `bridge/a2a/agent_card.py`
- Test: `tests/test_agent_card.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_card.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_card.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bridge.a2a.agent_card'`.

- [ ] **Step 3: Implement `bridge/a2a/agent_card.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_card.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add bridge/a2a/agent_card.py tests/test_agent_card.py
git commit -m "feat(a2a): build Agent Card from Settings"
```

---

## Task 5: In-memory task manager

**Files:**
- Create: `bridge/a2a/task_manager.py`
- Test: `tests/test_task_manager.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_manager.py`:

```python
import pytest
from bridge.a2a.models import Message, TaskState, TextPart
from bridge.a2a.task_manager import TaskManager, TaskNotFoundError


def test_create_task_returns_submitted():
    mgr = TaskManager()
    task = mgr.create(context_id="ctx-1")

    assert task.id
    assert task.contextId == "ctx-1"
    assert task.status.state == TaskState.submitted


def test_get_returns_same_task():
    mgr = TaskManager()
    created = mgr.create(context_id="ctx-1")
    fetched = mgr.get(created.id)

    assert fetched.id == created.id


def test_get_unknown_raises():
    mgr = TaskManager()
    with pytest.raises(TaskNotFoundError):
        mgr.get("nope")


def test_update_status_changes_state_and_appends_message():
    mgr = TaskManager()
    task = mgr.create(context_id="ctx-1")

    mgr.update_status(
        task.id,
        TaskState.working,
        message=Message(role="agent", parts=[TextPart(text="thinking")]),
    )
    mgr.update_status(
        task.id,
        TaskState.completed,
        message=Message(role="agent", parts=[TextPart(text="done")]),
    )

    updated = mgr.get(task.id)
    assert updated.status.state == TaskState.completed
    assert len(updated.history) == 2
    assert updated.history[-1].parts[0].text == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_task_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bridge.a2a.task_manager'`.

- [ ] **Step 3: Implement `bridge/a2a/task_manager.py`**

```python
import uuid
from datetime import datetime, timezone
from threading import Lock

from bridge.a2a.models import Message, Task, TaskState, TaskStatus


class TaskNotFoundError(KeyError):
    pass


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = Lock()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create(self, context_id: str, task_id: str | None = None) -> Task:
        tid = task_id or str(uuid.uuid4())
        task = Task(
            id=tid,
            contextId=context_id,
            status=TaskStatus(state=TaskState.submitted, timestamp=self._now_iso()),
        )
        with self._lock:
            self._tasks[tid] = task
        return task

    def get(self, task_id: str) -> Task:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    def update_status(
        self,
        task_id: str,
        state: TaskState,
        message: Message | None = None,
    ) -> Task:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(task_id)
            new_history = list(task.history)
            if message is not None:
                new_history.append(message)
            updated = task.model_copy(
                update={
                    "status": TaskStatus(
                        state=state, message=message, timestamp=self._now_iso()
                    ),
                    "history": new_history,
                }
            )
            self._tasks[task_id] = updated
            return updated
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_task_manager.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add bridge/a2a/task_manager.py tests/test_task_manager.py
git commit -m "feat(a2a): add in-memory TaskManager"
```

---

## Task 6: ClaudeAgentOptions builder

**Files:**
- Create: `bridge/claude/options.py`
- Test: `tests/test_options_builder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_options_builder.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_options_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `bridge/claude/options.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_options_builder.py -v`
Expected: 2 passed.

Note: if `ClaudeAgentOptions` rejects an unknown field (e.g. `mcp_servers`), narrow `kwargs` to fields the installed SDK version accepts. Check with `python -c "from claude_agent_sdk import ClaudeAgentOptions; help(ClaudeAgentOptions)"`.

- [ ] **Step 5: Commit**

```bash
git add bridge/claude/options.py tests/test_options_builder.py
git commit -m "feat(claude): build ClaudeAgentOptions from Settings"
```

---

## Task 7: Claude runner

**Files:**
- Create: `bridge/claude/runner.py`
- Test: `tests/test_runner.py`

The runner wraps `claude_agent_sdk.query()` and collects all emitted messages into a list. It also extracts the final text response so the A2A server can wrap it in a Task.

- [ ] **Step 1: Write the failing test**

Create `tests/test_runner.py`:

```python
import pytest
from bridge.claude import runner as runner_mod
from bridge.claude.runner import ClaudeRunner, RunResult
from bridge.config.settings import Settings


class _FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeAssistantMessage:
    def __init__(self, text: str):
        self.content = [_FakeTextBlock(text)]


class _FakeResultMessage:
    def __init__(self, text: str):
        self.result = text


async def _fake_query_factory(messages):
    async def _fake_query(*, prompt, options):
        for m in messages:
            yield m
    return _fake_query


@pytest.mark.asyncio
async def test_runner_collects_messages_and_final_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")

    msgs = [_FakeAssistantMessage("partial "), _FakeResultMessage("hello world")]
    monkeypatch.setattr(runner_mod, "query", await _fake_query_factory(msgs))

    r = ClaudeRunner(Settings())
    result: RunResult = await r.run("hi")

    assert isinstance(result, RunResult)
    assert result.final_text == "hello world"
    assert len(result.messages) == 2


@pytest.mark.asyncio
async def test_runner_falls_back_to_assistant_text_when_no_result(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")

    msgs = [_FakeAssistantMessage("only "), _FakeAssistantMessage("assistant text")]
    monkeypatch.setattr(runner_mod, "query", await _fake_query_factory(msgs))

    r = ClaudeRunner(Settings())
    result = await r.run("hi")

    assert result.final_text == "only assistant text"


@pytest.mark.asyncio
async def test_runner_propagates_exceptions(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")

    async def _boom(*, prompt, options):
        raise RuntimeError("sdk failure")
        yield  # pragma: no cover

    monkeypatch.setattr(runner_mod, "query", _boom)

    r = ClaudeRunner(Settings())
    with pytest.raises(RuntimeError, match="sdk failure"):
        await r.run("hi")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bridge.claude.runner'`.

- [ ] **Step 3: Implement `bridge/claude/runner.py`**

```python
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import query

from bridge.claude.options import build_options
from bridge.config.settings import Settings


@dataclass
class RunResult:
    final_text: str
    messages: list[Any] = field(default_factory=list)


def _extract_assistant_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


class ClaudeRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def run(self, prompt: str) -> RunResult:
        options = build_options(self._settings)
        collected: list[Any] = []
        result_text: str | None = None
        assistant_chunks: list[str] = []

        async for message in query(prompt=prompt, options=options):
            collected.append(message)
            res = getattr(message, "result", None)
            if isinstance(res, str):
                result_text = res
                continue
            chunk = _extract_assistant_text(message)
            if chunk:
                assistant_chunks.append(chunk)

        final_text = result_text if result_text is not None else "".join(assistant_chunks)
        return RunResult(final_text=final_text, messages=collected)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_runner.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add bridge/claude/runner.py tests/test_runner.py
git commit -m "feat(claude): add ClaudeRunner wrapping claude_agent_sdk.query"
```

---

## Task 8: A2A server endpoints

**Files:**
- Create: `bridge/a2a/server.py`
- Create: `tests/conftest.py`
- Test: `tests/test_a2a_server.py`

The server exposes `GET /.well-known/agent-card.json`, `POST /`, `GET /tasks/{task_id}`, `GET /health`. `POST /` dispatches on `method` and only accepts `message/send` in Phase 1 (returns JSON-RPC error `-32601` for anything else, including `message/stream`).

- [ ] **Step 1: Write `tests/conftest.py`**

```python
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
```

- [ ] **Step 2: Write the failing test — `tests/test_a2a_server.py`**

```python
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_agent_card(client):
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "test-agent"
    assert body["capabilities"]["streaming"] is False


def test_message_send_returns_task_with_result(client, fake_runner):
    fake_runner.final_text = "Hello from Claude"
    payload = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "hi"}],
            }
        },
    }
    r = client.post("/", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == "req-1"
    assert body["result"]["kind"] == "task"
    assert body["result"]["status"]["state"] == "completed"
    assert body["result"]["history"][-1]["parts"][0]["text"] == "Hello from Claude"
    assert fake_runner.calls == ["hi"]


def test_message_send_failure_returns_failed_task(client, fake_runner):
    fake_runner.should_raise = RuntimeError("boom")
    payload = {
        "jsonrpc": "2.0",
        "id": "req-2",
        "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "x"}]}},
    }
    r = client.post("/", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["status"]["state"] == "failed"


def test_unsupported_method_returns_jsonrpc_error(client):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-3",
        "method": "message/stream",
        "params": {},
    }
    r = client.post("/", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["error"]["code"] == -32601
    assert "result" not in body or body.get("result") is None


def test_get_task_returns_persisted_task(client):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}},
    }
    created = client.post("/", json=payload).json()
    task_id = created["result"]["id"]

    r = client.get(f"/tasks/{task_id}")
    assert r.status_code == 200
    assert r.json()["id"] == task_id


def test_get_task_unknown_returns_404(client):
    r = client.get("/tasks/does-not-exist")
    assert r.status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_a2a_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bridge.a2a.server'`.

- [ ] **Step 4: Implement `bridge/a2a/server.py`**

```python
from typing import Protocol
import uuid

from fastapi import APIRouter, HTTPException, Request

from bridge.a2a.agent_card import build_agent_card
from bridge.a2a.models import (
    AgentCard,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    Message,
    Task,
    TaskState,
    TextPart,
)
from bridge.a2a.task_manager import TaskManager, TaskNotFoundError
from bridge.claude.runner import RunResult
from bridge.config.settings import Settings


class RunnerProtocol(Protocol):
    async def run(self, prompt: str) -> RunResult: ...


METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _extract_prompt(params: dict) -> str:
    message = params.get("message") or {}
    parts = message.get("parts") or []
    texts = [p.get("text", "") for p in parts if p.get("kind") == "text"]
    return "".join(texts)


def build_router(
    *, settings: Settings, runner: RunnerProtocol, tasks: TaskManager
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @router.get("/.well-known/agent-card.json", response_model=AgentCard)
    async def agent_card() -> AgentCard:
        return build_agent_card(settings)

    @router.get("/tasks/{task_id}", response_model=Task)
    async def get_task(task_id: str) -> Task:
        try:
            return tasks.get(task_id)
        except TaskNotFoundError:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    @router.post("/", response_model=JsonRpcResponse, response_model_exclude_none=True)
    async def rpc(request: Request) -> JsonRpcResponse:
        raw = await request.json()
        try:
            rpc_req = JsonRpcRequest.model_validate(raw)
        except Exception as exc:
            return JsonRpcResponse(
                id=raw.get("id") if isinstance(raw, dict) else None,
                error=JsonRpcError(code=INVALID_PARAMS, message=str(exc)),
            )

        if rpc_req.method != "message/send":
            return JsonRpcResponse(
                id=rpc_req.id,
                error=JsonRpcError(
                    code=METHOD_NOT_FOUND,
                    message=f"Method '{rpc_req.method}' not supported in Phase 1 MVP",
                ),
            )

        prompt = _extract_prompt(rpc_req.params)
        context_id = rpc_req.params.get("contextId") or str(uuid.uuid4())
        task = tasks.create(context_id=context_id)

        try:
            result = await runner.run(prompt)
        except Exception as exc:
            updated = tasks.update_status(
                task.id,
                TaskState.failed,
                message=Message(role="agent", parts=[TextPart(text=f"Error: {exc}")]),
            )
            return JsonRpcResponse(id=rpc_req.id, result=updated.model_dump())

        updated = tasks.update_status(
            task.id,
            TaskState.completed,
            message=Message(role="agent", parts=[TextPart(text=result.final_text)]),
        )
        return JsonRpcResponse(id=rpc_req.id, result=updated.model_dump())

    return router
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_a2a_server.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add bridge/a2a/server.py tests/conftest.py tests/test_a2a_server.py
git commit -m "feat(a2a): add FastAPI router with message/send, agent-card, task lookup, health"
```

---

## Task 9: Main entry point

**Files:**
- Create: `bridge/main.py`

- [ ] **Step 1: Write `bridge/main.py`**

```python
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
```

- [ ] **Step 2: Smoke-test app construction**

Run: `ANTHROPIC_API_KEY=sk AGENT_NAME=smoke python -c "from bridge.main import create_app; app=create_app(); print([r.path for r in app.routes])"`
Expected: prints a list including `/health`, `/.well-known/agent-card.json`, `/tasks/{task_id}`, `/`.

- [ ] **Step 3: Smoke-test via uvicorn**

Run (in one terminal): `ANTHROPIC_API_KEY=sk AGENT_NAME=smoke python -m bridge.main`
In another terminal: `curl -s http://localhost:8080/health`
Expected: `{"status":"ok"}`. Then `curl -s http://localhost:8080/.well-known/agent-card.json` should return JSON with `"name":"smoke"`.

Stop the server with Ctrl-C.

- [ ] **Step 4: Commit**

```bash
git add bridge/main.py
git commit -m "feat: add main entry point wiring FastAPI app + uvicorn"
```

---

## Task 10: Dockerfile

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

COPY pyproject.toml ./
COPY bridge/ bridge/

RUN pip install --no-cache-dir .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["python", "-m", "bridge.main"]
```

- [ ] **Step 2: Build the image**

Run: `docker build -t claude-adk-bridge:dev .`
Expected: Build succeeds, ends with `Successfully tagged claude-adk-bridge:dev`.

- [ ] **Step 3: Smoke-run the image**

Run: `docker run --rm -p 8080:8080 -e ANTHROPIC_API_KEY=sk -e AGENT_NAME=smoke --name bridge-smoke claude-adk-bridge:dev`

In another terminal: `curl -s http://localhost:8080/health`
Expected: `{"status":"ok"}`.

Stop the container with Ctrl-C.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "build: add Dockerfile for claude-adk-bridge container image"
```

---

## Task 11: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# claude-adk-bridge

A2A-compliant bridge that exposes the Claude Agent SDK as an ADK-compatible
agent, enabling Claude-powered agents to run as Kagent BYO agents on Kubernetes.

## Phase 1 (MVP) scope

- Synchronous `message/send` JSON-RPC endpoint
- Agent Card discovery at `/.well-known/agent-card.json`
- Task lookup via `GET /tasks/{id}`
- Health check at `/health`
- In-memory task store (single replica)
- No streaming / memory MCP / OTel / auth yet

## Run locally

```bash
pip install -e '.[dev]'
export ANTHROPIC_API_KEY=sk-...
export AGENT_NAME=my-agent
python -m bridge.main
```

## Run in Docker

```bash
docker build -t claude-adk-bridge:dev .
docker run --rm -p 8080:8080 \
  -e ANTHROPIC_API_KEY=sk-... \
  -e AGENT_NAME=my-agent \
  claude-adk-bridge:dev
```

## Environment variables

See `bridge/config/settings.py` for the full list. Required:
`ANTHROPIC_API_KEY`, `AGENT_NAME`.

## Tests

```bash
pytest -v
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README for Phase 1 MVP"
```

---

## Task 12: Final full test run

- [ ] **Step 1: Run full test suite**

Run: `pytest -v`
Expected: all tests pass (~22 tests across 6 test files).

- [ ] **Step 2: Tag the MVP**

```bash
git tag -a phase1-mvp -m "Phase 1 MVP: synchronous A2A bridge"
```

---

## Out of Scope (subsequent plans)

- **Phase 2:** SSE streaming (`message/stream`), Redis-backed session store, in-process memory MCP
- **Phase 3:** `PreToolUse`/`PostToolUse` hooks, OpenTelemetry tracing, Prometheus metrics
- **Phase 4:** Long-term vector memory, skills ConfigMap mounting, Bearer auth, Helm chart

Each should get its own plan written after Phase 1 is merged and validated in a Kind + Kagent cluster.
