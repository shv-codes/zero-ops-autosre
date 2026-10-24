"""Staying under free-tier token limits: context compaction, pacing and rate-limit retries."""
from types import SimpleNamespace

import httpx
import openai

from agent.coding.context import ContextWindow, TokenEstimator
from agent.coding.llm import LLMSettings, OpenAICompatClient
from agent.coding.ratelimit import RollingTokenLimiter


def conversation(n_tools=8, size=4000):
    msgs = [{"role": "system", "content": "rules"}, {"role": "user", "content": "task " * 50}]
    for i in range(n_tools):
        msgs.append({"role": "assistant", "content": f"thinking {i}", "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"output {i} " + "x" * size})
    return msgs


def test_context_window_trims_old_outputs_first_and_keeps_original():
    msgs = conversation()
    before = TokenEstimator.messages(msgs)
    fitted = ContextWindow(budget_tokens=4000).fit(msgs)
    assert TokenEstimator.messages(fitted) <= 4000 < before
    assert fitted[0] == msgs[0] and fitted[1] == msgs[1]                       # system + task intact
    assert fitted[-1]["content"] == msgs[-1]["content"]                       # latest output intact
    assert ContextWindow.TRIM_NOTE in fitted[3]["content"]                   # oldest output trimmed
    assert all(f.get("tool_call_id") == m.get("tool_call_id") for f, m in zip(fitted, msgs))  # pairs preserved
    assert ContextWindow.TRIM_NOTE not in msgs[3]["content"]                 # full history untouched


def test_context_window_noop_when_unlimited_or_small():
    msgs = conversation(1, 10)
    assert ContextWindow(None).fit(msgs) is msgs
    assert ContextWindow(100_000).fit(msgs) is msgs


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_limiter_waits_for_the_window_instead_of_failing():
    clock = FakeClock()
    limiter = RollingTokenLimiter(8000, clock=clock, sleep=clock.sleep)
    assert limiter.acquire(5000) == 0
    waited = limiter.acquire(5000)  # would exceed 8000 in the same minute
    assert 59 < waited < 61 and limiter.used() == 5000
    limiter.adjust_last(1200)  # real usage was smaller
    assert limiter.used() == 1200


def test_client_retries_after_rate_limit_using_server_hint():
    waits = []
    client = OpenAICompatClient(LLMSettings("nvidia", "https://x", "nvapi-test-key-not-real-123456", "openai/gpt-oss-120b",
                                            tokens_per_minute=8000), sleep=waits.append)
    calls = {"n": 0}
    sent = {}
    ok = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[]))],
                         usage=SimpleNamespace(total_tokens=900))

    def create(**kwargs):
        sent.update(kwargs)
        calls["n"] += 1
        if calls["n"] == 1:
            resp = httpx.Response(429, request=httpx.Request("POST", "https://x"), headers={"retry-after": "7"})
            raise openai.RateLimitError("Rate limit reached. Please try again in 7s", response=resp, body=None)
        return ok

    client._client.chat.completions.create = create
    client.complete([{"role": "user", "content": "hi"}], tools=[])
    assert calls["n"] == 2 and waits == [7.0]
    assert sent["extra_body"] == {"reasoning_effort": "low"}  # gpt-oss keeps hidden reasoning short
    assert client.prompt_budget == 8000 - 1024 - OpenAICompatClient.SAFETY_MARGIN_TOKENS


