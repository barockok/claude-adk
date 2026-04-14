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
