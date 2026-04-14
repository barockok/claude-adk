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
    assert server is not None
