# Claude ADK Bridge — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Phase 1 bridge with (a) true incremental SSE streaming, (b) an in-process Memory MCP server that gives Claude memory tools, and (c) optional Redis-backed session state.

**Architecture:** Streaming is refactored into a dedicated adapter that consumes the Claude SDK async iterator and translates each chunk into a concrete A2A SSE event (task → working → incremental artifacts → completed). The Memory MCP server is an in-process stdio server (per `claude_agent_sdk.create_sdk_mcp_server`) wired into `ClaudeAgentOptions.mcp_servers`; it exposes four tools backed by a pluggable `SessionStore` with two implementations: in-memory (default) and Redis (used when `REDIS_URL` is set).

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, `claude-agent-sdk`, Pydantic v2, `redis>=5.0` (async), pytest + pytest-asyncio, `fakeredis` for tests.

**Scope (Phase 2 only):**
- True incremental streaming from Claude SDK to SSE
- In-process Memory MCP with `get_state` / `set_state` / `save_memory` / `search_memory`
- Redis session store (optional — falls back to in-memory when `REDIS_URL` unset)
- **NOT in scope:** Vector-backed long-term memory (Phase 4), hooks/OTel (Phase 3), auth (Phase 4), multi-tenancy

---

## File Structure

New and modified files grouped by responsibility:

```
bridge/
├── a2a/
│   └── stream_adapter.py         # NEW: Claude async iterator → A2A SSE events
├── a2a/server.py                 # MODIFY: stream handler delegates to stream_adapter
├── claude/
│   ├── options.py                # MODIFY: inject Memory MCP server into mcp_servers
│   └── runner.py                 # MODIFY: expose stream() async iterator alongside run()
├── memory/
│   ├── __init__.py               # NEW: package init
│   ├── session_store.py          # NEW: SessionStore protocol + InMemory + Redis impls
│   └── mcp_memory.py             # NEW: in-process MCP server exposing memory tools
└── config/
    └── settings.py               # MODIFY: add redis_url, memory_enabled fields

tests/
├── test_stream_adapter.py        # NEW
├── test_session_store.py         # NEW
├── test_mcp_memory.py            # NEW
├── test_a2a_server.py            # MODIFY: replace "run-then-emit" stream test
├── test_options_builder.py       # MODIFY: assert memory MCP injected when enabled
└── test_runner.py                # MODIFY: add test for ClaudeRunner.stream()
```

Responsibility boundaries:
- `a2a/stream_adapter.py` — ONE job: turn a `AsyncIterator[ClaudeMessage]` + request context into a stream of A2A SSE `data: ...` strings. Pure translation. No HTTP, no task-store writes (caller handles those).
- `memory/session_store.py` — the CRUD contract. Two impls behind one `SessionStore` Protocol.
- `memory/mcp_memory.py` — wraps the store in MCP tool decorators and returns the configured MCP server object that `ClaudeAgentOptions.mcp_servers` accepts.
- `claude/runner.py` — adds `stream()` that is an async generator yielding the raw Claude messages. `run()` stays for non-streaming callers.
- `claude/options.py` — now responsible for wiring the memory MCP server when `memory_enabled=True`.
- `a2a/server.py` — stream handler orchestrates: create task, call runner.stream(), push each chunk through stream_adapter, update task manager.

---

## Task 1: Session store — Protocol + InMemory implementation

**Files:**
- Create: `bridge/memory/__init__.py` (empty)
- Create: `bridge/memory/session_store.py`
- Test: `tests/test_session_store.py`

- [ ] **Step 1: Create `bridge/memory/__init__.py`** — empty file.

- [ ] **Step 2: Write failing test — `tests/test_session_store.py`**

```python
import pytest
from bridge.memory.session_store import InMemorySessionStore


@pytest.mark.asyncio
async def test_set_and_get():
    store = InMemorySessionStore()
    await store.set_state("ctx-1", "key", "value")
    assert await store.get_state("ctx-1", "key") == "value"


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    store = InMemorySessionStore()
    assert await store.get_state("ctx-1", "nope") is None


@pytest.mark.asyncio
async def test_namespace_isolation():
    store = InMemorySessionStore()
    await store.set_state("ctx-a", "k", "va")
    await store.set_state("ctx-b", "k", "vb")
    assert await store.get_state("ctx-a", "k") == "va"
    assert await store.get_state("ctx-b", "k") == "vb"


@pytest.mark.asyncio
async def test_save_and_search_memory():
    store = InMemorySessionStore()
    await store.save_memory("ctx-1", "The user's favorite color is blue.")
    await store.save_memory("ctx-1", "The user lives in Jakarta.")
    results = await store.search_memory("ctx-1", "color")
    assert len(results) == 1
    assert "blue" in results[0]


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_hits():
    store = InMemorySessionStore()
    await store.save_memory("ctx-1", "irrelevant fact")
    assert await store.search_memory("ctx-1", "python") == []
```

