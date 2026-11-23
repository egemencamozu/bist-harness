"""Local LLM clients (CLAUDE.md §1.1, §9): Ollama on localhost only, plus a scripted client for tests.

Every call uses temperature 0, seed 42 and a JSON schema (`format`), and records the model digest and a prompt hash
so an analysis can be replayed.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from bistharness.core.errors import ConfigError
from bistharness.core.hashing import sha256_hex

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    digest: str
    prompt_hash: str
    seconds: float
    error: str | None = None  # set when the server aborted the generation (text is then "")


# Ollama aborts a generation it detects as a degenerate repetition loop with HTTP 500 "prediction aborted, token
# repeat limit reached" (seen 2026-11-23 in the A-level ablation). That is a failed answer, not a crash: the client
# returns empty text, which every caller already treats as invalid output (validator retry -> safe template; planner
# -> no proposal -> harness default; intent -> keyword rules).
ABORTED_GENERATION = ("prediction aborted", "repeat limit")


class LLMClient(Protocol):
    model: str

    def chat(self, messages: Sequence[dict[str, str]], schema: dict[str, Any]) -> LLMResponse: ...


def prompt_hash(model: str, messages: Sequence[dict[str, str]], schema: dict[str, Any], options: dict[str, Any]) -> str:
    return sha256_hex({"model": model, "messages": list(messages), "schema": schema, "options": options})


@dataclass
class OllamaClient:
    model: str
    host: str = "http://127.0.0.1:11434"
    options: dict[str, Any] = field(default_factory=lambda: {"temperature": 0.0, "seed": 42, "num_ctx": 4096})
    timeout: float = 600.0
    # Reproducibility: Ollama reuses the KV cache of an identical prompt prefix, which changes the numerics and the
    # output even at temperature 0. A cold call (model unloaded before and after) is byte-reproducible (measured
    # 2026-11-21: warm vs cold outputs differ, cold vs cold identical). Costs one model load (~5 s) per call.
    fresh: bool = True
    # Reasoning models (e.g. Qwen3.5) are run with thinking off: the answer must be the JSON object only.
    think: bool | None = None

    def __post_init__(self) -> None:
        h = urlparse(self.host).hostname
        if h not in LOCAL_HOSTS:
            raise ConfigError(f"LLM host {self.host!r} is not local; cloud/remote inference is forbidden")
        import ollama  # local HTTP client for the Ollama daemon on this machine

        self._client = ollama.Client(host=self.host, timeout=self.timeout)
        self._response_error: type[Exception] = ollama.ResponseError
        self._digest: str | None = None

    @property
    def digest(self) -> str:
        if self._digest is None:
            models = {m.model: m.digest for m in self._client.list().models}
            self._digest = str(models.get(self.model) or models.get(f"{self.model}:latest") or "unknown")
        return self._digest

    def chat(self, messages: Sequence[dict[str, str]], schema: dict[str, Any]) -> LLMResponse:
        t0 = time.perf_counter()
        if self.fresh:
            self._client.generate(model=self.model, prompt="", keep_alive=0)  # unload: no cached prefix survives
        extra: dict[str, Any] = {} if self.think is None else {"think": self.think}
        ph = prompt_hash(self.model, messages, schema, self.options)
        try:
            resp = self._client.chat(
                model=self.model,
                messages=list(messages),
                format=schema,
                options=self.options,
                keep_alive=0 if self.fresh else None,
                **extra,
            )
        except self._response_error as exc:
            msg = str(exc)
            if not any(m in msg for m in ABORTED_GENERATION):
                raise
            return LLMResponse("", self.model, self.digest, ph, time.perf_counter() - t0, error=msg[:200])
        return LLMResponse(str(resp.message.content or ""), self.model, self.digest, ph, time.perf_counter() - t0)


@dataclass
class ScriptedClient:
    """Deterministic stand-in: returns `responses` in order (or calls `fn(messages)`)."""

    responses: list[str] = field(default_factory=list)
    fn: Callable[[Sequence[dict[str, str]]], str] | None = None
    model: str = "scripted"
    calls: list[Sequence[dict[str, str]]] = field(default_factory=list)

    def chat(self, messages: Sequence[dict[str, str]], schema: dict[str, Any]) -> LLMResponse:
        self.calls.append(messages)
        text = self.fn(messages) if self.fn is not None else self.responses.pop(0)
        return LLMResponse(text, self.model, "scripted", prompt_hash(self.model, messages, schema, {}), 0.0)
