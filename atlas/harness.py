"""Budgets, bounded retries, usage accounting and safe diagnostic events."""

import hashlib
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

import httpx
import openai

from atlas.schemas import HarnessConfig


class BudgetExceeded(RuntimeError):
    pass


def transient(exc: Exception) -> bool:
    if isinstance(
        exc,
        (
            httpx.TimeoutException,
            httpx.NetworkError,
            openai.APIConnectionError,
            openai.RateLimitError,
            TimeoutError,
        ),
    ):
        return True
    if isinstance(exc, (httpx.HTTPStatusError, openai.APIStatusError)):
        code = (
            exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else exc.status_code
        )
        return code in {408, 429} or code >= 500
    return False


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def safe_error(exc: Exception) -> str:
    # Provider errors can contain URLs, credentials, prompt text or response bodies.
    return f"{type(exc).__name__}: operation failed; inspect configuration or retry if transient"


@dataclass
class Usage:
    limits: HarnessConfig
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unreported_usage_calls: int = 0
    retries: int = 0
    events: list[dict] = field(default_factory=list)

    def snapshot(self):
        return {
            k: getattr(self, k)
            for k in (
                "model_calls",
                "input_tokens",
                "output_tokens",
                "unreported_usage_calls",
                "retries",
            )
        }

    def invoke(self, runnable, messages):
        for attempt in range(self.limits.max_retries + 1):
            if self.model_calls >= self.limits.max_model_calls:
                raise BudgetExceeded("Model call budget exhausted")
            if self.input_tokens + self.output_tokens >= self.limits.max_tokens:
                raise BudgetExceeded("Reported token budget exhausted")
            if (
                sum(
                    len(json.dumps(m.model_dump(), ensure_ascii=False, default=str))
                    for m in messages
                )
                > self.limits.max_context_chars
            ):
                raise BudgetExceeded("Model context character budget exhausted")
            self.model_calls += 1
            started = time.perf_counter()
            try:
                result = runnable.invoke(messages)
                raw = result.get("raw") if isinstance(result, dict) else result
                usage = getattr(raw, "usage_metadata", None)
                if usage:
                    self.input_tokens += usage.get("input_tokens", 0)
                    self.output_tokens += usage.get("output_tokens", 0)
                else:
                    self.unreported_usage_calls += 1
                self.events.append(
                    {
                        "kind": "model",
                        "ok": True,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    }
                )
                return result
            except Exception as exc:
                self.events.append({"kind": "model", "ok": False, "error_type": type(exc).__name__})
                if not transient(exc) or attempt == self.limits.max_retries:
                    raise
                self.retries += 1
                time.sleep(self.limits.retry_delay * 2**attempt)


CURRENT_USAGE: ContextVar[Usage | None] = ContextVar("atlas_usage", default=None)


@contextmanager
def usage_scope(usage):
    token = CURRENT_USAGE.set(usage)
    try:
        yield
    finally:
        CURRENT_USAGE.reset(token)


def invoke_model(runnable, messages):
    usage = CURRENT_USAGE.get() or Usage(HarnessConfig())
    return usage.invoke(runnable, messages)


def compact_result(value, limit: int) -> str:
    content = json.dumps(value, ensure_ascii=False, default=str)
    if len(content) <= limit:
        return content
    # Keep valid JSON, with an explicit indication that the full artifact is in state.
    prefix = content[: max(0, limit // 2 - 100)]
    result = json.dumps(
        {"truncated": True, "preview": prefix, "note": "Full result retained in mission state"},
        ensure_ascii=False,
    )
    while len(result) > limit:
        prefix = prefix[: len(prefix) // 2]
        result = json.dumps({"truncated": True, "preview": prefix}, ensure_ascii=False)
    return result
