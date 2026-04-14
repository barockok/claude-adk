from datetime import datetime, timezone
from typing import Any, AsyncIterator

from bridge.a2a.models import JsonRpcResponse, Task, TaskState, TaskStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frame(rpc_id: Any, result: Any) -> str:
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

        res = getattr(message, "result", None)
        if isinstance(res, str):
            result_text = res

    final_text = result_text if result_text is not None else "".join(assistant_chunks)

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
