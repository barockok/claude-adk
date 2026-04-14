import uuid
from datetime import datetime, timezone
from threading import Lock

from bridge.a2a.models import Message, Task, TaskState, TaskStatus


class TaskNotFoundError(KeyError):
    pass


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = Lock()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create(self, context_id: str, task_id: str | None = None) -> Task:
        tid = task_id or str(uuid.uuid4())
        task = Task(
            id=tid,
            contextId=context_id,
            status=TaskStatus(state=TaskState.submitted, timestamp=self._now_iso()),
        )
        with self._lock:
            self._tasks[tid] = task
        return task

    def get(self, task_id: str) -> Task:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    def update_status(
        self,
        task_id: str,
        state: TaskState,
        message: Message | None = None,
    ) -> Task:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(task_id)
            new_history = list(task.history)
            if message is not None:
                new_history.append(message)
            updated = task.model_copy(
                update={
                    "status": TaskStatus(
                        state=state, message=message, timestamp=self._now_iso()
                    ),
                    "history": new_history,
                }
            )
            self._tasks[task_id] = updated
            return updated
