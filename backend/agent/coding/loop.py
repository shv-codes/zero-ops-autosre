"""
The inner loop: think -> use a tool -> look at the result -> repeat.

Each round, the brain (LLM or recording) sees the whole conversation and picks the
next tool. The loop stops when:
  * finish is accepted (only possible after tests passed on the current code), or
  * all test attempts are used up, or
  * the step budget runs out.
Every tool call is recorded (dashboard + audit trail).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable

from .context import ContextWindow
from .llm import ChatClient, LLMUnavailable
from .tools import TOOL_SCHEMAS, ToolBox, describe_args

logger = logging.getLogger("autosre.agent")


@dataclass
class AgentResult:
    success: bool
    reason: str
    summary: str = ""
    risk: str = ""
    risk_reason: str = ""
    attempts: int = 0
    steps: int = 0
    created_tests: list[str] = field(default_factory=list)
    last_sandbox: dict | None = None
    last_guardrails: list[dict] = field(default_factory=list)


class ForceStopped(Exception):
    """A person pressed Force stop. The live run should end at this checkpoint."""


class CodingAgent:
    def __init__(self, client: ChatClient, toolbox: ToolBox, recorder, max_steps: int = 30,
                 should_stop: Callable[[], bool] | None = None):
        self.client = client
        self.tools = toolbox
        self.recorder = recorder
        self.max_steps = max_steps
        self.should_stop = should_stop
        self.window = ContextWindow(getattr(client, "prompt_budget", None))

    def run(self, system_prompt: str, task_prompt: str) -> AgentResult:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": task_prompt}]
        self.recorder.audit("prompt", {"task": self.tools.task, "model": f"{self.client.provider}/{self.client.model}",
                                       "system": system_prompt, "user": task_prompt})
        step = 0
        idle_turns = 0
        while step < self.max_steps:
            if self.should_stop and self.should_stop():
                raise ForceStopped()
            # The model sees a compacted copy; `messages` keeps the full history.
            turn = self.client.complete(self.window.fit(messages, TOOL_SCHEMAS), TOOL_SCHEMAS)  # may raise LLMUnavailable
            self.recorder.audit("response", {"task": self.tools.task, "content": turn.content,
                                             "tool_calls": [{"name": c.name, "arguments": c.arguments} for c in turn.tool_calls]})
            if not turn.tool_calls:
                idle_turns += 1
                step += 1
                messages.append({"role": "assistant", "content": turn.content or ""})
                if idle_turns >= 3:
                    return self._result(False, "the model stopped calling tools", step)
                messages.append({"role": "user", "content": "Use the tools to continue. Call finish only after run_tests passes."})
                continue
            idle_turns = 0
            messages.append({
                "role": "assistant", "content": turn.content or "",
                "tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                               for c in turn.tool_calls],
            })
            for call in turn.tool_calls:
                step += 1
                ok, output = self.tools.execute(call.name, call.arguments)
                self.recorder.agent_step(task=self.tools.task, attempt=max(1, self.tools.state.attempts),
                                         step=step, tool=call.name, args=_short_args(call.arguments),
                                         ok=ok, result=output, thought=turn.content or "")
                label = describe_args(call.name, call.arguments)
                if call.name not in ("run_tests", "finish"):
                    self.recorder.event("AGENT", f"{'' if ok else '✗ '}{label}" + (f" — {turn.content.strip()[:140]}" if turn.content else ""))
                messages.append({"role": "tool", "tool_call_id": call.id, "content": output})

                if self.tools.state.finished:
                    return self._result(True, "finished", step)
                if self.tools.attempts_left <= 0 and not self.tools.state.last_run_passed:
                    return self._result(False, f"all {self.tools.max_attempts} test attempts failed", step)
        return self._result(False, f"step budget of {self.max_steps} exhausted", step)

    def _result(self, success: bool, reason: str, steps: int) -> AgentResult:
        st = self.tools.state
        fin = st.finished or {}
        return AgentResult(
            success=success, reason=reason, summary=fin.get("summary", ""), risk=fin.get("risk", ""),
            risk_reason=fin.get("risk_reason", ""), attempts=st.attempts, steps=steps,
            created_tests=list(st.created_tests), last_sandbox=st.last_sandbox,
            last_guardrails=list(st.last_guardrails),
        )


def _short_args(args: dict) -> dict:
    return {k: (v if not isinstance(v, str) or len(v) <= 4000 else v[:4000] + "...") for k, v in args.items()}


__all__ = ["CodingAgent", "AgentResult", "ForceStopped", "LLMUnavailable"]
