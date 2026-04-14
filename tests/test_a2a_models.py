from bridge.a2a.models import (
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcError,
    Message,
    TextPart,
    Task,
    TaskStatus,
    TaskState,
    AgentCard,
)


def test_jsonrpc_request_parses_message_send():
    raw = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "hello"}],
            }
        },
    }
    req = JsonRpcRequest.model_validate(raw)
    assert req.method == "message/send"
    assert req.params["message"]["parts"][0]["text"] == "hello"


def test_message_and_textpart_roundtrip():
    msg = Message(role="agent", parts=[TextPart(text="hi")])
    dumped = msg.model_dump()
    assert dumped["role"] == "agent"
    assert dumped["parts"][0]["kind"] == "text"
    assert dumped["parts"][0]["text"] == "hi"


def test_task_has_status_and_id():
    task = Task(
        id="t-1",
        contextId="ctx-1",
        status=TaskStatus(state=TaskState.completed),
        history=[Message(role="agent", parts=[TextPart(text="done")])],
    )
    assert task.status.state == TaskState.completed
    assert task.id == "t-1"


def test_jsonrpc_error_response_shape():
    resp = JsonRpcResponse(
        id="req-1",
        error=JsonRpcError(code=-32601, message="Method not found"),
    )
    dumped = resp.model_dump(exclude_none=True)
    assert dumped["jsonrpc"] == "2.0"
    assert dumped["error"]["code"] == -32601
    assert "result" not in dumped


def test_agent_card_serializes():
    card = AgentCard(
        name="x",
        description="y",
        url="http://x",
        version="1.0.0",
    )
    dumped = card.model_dump()
    assert dumped["name"] == "x"
    assert dumped["capabilities"]["streaming"] is False