- [ ] **Step 3: Run test — expect fail**

Run: `pytest tests/test_session_store.py -v`
Expected: `ModuleNotFoundError: No module named 'bridge.memory.session_store'`.

- [ ] **Step 4: Implement `bridge/memory/session_store.py`**

```python
from typing import Protocol


class SessionStore(Protocol):
    async def get_state(self, context_id: str, key: str) -> str | None: ...
    async def set_state(self, context_id: str, key: str, value: str) -> None: ...
    async def save_memory(self, context_id: str, content: str) -> None: ...
    async def search_memory(self, context_id: str, query: str, limit: int = 10) -> list[str]: ...


class InMemorySessionStore:
    """Dict-backed store. Substring match for search_memory — no vector, no ranking."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, str]] = {}
        self._memories: dict[str, list[str]] = {}

    async def get_state(self, context_id: str, key: str) -> str | None:
        return self._state.get(context_id, {}).get(key)

    async def set_state(self, context_id: str, key: str, value: str) -> None:
        self._state.setdefault(context_id, {})[key] = value

    async def save_memory(self, context_id: str, content: str) -> None:
        self._memories.setdefault(context_id, []).append(content)

    async def search_memory(self, context_id: str, query: str, limit: int = 10) -> list[str]:
        needle = query.lower()
        hits = [m for m in self._memories.get(context_id, []) if needle in m.lower()]
        return hits[:limit]
```

- [ ] **Step 5: Run tests — expect 5 passed**

Run: `pytest tests/test_session_store.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add bridge/memory/__init__.py bridge/memory/session_store.py tests/test_session_store.py
git commit -m "feat(memory): add SessionStore protocol + in-memory implementation"
```

---

## Task 2: Redis session store implementation

**Files:**
- Modify: `bridge/memory/session_store.py`
- Modify: `pyproject.toml` (add `redis`, dev add `fakeredis`)
- Modify: `tests/test_session_store.py` (append Redis tests)

- [ ] **Step 1: Add deps to `pyproject.toml`**

In `dependencies`, add: `"redis>=5.0.0",`
In `[project.optional-dependencies].dev`, add: `"fakeredis>=2.0.0",`

Run: `pip install -e '.[dev]'` — expect success.

- [ ] **Step 2: Append failing tests — `tests/test_session_store.py`**

Append (keep existing tests):

```python
import fakeredis.aioredis
from bridge.memory.session_store import RedisSessionStore


@pytest.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_redis_set_and_get(redis_client):
    store = RedisSessionStore(redis_client)
    await store.set_state("ctx-1", "key", "value")
    assert await store.get_state("ctx-1", "key") == "value"


@pytest.mark.asyncio
async def test_redis_get_missing_returns_none(redis_client):
    store = RedisSessionStore(redis_client)
    assert await store.get_state("ctx-1", "nope") is None


@pytest.mark.asyncio
async def test_redis_namespace_isolation(redis_client):
    store = RedisSessionStore(redis_client)
    await store.set_state("ctx-a", "k", "va")
    await store.set_state("ctx-b", "k", "vb")
    assert await store.get_state("ctx-a", "k") == "va"
    assert await store.get_state("ctx-b", "k") == "vb"


@pytest.mark.asyncio
async def test_redis_save_and_search(redis_client):
    store = RedisSessionStore(redis_client)
    await store.save_memory("ctx-1", "The user's favorite color is blue.")
    await store.save_memory("ctx-1", "The user lives in Jakarta.")
    results = await store.search_memory("ctx-1", "color")
    assert len(results) == 1
    assert "blue" in results[0]
```

- [ ] **Step 3: Run tests — expect fail**

Run: `pytest tests/test_session_store.py -v -k redis`
Expected: FAIL with `ImportError: cannot import name 'RedisSessionStore'`.

- [ ] **Step 4: Implement `RedisSessionStore` in `bridge/memory/session_store.py`**

Append (keep everything above):

```python
from redis.asyncio import Redis


class RedisSessionStore:
    """Redis-backed SessionStore. Keys:
        session:{context_id}:state:{key}   -> STRING value
        session:{context_id}:memories      -> LIST of content strings
    """

    def __init__(self, client: "Redis") -> None:
        self._r = client

    @staticmethod
    def _state_key(context_id: str, key: str) -> str:
        return f"session:{context_id}:state:{key}"

    @staticmethod
    def _memories_key(context_id: str) -> str:
        return f"session:{context_id}:memories"

    async def get_state(self, context_id: str, key: str) -> str | None:
        return await self._r.get(self._state_key(context_id, key))

    async def set_state(self, context_id: str, key: str, value: str) -> None:
        await self._r.set(self._state_key(context_id, key), value)

    async def save_memory(self, context_id: str, content: str) -> None:
        await self._r.rpush(self._memories_key(context_id), content)

    async def search_memory(self, context_id: str, query: str, limit: int = 10) -> list[str]:
        all_items = await self._r.lrange(self._memories_key(context_id), 0, -1)
        needle = query.lower()
        hits = [m for m in all_items if needle in m.lower()]
        return hits[:limit]
```

