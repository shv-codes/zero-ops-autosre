"""
Runs one coding task (fix / resolve_conflict / fix_ci) and picks the brain:

  live mode   -> real LLM (Groq / NVIDIA). If it can't be reached, before or during the
                 task, fall back to the recording when one exists (FR-9.1) and say so
                 loudly on the dashboard (FR-9.3).
  cached mode -> the recording. No recording for this situation -> honest failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .llm import ChatClient, LLMUnavailable, ScriptedClient
from .loop import AgentResult, CodingAgent
from .tools import ToolBox


@dataclass
class BrainInfo:
    mode: str
    provider: str = ""
    model: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    notes: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)  # calls, prompt/completion tokens (transparency)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def usage_of(client) -> dict:
    usage = getattr(client, "usage", None)
    return dict(usage) if isinstance(usage, dict) else {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def run_coding_task(*, mode: str, live_client_factory: Callable[[], ChatClient],
                    recording: ScriptedClient | None, make_toolbox: Callable[[], ToolBox],
                    restart: Callable[[], None], recorder, system_prompt: str, task_prompt: str,
                    max_steps: int, should_stop: Callable[[], bool] | None = None) -> tuple[AgentResult, BrainInfo]:
    info = BrainInfo(mode=mode)
    client: ChatClient | None = None

    if mode == "live":
        try:
            client = live_client_factory()
        except LLMUnavailable as exc:
            info.fallback_reason = str(exc)
    if client is None:
        if recording is None:
            reason = ("cached mode has no recorded decisions for this situation; switch to live mode with an API key"
                      if mode != "live" else f"LLM unavailable ({info.fallback_reason}) and no cached recording exists")
            return AgentResult(success=False, reason=reason), info
        client = recording
        if mode == "live":
            info.fallback_used = True
            recorder.event("AGENT", f"LLM unavailable ({info.fallback_reason}); using CACHED recorded responses.")
    info.provider, info.model = client.provider, client.model

    toolbox = make_toolbox()
    try:
        result = CodingAgent(client, toolbox, recorder, max_steps, should_stop=should_stop).run(system_prompt, task_prompt)
        info.usage = usage_of(client)
        return result, info
    except LLMUnavailable as exc:
        if recording is None or isinstance(client, ScriptedClient):
            return AgentResult(success=False, reason=f"LLM became unavailable: {exc}"), info
        recorder.event("AGENT", f"LLM became unavailable mid-task ({exc}); restarting this task with CACHED recorded responses.")
        info.fallback_used, info.fallback_reason = True, str(exc)
        info.provider, info.model = recording.provider, recording.model
    finally:
        toolbox.cleanup()

    restart()
    toolbox = make_toolbox()
    try:
        result = CodingAgent(recording, toolbox, recorder, max_steps, should_stop=should_stop).run(system_prompt, task_prompt)
        info.usage = usage_of(client) if client is not recording else usage_of(recording)
        return result, info
    finally:
        toolbox.cleanup()
