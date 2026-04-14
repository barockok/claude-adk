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


def _fake_query_factory(messages):
    async def _fake_query(*, prompt, options):
        for m in messages:
            yield m
    return _fake_query


@pytest.mark.asyncio
async def test_runner_collects_messages_and_final_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    monkeypatch.setenv("AGENT_NAME", "x")

    msgs = [_FakeAssistantMessage("partial "), _FakeResultMessage("hello world")]
    monkeypatch.setattr(runner_mod, "query", _fake_query_factory(msgs))

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
    monkeypatch.setattr(runner_mod, "query", _fake_query_factory(msgs))

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
    r_holder: dict = {}

    async def _query(*, prompt, options):
        observed.append(r_holder["r"].current_context_id())
        if False:
            yield  # make it a generator
        return

    monkeypatch.setattr(runner_mod, "query", _query)

    r = ClaudeRunner(Settings())
    r_holder["r"] = r
    async for _ in r.stream("hi", context_id="ctx-9"):
        pass

    assert observed == ["ctx-9"]
