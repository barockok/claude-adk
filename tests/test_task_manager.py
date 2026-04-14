import pytest
from bridge.a2a.models import Message, TaskState, TextPart
from bridge.a2a.task_manager import TaskManager, TaskNotFoundError


def test_create_task_returns_submitted():
    mgr = TaskManager()
    task = mgr.create(context_id="ctx-1")

    assert task.id
    assert task.contextId == "ctx-1"
    assert task.status.state == TaskState.submitted


def test_get_returns_same_task():
    mgr = TaskManager()
    created = mgr.create(context_id="ctx-1")
    fetched = mgr.get(created.id)

    assert fetched.id == created.id


def test_get_unknown_raises():
    mgr = TaskManager()
    with pytest.raises(TaskNotFoundError):
        mgr.get("nope")


def test_update_status_changes_state_and_appends_message():
    mgr = TaskManager()
    task = mgr.create(context_id="ctx-1")

    mgr.update_status(
        task.id,
        TaskState.working,
        message=Message(role="agent", parts=[TextPart(text="thinking")]),
    )
    mgr.update_status(
        task.id,
        TaskState.completed,
        message=Message(role="agent", parts=[TextPart(text="done")]),
    )

    updated = mgr.get(task.id)
    assert updated.status.state == TaskState.completed
    assert len(updated.history) == 2
    assert updated.history[-1].parts[0].text == "done"
