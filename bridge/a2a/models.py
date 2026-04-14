from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class TaskState(str, Enum):
    submitted = "submitted"
    working = "working"
    input_required = "input-required"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[TextPart]
    messageId: str | None = None


class TaskStatus(BaseModel):
    state: TaskState
    message: Message | None = None
    timestamp: str | None = None


class Task(BaseModel):
    id: str
    contextId: str
    status: TaskStatus
    history: list[Message] = Field(default_factory=list)
    kind: Literal["task"] = "task"


class AgentCapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False
    stateTransitionHistory: bool = False


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = Field(default_factory=list)
    defaultInputModes: list[str] = Field(default_factory=lambda: ["text"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["text"])


class JsonRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    result: Any | None = None
    error: JsonRpcError | None = None
