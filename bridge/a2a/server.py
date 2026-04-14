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
