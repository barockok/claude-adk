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
    """Return memory tools as (name, async handler) pairs — directly testable."""

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
    """Register memory tools with an in-process MCP server the Claude SDK can consume."""

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