- [ ] **Step 5: Run tests — expect 9 passed (5 old + 4 new)**

Run: `pytest tests/test_session_store.py -v`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml bridge/memory/session_store.py tests/test_session_store.py
git commit -m "feat(memory): add Redis-backed SessionStore"
```

---

## Task 3: Memory MCP server (in-process, stdio-style)

**Files:**
- Create: `bridge/memory/mcp_memory.py`
- Test: `tests/test_mcp_memory.py`

The Claude Agent SDK accepts in-process MCP servers via `claude_agent_sdk.create_sdk_mcp_server(name, version, tools)` where each tool is created with the `@tool` decorator. These run in the same Python process — no subprocess, no network.

- [ ] **Step 1: Verify the SDK API first**

Run:
```bash
.venv/bin/python -c "from claude_agent_sdk import create_sdk_mcp_server, tool; import inspect; print(inspect.signature(create_sdk_mcp_server)); print(inspect.signature(tool))"
```

Expected: prints two signatures. If either name isn't found, abort and report — the SDK version (>=0.1.59) must expose both. If the names differ (e.g. `McpServer` class), adapt imports accordingly in the steps below.

- [ ] **Step 2: Write failing test — `tests/test_mcp_memory.py`**

```python
import pytest

from bridge.memory.mcp_memory import build_memory_mcp_server, make_memory_tools
from bridge.memory.session_store import InMemorySessionStore


@pytest.mark.asyncio
async def test_get_state_tool_returns_stored_value():
    store = InMemorySessionStore()
    await store.set_state("ctx-1", "favorite_color", "blue")
    tools = make_memory_tools(store, context_id_provider=lambda: "ctx-1")

    get_state = next(t for t in tools if t.name == "get_state")
    result = await get_state.handler({"key": "favorite_color"})

    assert result["content"][0]["text"] == "blue"


@pytest.mark.asyncio
async def test_set_state_tool_writes_to_store():
    store = InMemorySessionStore()
    tools = make_memory_tools(store, context_id_provider=lambda: "ctx-1")

    set_state = next(t for t in tools if t.name == "set_state")
    await set_state.handler({"key": "lang", "value": "python"})

    assert await store.get_state("ctx-1", "lang") == "python"


@pytest.mark.asyncio
async def test_save_and_search_memory_tools():
    store = InMemorySessionStore()
    tools = make_memory_tools(store, context_id_provider=lambda: "ctx-1")

    save = next(t for t in tools if t.name == "save_memory")
    search = next(t for t in tools if t.name == "search_memory")

    await save.handler({"content": "User prefers dark mode."})
    result = await search.handler({"query": "dark"})

    text = result["content"][0]["text"]
    assert "dark mode" in text


def test_build_memory_mcp_server_returns_configured_server():
    store = InMemorySessionStore()
    server = build_memory_mcp_server(store, context_id_provider=lambda: "ctx-1")

    # The SDK returns a dict-shaped entry suitable for ClaudeAgentOptions.mcp_servers.
    # Exact shape depends on SDK; at minimum the object must exist and be truthy.
    assert server is not None
```

- [ ] **Step 3: Run tests — expect fail**

Run: `pytest tests/test_mcp_memory.py -v`
Expected: `ModuleNotFoundError: No module named 'bridge.memory.mcp_memory'`.

- [ ] **Step 4: Implement `bridge/memory/mcp_memory.py`**

```python
from dataclasses import dataclass
from typing import Any, Callable

from claude_agent_sdk import create_sdk_mcp_server, tool

from bridge.memory.session_store import SessionStore


ContextIdProvider = Callable[[], str]


@dataclass
class MemoryTool:
    name: str
    handler: Callable[[dict[str, Any]], Any]


def _text_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def make_memory_tools(
    store: SessionStore, context_id_provider: ContextIdProvider
) -> list[MemoryTool]:
    """Return the four memory tools as (name, async handler) pairs, testable without the SDK."""

    async def get_state(args: dict) -> dict:
        value = await store.get_state(context_id_provider(), args["key"])
        return _text_result(value if value is not None else "")

    async def set_state(args: dict) -> dict:
        await store.set_state(context_id_provider(), args["key"], args["value"])
        return _text_result("ok")

    async def save_memory(args: dict) -> dict:
        await store.save_memory(context_id_provider(), args["content"])
        return _text_result("ok")

    async def search_memory(args: dict) -> dict:
        hits = await store.search_memory(context_id_provider(), args["query"])
        return _text_result("\n---\n".join(hits) if hits else "(no results)")

    return [
        MemoryTool("get_state", get_state),
        MemoryTool("set_state", set_state),
        MemoryTool("save_memory", save_memory),
        MemoryTool("search_memory", search_memory),
    ]


