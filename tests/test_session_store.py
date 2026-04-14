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
