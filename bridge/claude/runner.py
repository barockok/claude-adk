from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import query

from bridge.claude.options import build_options
from bridge.config.settings import Settings


@dataclass
class RunResult:
    final_text: str
    messages: list[Any] = field(default_factory=list)


def _extract_assistant_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


class ClaudeRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def run(self, prompt: str) -> RunResult:
        options = build_options(self._settings)
        collected: list[Any] = []
        result_text: str | None = None
        assistant_chunks: list[str] = []

        async for message in query(prompt=prompt, options=options):
            collected.append(message)
            res = getattr(message, "result", None)
            if isinstance(res, str):
                result_text = res
                continue
            chunk = _extract_assistant_text(message)
            if chunk:
                assistant_chunks.append(chunk)

        final_text = result_text if result_text is not None else "".join(assistant_chunks)
        return RunResult(final_text=final_text, messages=collected)
