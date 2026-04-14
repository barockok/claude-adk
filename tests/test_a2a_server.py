def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_agent_card(client):
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "test-agent"
    assert body["capabilities"]["streaming"] is False


def test_message_send_returns_task_with_result(client, fake_runner):
    fake_runner.final_text = "Hello from Claude"
    payload = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "hi"}],
            }
        },
    }
    r = client.post("/", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == "req-1"
    assert body["result"]["kind"] == "task"
    assert body["result"]["status"]["state"] == "completed"
    assert body["result"]["history"][-1]["parts"][0]["text"] == "Hello from Claude"
    assert fake_runner.calls == ["hi"]


def test_message_send_failure_returns_failed_task(client, fake_runner):
    fake_runner.should_raise = RuntimeError("boom")
    payload = {
        "jsonrpc": "2.0",
        "id": "req-2",
        "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "x"}]}},
    }
    r = client.post("/", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["status"]["state"] == "failed"


def test_unsupported_method_returns_jsonrpc_error(client):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-3",
        "method": "message/stream",
        "params": {},
    }
    r = client.post("/", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["error"]["code"] == -32601
    assert "result" not in body or body.get("result") is None


def test_get_task_returns_persisted_task(client):
    payload = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}},
    }
    created = client.post("/", json=payload).json()
    task_id = created["result"]["id"]

    r = client.get(f"/tasks/{task_id}")
    assert r.status_code == 200
    assert r.json()["id"] == task_id


def test_get_task_unknown_returns_404(client):
    r = client.get("/tasks/does-not-exist")
    assert r.status_code == 404
