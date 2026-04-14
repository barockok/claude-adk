from typing import AsyncIterator, Protocol
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

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


def _extract_prompt(params: dict) -> str:
    message = params.get("message") or {}
    parts = message.get("parts") or []
    texts = [p.get("text", "") for p in parts if p.get("kind") == "text"]
    return "".join(texts)


def _sse_frame(rpc_id, result: dict) -> str:
    resp = JsonRpcResponse(id=rpc_id, result=result)
    return f"data: {resp.model_dump_json(exclude_none=True)}\n\n"


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

    async def _run_sync(rpc_req: JsonRpcRequest) -> JsonRpcResponse:
        prompt = _extract_prompt(rpc_req.params)
        context_id = rpc_req.params.get("contextId") or str(uuid.uuid4())
        task = tasks.create(context_id=context_id)
        tasks.update_status(task.id, TaskState.working)

        try:
            result = await runner.run(prompt)
        # A2A convention: runner failures surface as Task(status=failed) in `result`,
        # not as a JSON-RPC `error`. Clients can poll /tasks/{id} for the same shape.
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

    async def _stream(rpc_req: JsonRpcRequest) -> AsyncIterator[str]:
        prompt = _extract_prompt(rpc_req.params)
        context_id = rpc_req.params.get("contextId") or str(uuid.uuid4())
        task = tasks.create(context_id=context_id)

        # Frame 1: initial Task object so the client knows the task id.
        yield _sse_frame(rpc_req.id, task.model_dump())

        # Frame 2: working status-update.
        working = tasks.update_status(task.id, TaskState.working)
        yield _sse_frame(rpc_req.id, {
            "kind": "status-update",
            "taskId": task.id,
            "contextId": context_id,
            "status": {"state": "working", "timestamp": working.status.timestamp},
            "final": False,
        })

        try:
            result = await runner.run(prompt)
        except Exception as exc:
            final = tasks.update_status(
                task.id,
                TaskState.failed,
                message=Message(role="agent", parts=[TextPart(text=f"Error: {exc}")]),
            )
            yield _sse_frame(rpc_req.id, {
                "kind": "status-update",
                "taskId": task.id,
                "contextId": context_id,
                "status": {
                    "state": "failed",
                    "timestamp": final.status.timestamp,
                    "message": final.status.message.model_dump() if final.status.message else None,
                },
                "final": True,
            })
            return

        final = tasks.update_status(
            task.id,
            TaskState.completed,
            message=Message(role="agent", parts=[TextPart(text=result.final_text)]),
        )
        yield _sse_frame(rpc_req.id, {
            "kind": "status-update",
            "taskId": task.id,
            "contextId": context_id,
            "status": {
                "state": "completed",
                "timestamp": final.status.timestamp,
                "message": final.status.message.model_dump() if final.status.message else None,
            },
            "final": True,
        })

    @router.post("/")
    async def rpc(request: Request):
        raw = await request.json()
        try:
            rpc_req = JsonRpcRequest.model_validate(raw)
        except Exception as exc:
            return JsonRpcResponse(
                id=raw.get("id") if isinstance(raw, dict) else None,
                error=JsonRpcError(code=INVALID_PARAMS, message=str(exc)),
            ).model_dump(exclude_none=True)

        if rpc_req.method == "message/send":
            return (await _run_sync(rpc_req)).model_dump(exclude_none=True)

        if rpc_req.method == "message/stream":
            return StreamingResponse(_stream(rpc_req), media_type="text/event-stream")

        return JsonRpcResponse(
            id=rpc_req.id,
            error=JsonRpcError(
                code=METHOD_NOT_FOUND,
                message=f"Method '{rpc_req.method}' not supported",
            ),
        ).model_dump(exclude_none=True)

    return router