def test_groq_429_switches_to_the_next_model_without_waiting():
    from agent.coding.llm import FallbackChatClient, LLMRateLimited

    rpm = _rate_limit("Rate limit reached on tokens per minute (TPM). Please try again in 7s.", retry_after="7")

    def make(model, error=None):
        waits = []
        c = OpenAICompatClient(LLMSettings("groq", "https://x", "gsk_test_key_not_real_123456", model), sleep=waits.append)

        def create(**kwargs):
            if error:
                raise error
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=model, tool_calls=[]))],
                                   usage=None)

        c._client.chat.completions.create = create
        return c, waits

    primary, waits = make("openai/gpt-oss-120b", rpm)
    try:
        primary.complete([], [])
        raise AssertionError("expected LLMRateLimited")
    except LLMRateLimited as exc:
        assert waits == [] and exc.retry_after == 7

    backup, _ = make("openai/gpt-oss-20b")
    switches = []
    chain_waits = []
    chain = FallbackChatClient([primary, backup], on_switch=lambda a, b, why: switches.append((a, b)),
                               sleep=chain_waits.append)
    assert chain.complete([], []).content == "openai/gpt-oss-20b"
    assert chain_waits == []
    assert switches == [("openai/gpt-oss-120b", "openai/gpt-oss-20b")]


def test_last_groq_model_retries_a_429_with_jitter():
    import random

    from agent.coding.llm import FallbackChatClient, _jittered_wait

    calls = {"n": 0}
    ok = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=[]))], usage=None)
    client = OpenAICompatClient(LLMSettings("groq", "https://x", "gsk_test_key_not_real_123456", "qwen/qwen3.8-27b",
                                            rate_limit_retries=1))

    def create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _rate_limit("Rate limit reached on requests per minute (RPM). Please try again in 7s.", retry_after="7")
        return ok

    client._client.chat.completions.create = create
    waits = []
    rng = random.Random(0)
    expected = _jittered_wait(7, 0, random.Random(0))
    chain = FallbackChatClient([client], sleep=waits.append, rng=rng)
    assert chain.complete([], []).content == "ok"
    assert calls["n"] == 2 and waits == [expected] and expected > 7


def _rate_limit(msg, retry_after=None):
    headers = {"retry-after": retry_after} if retry_after else {}
    resp = httpx.Response(429, request=httpx.Request("POST", "https://x"), headers=headers)
    return openai.RateLimitError(msg, response=resp, body=None)


def test_daily_quota_fails_fast_and_fallback_switches_model():
    from agent.coding.llm import FallbackChatClient, LLMQuotaExhausted, LLMUnavailable

    def make(model, error=None):
        waits = []
        c = OpenAICompatClient(LLMSettings("groq", "https://x", "gsk_test_key_not_real_123456", model), sleep=waits.append)

        def create(**kwargs):
            if error:
                raise error
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=model, tool_calls=[]))],
                                   usage=None)

        c._client.chat.completions.create = create
        return c, waits

    daily = _rate_limit("Rate limit reached on tokens per day (TPD): Limit 200000. Please try again in 18m36.288s.")
    primary, waits = make("openai/gpt-oss-120b", daily)
    try:
        primary.complete([], [])
        raise AssertionError("expected LLMQuotaExhausted")
    except LLMQuotaExhausted:
        assert waits == []  # no pointless retries

    switches = []
    backup, _ = make("openai/gpt-oss-20b")
    chain = FallbackChatClient([primary, backup], on_switch=lambda a, b, why: switches.append((a, b)))
    assert chain.complete([], []).content == "openai/gpt-oss-20b"
    assert switches == [("openai/gpt-oss-120b", "openai/gpt-oss-20b")] and chain.model == "openai/gpt-oss-20b"

    only_dead = FallbackChatClient([make("m", daily)[0]])
    try:
        only_dead.complete([], [])
        raise AssertionError("expected LLMUnavailable")
    except LLMUnavailable:
        pass


def test_retry_hint_parsing_handles_minutes():
    c = OpenAICompatClient(LLMSettings("groq", "https://x", "gsk_test_key_not_real_123456", "m"))
    assert c._retry_after(_rate_limit("Please try again in 18m36.288s."), cap=False) > 1100
    assert c._retry_after(_rate_limit("Please try again in 7.5s.")) == 7.5
    assert c._retry_after(_rate_limit("Please try again in 120ms.")) == 1.0