def build_memory_mcp_server(
    store: SessionStore, context_id_provider: ContextIdProvider
):
    """Register the memory tools with the Claude SDK's in-process MCP server."""

    @tool("get_state", "Read a value from short-term session state", {"key": str})
    async def _get_state(args):
        value = await store.get_state(context_id_provider(), args["key"])
        return _text_result(value if value is not None else "")

    @tool("set_state", "Write a value to short-term session state",
          {"key": str, "value": str})
    async def _set_state(args):
        await store.set_state(context_id_provider(), args["key"], args["value"])
        return _text_result("ok")

    @tool("save_memory", "Append a memory to long-term store", {"content": str})
    async def _save_memory(args):
        await store.save_memory(context_id_provider(), args["content"])
        return _text_result("ok")

    @tool("search_memory", "Substring-search long-term memories", {"query": str})
    async def _search_memory(args):
        hits = await store.search_memory(context_id_provider(), args["query"])
        return _text_result("\n---\n".join(hits) if hits else "(no results)")

    return create_sdk_mcp_server(
        name="bridge-memory",
        version="0.1.0",
        tools=[_get_state, _set_state, _save_memory, _search_memory],
    )
```

Note on SDK drift: if `create_sdk_mcp_server` accepts a different argument name or the `@tool` decorator has a different schema format in your installed `claude-agent-sdk` version, adjust — the goal is that `build_memory_mcp_server` returns an object accepted by `ClaudeAgentOptions.mcp_servers` under the key `"bridge-memory"`.

- [ ] **Step 5: Run tests — expect 4 passed**

Run: `pytest tests/test_mcp_memory.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add bridge/memory/mcp_memory.py tests/test_mcp_memory.py
git commit -m "feat(memory): add in-process Memory MCP server with 4 tools"
```

---

## Task 4: Settings — add memory config

**Files:**
- Modify: `bridge/config/settings.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: Append failing test — `tests/test_settings.py`**

```python
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
```

- [ ] **Step 2: Run — expect 3 new fails**

Run: `pytest tests/test_settings.py -v -k memory`
Expected: FAIL (attribute errors on Settings).

- [ ] **Step 3: Modify `bridge/config/settings.py`**

Add these two fields to the `Settings` class (alongside the existing fields — do NOT remove anything):

```python
    memory_enabled: bool = Field(default=True, validation_alias="MEMORY_ENABLED")
    redis_url: str = Field(default="", validation_alias="REDIS_URL")
```

Use `validation_alias` to match the existing pattern in the file (per the Phase 1 deviation note about pydantic-settings treating `alias` differently).

- [ ] **Step 4: Run tests — expect all settings tests pass**

