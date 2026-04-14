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