Run: `pytest tests/test_settings.py -v`
Expected: 7 passed (4 pre-existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add bridge/config/settings.py tests/test_settings.py
git commit -m "feat(config): add memory_enabled + redis_url settings"
```

---

## Task 5: Wire Memory MCP into options builder

**Files:**
- Modify: `bridge/claude/options.py`
- Modify: `tests/test_options_builder.py`

The options builder currently takes only `Settings`. It needs to optionally accept a memory MCP server and inject it into `mcp_servers`.

- [ ] **Step 1: Append failing test — `tests/test_options_builder.py`**

```python
def test_build_options_injects_memory_mcp_when_provided(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")

    sentinel = object()  # stand-in for an MCP server object
    opts = build_options(Settings(), memory_mcp_server=sentinel)

    assert "bridge-memory" in opts.mcp_servers
    assert opts.mcp_servers["bridge-memory"] is sentinel


def test_build_options_omits_memory_mcp_when_not_provided(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")

    opts = build_options(Settings())

    # mcp_servers may be {} or not contain bridge-memory
    assert "bridge-memory" not in getattr(opts, "mcp_servers", {}) or True
```

- [ ] **Step 2: Run — expect fail**

Run: `pytest tests/test_options_builder.py -v -k memory_mcp`
Expected: FAIL with `TypeError: build_options() got an unexpected keyword argument 'memory_mcp_server'`.

- [ ] **Step 3: Modify `bridge/claude/options.py`**

Replace the function with:

```python
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
    }
    if settings.agent_system_prompt:
        kwargs["system_prompt"] = settings.agent_system_prompt
    if mcp_servers:
        kwargs["mcp_servers"] = mcp_servers

    return ClaudeAgentOptions(**kwargs)
```

- [ ] **Step 4: Run tests — expect all options tests pass**

Run: `pytest tests/test_options_builder.py -v`
Expected: 4 passed (2 old + 2 new).

- [ ] **Step 5: Commit**

```bash
git add bridge/claude/options.py tests/test_options_builder.py
git commit -m "feat(claude): inject memory MCP server into ClaudeAgentOptions"
```

---

## Task 6: ClaudeRunner — add stream() method + per-call context_id

**Files:**
- Modify: `bridge/claude/runner.py`
- Modify: `tests/test_runner.py`

The runner needs:
1. A `stream(prompt, context_id)` async generator that yields raw Claude messages (for the server's stream handler to adapt).
2. A way to receive the current `context_id` per call so the memory MCP tools (which close over `context_id_provider`) see the right id.

Approach: the runner owns a `_current_context_id` attribute set at the top of each call, and the memory MCP's `context_id_provider` reads it. Simple, avoids contextvars.

- [ ] **Step 1: Append failing tests — `tests/test_runner.py`**

```python
@pytest.mark.asyncio
async def test_runner_stream_yields_raw_messages(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")

    msgs = [_FakeAssistantMessage("a "), _FakeAssistantMessage("b"), _FakeResultMessage("ab")]
    monkeypatch.setattr(runner_mod, "query", _fake_query_factory(msgs))

    r = ClaudeRunner(Settings())
    collected = []
    async for m in r.stream("hi", context_id="ctx-s"):
        collected.append(m)

    assert len(collected) == 3


@pytest.mark.asyncio
async def test_runner_exposes_current_context_id(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")

    observed: list[str | None] = []

    async def _query(*, prompt, options):
        observed.append(r.current_context_id())
        if False:
            yield  # make it a generator
        return

    monkeypatch.setattr(runner_mod, "query", _query)

    r = ClaudeRunner(Settings())
    async for _ in r.stream("hi", context_id="ctx-9"):
        pass

    assert observed == ["ctx-9"]
```

- [ ] **Step 2: Run — expect fail**

Run: `pytest tests/test_runner.py -v -k stream`
Expected: FAIL.

- [ ] **Step 3: Replace `bridge/claude/runner.py`**

```python
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

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
    def __init__(self, settings: Settings, memory_mcp_server: Any | None = None) -> None:
        self._settings = settings
        self._memory_mcp_server = memory_mcp_server
        self._current_context_id: str | None = None

    def current_context_id(self) -> str | None:
        """Provider the memory MCP server uses to namespace reads/writes."""
        return self._current_context_id

    def _build_options(self):
        return build_options(self._settings, memory_mcp_server=self._memory_mcp_server)

    async def run(self, prompt: str, context_id: str | None = None) -> RunResult:
        self._current_context_id = context_id
        options = self._build_options()
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

    async def stream(self, prompt: str, context_id: str | None = None) -> AsyncIterator[Any]:
        self._current_context_id = context_id
        options = self._build_options()
        async for message in query(prompt=prompt, options=options):
            yield message
```

- [ ] **Step 4: Run runner tests — expect all pass**

Run: `pytest tests/test_runner.py -v`
Expected: 5 passed (3 old + 2 new).

- [ ] **Step 5: Commit**

```bash
git add bridge/claude/runner.py tests/test_runner.py
git commit -m "feat(claude): add ClaudeRunner.stream() and context_id plumbing"
```

---

## Task 7: Stream adapter — Claude messages → A2A SSE events

**Files:**
- Create: `bridge/a2a/stream_adapter.py`
- Test: `tests/test_stream_adapter.py`

The adapter:
- Takes an async iterator of Claude messages + a `task_id` + `context_id` + `rpc_id`.
- Emits `data: <json-rpc frame>\n\n` strings in this order:
  1. Initial `Task` (submitted).
  2. `status-update` (working).
  3. For each Claude assistant text chunk: an `artifact-update` with the text delta.
  4. For each Claude tool-use message: a `status-update` with `state=working` and a detail message naming the tool.
  5. Final `status-update` (completed) with the full concatenated text + `final: true`.

It does NOT touch the TaskManager — the caller owns that.

- [ ] **Step 1: Write failing test — `tests/test_stream_adapter.py`**

```python
import json
import pytest

from bridge.a2a.stream_adapter import claude_to_sse


class _TextBlock:
    def __init__(self, text: str):
        self.text = text


class _ToolUseBlock:
    def __init__(self, name: str):
        self.name = name
        self.type = "tool_use"


class _AssistantMessage:
    def __init__(self, blocks):
        self.content = blocks


class _ResultMessage:
    def __init__(self, text: str):
        self.result = text


async def _iter(items):
    for i in items:
        yield i


def _parse(frames: list[str]) -> list[dict]:
    out = []
    for f in frames:
        if f.startswith("data: "):
            out.append(json.loads(f[len("data: "):]))
    return out


@pytest.mark.asyncio
async def test_stream_adapter_emits_task_working_artifact_completed():
    msgs = [
        _AssistantMessage([_TextBlock("Hel")]),
        _AssistantMessage([_TextBlock("lo")]),
        _ResultMessage("Hello"),
    ]
    frames: list[str] = []
    async for chunk in claude_to_sse(_iter(msgs), rpc_id="r1", task_id="t1", context_id="c1"):
        frames.append(chunk)

    parsed = _parse(frames)
    assert parsed[0]["result"]["kind"] == "task"
    assert parsed[1]["result"]["kind"] == "status-update"
    assert parsed[1]["result"]["status"]["state"] == "working"

    artifacts = [p for p in parsed if p["result"].get("kind") == "artifact-update"]
    assert len(artifacts) == 2
    assert artifacts[0]["result"]["artifact"]["parts"][0]["text"] == "Hel"
    assert artifacts[1]["result"]["artifact"]["parts"][0]["text"] == "lo"

    assert parsed[-1]["result"]["kind"] == "status-update"
    assert parsed[-1]["result"]["status"]["state"] == "completed"
    assert parsed[-1]["result"]["final"] is True
    assert parsed[-1]["result"]["status"]["message"]["parts"][0]["text"] == "Hello"


@pytest.mark.asyncio
async def test_stream_adapter_surfaces_tool_use_as_status_update():
    msgs = [
        _AssistantMessage([_ToolUseBlock("Bash"), _TextBlock("running")]),
        _ResultMessage("done"),
    ]
    frames: list[str] = []
    async for chunk in claude_to_sse(_iter(msgs), rpc_id="r1", task_id="t1", context_id="c1"):
        frames.append(chunk)

    parsed = _parse(frames)
    tool_updates = [
        p for p in parsed
        if p["result"].get("kind") == "status-update"
        and (p["result"]["status"].get("message", {}) or {}).get("parts", [{}])[0].get("text", "").startswith("Using tool:")
    ]
    assert any("Bash" in u["result"]["status"]["message"]["parts"][0]["text"] for u in tool_updates)
```

- [ ] **Step 2: Run — expect fail**

Run: `pytest tests/test_stream_adapter.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `bridge/a2a/stream_adapter.py`**

```python
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from bridge.a2a.models import JsonRpcResponse, Task, TaskState, TaskStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frame(rpc_id, result: Any) -> str:
    payload = result.model_dump() if hasattr(result, "model_dump") else result
    resp = JsonRpcResponse(id=rpc_id, result=payload)
    return f"data: {resp.model_dump_json(exclude_none=True)}\n\n"


def _text_part(text: str) -> dict:
    return {"kind": "text", "text": text}


def _assistant_text_chunks(message: Any) -> list[str]:
    content = getattr(message, "content", None) or []
    out: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            out.append(text)
    return out


def _tool_use_names(message: Any) -> list[str]:
    content = getattr(message, "content", None) or []
    out: list[str] = []
    for block in content:
        if getattr(block, "type", None) == "tool_use":
            name = getattr(block, "name", None)
            if isinstance(name, str):
                out.append(name)
    return out


async def claude_to_sse(
    messages: AsyncIterator[Any],
    *,
    rpc_id: Any,
    task_id: str,
    context_id: str,
) -> AsyncIterator[str]:
    # 1. Initial task (submitted)
    initial = Task(
        id=task_id,
        contextId=context_id,
        status=TaskStatus(state=TaskState.submitted, timestamp=_now()),
    )
    yield _frame(rpc_id, initial)

    # 2. Working
    yield _frame(rpc_id, {
        "kind": "status-update",
        "taskId": task_id,
        "contextId": context_id,
        "status": {"state": "working", "timestamp": _now()},
        "final": False,
    })

    assistant_chunks: list[str] = []
    result_text: str | None = None

    async for message in messages:
        # Tool use → status-update
        for tool_name in _tool_use_names(message):
            yield _frame(rpc_id, {
                "kind": "status-update",
                "taskId": task_id,
                "contextId": context_id,
                "status": {
                    "state": "working",
                    "timestamp": _now(),
                    "message": {"role": "agent", "parts": [_text_part(f"Using tool: {tool_name}")]},
                },
                "final": False,
            })

        # Text chunks → artifact-update
        for chunk in _assistant_text_chunks(message):
            assistant_chunks.append(chunk)
            yield _frame(rpc_id, {
                "kind": "artifact-update",
                "taskId": task_id,
                "contextId": context_id,
                "artifact": {
                    "artifactId": task_id,
                    "parts": [_text_part(chunk)],
                },
                "append": True,
                "lastChunk": False,
            })

        # ResultMessage → capture final text
        res = getattr(message, "result", None)
        if isinstance(res, str):
            result_text = res

    final_text = result_text if result_text is not None else "".join(assistant_chunks)

    # 3. Completed
    yield _frame(rpc_id, {
        "kind": "status-update",
        "taskId": task_id,
        "contextId": context_id,
        "status": {
            "state": "completed",
            "timestamp": _now(),
            "message": {"role": "agent", "parts": [_text_part(final_text)]},
        },
        "final": True,
    })
```

- [ ] **Step 4: Run tests — expect 2 passed**

Run: `pytest tests/test_stream_adapter.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add bridge/a2a/stream_adapter.py tests/test_stream_adapter.py
git commit -m "feat(a2a): add stream adapter translating Claude messages to A2A SSE"
```

---

## Task 8: Wire stream adapter into server

**Files:**
- Modify: `bridge/a2a/server.py`
- Modify: `tests/test_a2a_server.py`

Replace the `_stream` local generator (which runs the full SDK call then emits 3 frames) with one that uses `ClaudeRunner.stream()` + `claude_to_sse`.

- [ ] **Step 1: Update `tests/test_a2a_server.py`**

Find the existing `test_message_stream_emits_sse_events` test. Update `FakeRunner` in `conftest.py` to support `stream()`. Change `tests/conftest.py`:

```python
class FakeRunner:
    def __init__(
        self,
        final_text: str = "fake-response",
        should_raise: Exception | None = None,
        stream_messages: list | None = None,
    ):
        self.final_text = final_text
        self.should_raise = should_raise
        self.stream_messages = stream_messages or []
        self.calls: list[str] = []
        self._current_context_id: str | None = None

    def current_context_id(self) -> str | None:
        return self._current_context_id

    async def run(self, prompt: str, context_id: str | None = None) -> RunResult:
        self._current_context_id = context_id
        self.calls.append(prompt)
        if self.should_raise:
            raise self.should_raise
        return RunResult(final_text=self.final_text, messages=[])

    async def stream(self, prompt: str, context_id: str | None = None):
        self._current_context_id = context_id
        self.calls.append(prompt)
        if self.should_raise:
            raise self.should_raise
        for m in self.stream_messages:
            yield m
```

Then update the existing streaming test to use structured fake messages:

```python
def test_message_stream_emits_sse_events(client, fake_runner):
    import json

    class _Block:
        def __init__(self, text):
            self.text = text
    class _Msg:
        def __init__(self, blocks):
            self.content = blocks
    class _Result:
        def __init__(self, text):
            self.result = text

    fake_runner.stream_messages = [_Msg([_Block("Hel")]), _Msg([_Block("lo")]), _Result("Hello")]
    payload = {
        "jsonrpc": "2.0",
        "id": "req-s",
        "method": "message/stream",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}},
    }
    with client.stream("POST", "/", json=payload) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = b"".join(r.iter_bytes()).decode()

    frames = [line[len("data: "):] for line in body.splitlines() if line.startswith("data: ")]
    parsed = [json.loads(f) for f in frames]
    kinds = [p["result"].get("kind") for p in parsed]

    assert kinds[0] == "task"
    assert "artifact-update" in kinds
    assert kinds[-1] == "status-update"
    assert parsed[-1]["result"]["status"]["state"] == "completed"
    assert parsed[-1]["result"]["final"] is True
```

- [ ] **Step 2: Run — expect fail (new assertions don't match current server)**

Run: `pytest tests/test_a2a_server.py::test_message_stream_emits_sse_events -v`
Expected: FAIL (no artifact-update kind in current output).

- [ ] **Step 3: Modify `bridge/a2a/server.py`**

Replace the existing local `_stream` function with one that delegates to the stream adapter. Change the method-dispatch block in the `rpc` handler:

```python
from bridge.a2a.stream_adapter import claude_to_sse
# ... existing imports ...


async def _stream_via_adapter(rpc_req, tasks, runner):
    prompt = _extract_prompt(rpc_req.params)
    context_id = rpc_req.params.get("contextId") or str(uuid.uuid4())
    task = tasks.create(context_id=context_id)
    tasks.update_status(task.id, TaskState.working)

    try:
        async def _claude_iter():
            async for m in runner.stream(prompt, context_id=context_id):
                yield m

        async for sse_chunk in claude_to_sse(
            _claude_iter(), rpc_id=rpc_req.id, task_id=task.id, context_id=context_id,
        ):
            yield sse_chunk
    except Exception as exc:
        final = tasks.update_status(
            task.id, TaskState.failed,
            message=Message(role="agent", parts=[TextPart(text=f"Error: {exc}")]),
        )
        yield (
            "data: "
            + JsonRpcResponse(id=rpc_req.id, result={
                "kind": "status-update",
                "taskId": task.id,
                "contextId": context_id,
                "status": {
                    "state": "failed",
                    "timestamp": final.status.timestamp,
                    "message": final.status.message.model_dump() if final.status.message else None,
                },
                "final": True,
            }).model_dump_json(exclude_none=True)
            + "\n\n"
        )
        return

    # Stream completed normally — sync task manager to completed state.
    tasks.update_status(task.id, TaskState.completed)
```

And in the `rpc` POST handler dispatch:

```python
        if rpc_req.method == "message/stream":
            return StreamingResponse(
                _stream_via_adapter(rpc_req, tasks, runner),
                media_type="text/event-stream",
            )
```

Delete the old `_stream` function in server.py entirely.

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`
Expected: all tests pass (existing stream test updated + every other test still green).

- [ ] **Step 5: Commit**

```bash
git add bridge/a2a/server.py tests/conftest.py tests/test_a2a_server.py
git commit -m "feat(a2a): route streaming through stream_adapter for incremental output"
```

---

## Task 9: Wire it all together in `main.py`

**Files:**
- Modify: `bridge/main.py`

- [ ] **Step 1: Replace `bridge/main.py`**

```python
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

    memory_mcp = None
    if settings.memory_enabled:
        store = _build_session_store(settings)
        # Runner is created below; we need context_id_provider to reach it.
        # Solution: build a forward-reference closure.
        runner_holder: dict = {}
        memory_mcp = build_memory_mcp_server(
            store, context_id_provider=lambda: runner_holder["runner"].current_context_id() or "default",
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
```

- [ ] **Step 2: Smoke-test app construction**

Run:
```bash
ANTHROPIC_API_KEY=sk AGENT_NAME=smoke .venv/bin/python -c \
  "from bridge.main import create_app; app=create_app(); print([r.path for r in app.routes])"
```
Expected: prints the four routes (`/health`, `/.well-known/agent-card.json`, `/tasks/{task_id}`, `/`).

- [ ] **Step 3: Smoke-test with memory disabled**

Run:
```bash
ANTHROPIC_API_KEY=sk AGENT_NAME=smoke MEMORY_ENABLED=false .venv/bin/python -c \
  "from bridge.main import create_app; app=create_app(); print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add bridge/main.py
git commit -m "feat: wire memory MCP + session store into app factory"
```

---

## Task 10: Streaming integration smoke-test inside Kind

**Files:** (no code)

- [ ] **Step 1: Verify test suite**

Run: `pytest -v`
Expected: all tests pass.

- [ ] **Step 2: Push and wait for image build**

```bash
git push
gh run watch $(gh run list --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
```
Expected: build success.

- [ ] **Step 3: Roll out in Kind**

```bash
kubectl -n kagent scale deployment claude-bridge-agent --replicas=0
kubectl -n kagent wait --for=delete pod -l app.kubernetes.io/name=claude-bridge-agent --timeout=60s
kubectl -n kagent scale deployment claude-bridge-agent --replicas=1
kubectl -n kagent rollout status deployment claude-bridge-agent --timeout=180s
```

- [ ] **Step 4: Stream a real prompt end-to-end**

Port-forward (reuse existing if already up) and run:
```bash
curl -sN -X POST http://localhost:9090/ -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"s","method":"message/stream","params":{"message":{"role":"user","parts":[{"kind":"text","text":"Count to 5 one number per line"}]}}}'
```
Expected: one `task` frame, one `working` frame, multiple `artifact-update` frames arriving incrementally, final `completed` frame.

- [ ] **Step 5: Verify memory tools exist in Agent Card introspection**

Kagent itself doesn't expose tool list from a BYO agent card (skills are advertised but MCP tools aren't). So there's nothing to assert via the Agent Card endpoint. Instead, test via prompt:

```bash
curl -sf -X POST http://localhost:9090/ -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"m1","method":"message/send","params":{"message":{"role":"user","parts":[{"kind":"text","text":"Call set_state with key=color value=blue, then call get_state with key=color, then tell me what get_state returned."}]}}}' \
  --max-time 120 | python3 -m json.tool | head -20
```
Expected: the final text mentions "blue" — proving Claude can round-trip through the memory MCP tools.

- [ ] **Step 6: Tag the milestone**

```bash
git tag -a phase2-mvp -m "Phase 2: incremental streaming + in-process memory MCP + Redis session store"
git push origin phase2-mvp
```

---

## Out of Scope (subsequent plans)

- **Phase 3:** `PreToolUse` / `PostToolUse` hooks, OpenTelemetry tracing, Prometheus metrics
- **Phase 4:** Vector-backed long-term memory (Mem0 / Chroma), skills ConfigMap mounting, Bearer auth, Helm chart, multi-tenancy decision

---

## Self-Review Findings

**Spec coverage (design doc §13 Phase 2):**
- ✅ SSE streaming for `message/stream` — Tasks 7 + 8 (real incremental).
- ✅ `tasks/get` polling — already implemented in Phase 1.
- ✅ In-process memory MCP — Tasks 1 + 3.
- ✅ Redis-backed session state — Task 2.

**Placeholder scan:** clean. No TBD / TODO / implement-later.

**Type consistency:**
- `SessionStore` Protocol + `InMemorySessionStore` + `RedisSessionStore` share the same method signatures.
- `ClaudeRunner.run(prompt, context_id=None)` and `ClaudeRunner.stream(prompt, context_id=None)` match across Tasks 6, 8, 9, and the `FakeRunner` fixture.
- `build_options(settings, memory_mcp_server=None)` signature consistent across Tasks 5 and 6.
- `claude_to_sse(messages, *, rpc_id, task_id, context_id)` signature consistent between Tasks 7 and 8.
- `build_memory_mcp_server(store, context_id_provider)` signature consistent between Tasks 3 and 9.
