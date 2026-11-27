"""Builds a HarnessConfig from simple choices (CLI, UI, eval)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from bistharness.core.config import load_settings
from bistharness.core.enums import HarnessState
from bistharness.harness.explainer import Explainer, LLMExplainer, TemplateExplainer
from bistharness.harness.llm_client import OllamaClient
from bistharness.harness.memory import EpisodicMemory
from bistharness.harness.planner import LLMPlanner, Planner, ScenarioPlanner
from bistharness.harness.policy import Policy, load_policy
from bistharness.harness.runner import HarnessConfig, Reviewer, StateRecord
from bistharness.tools import ToolContext


def default_memory_path() -> Path:
    return load_settings().db_path.parent / "episodic.sqlite"


def ollama_client(policy: Policy, model: str | None = None) -> OllamaClient:
    cfg = policy.llm
    name = model or str(cfg["model"])
    think = False if any(name.startswith(p) for p in cfg.get("thinking_models", [])) else None
    return OllamaClient(
        name,
        host=str(cfg["host"]),
        options=dict(cfg["options"]),
        fresh=bool(cfg.get("fresh", True)),
        think=think,
    )


def build_config(
    *,
    explainer: str = "template",
    planner: str = "scenario",
    model: str | None = None,
    memory: EpisodicMemory | None = None,
    memory_path: Path | None = None,
    reviewer: Reviewer | None = None,
    progress: Callable[[str, HarnessState, StateRecord], None] | None = None,
) -> HarnessConfig:
    policy = load_policy()
    client = ollama_client(policy, model) if "llm" in (explainer, planner) else None
    ex: Explainer = LLMExplainer(client, policy) if explainer == "llm" and client else TemplateExplainer(policy)
    pl: Planner = LLMPlanner(client, policy) if planner == "llm" and client else ScenarioPlanner(policy)
    mem = memory if memory is not None else EpisodicMemory(memory_path or default_memory_path())
    return HarnessConfig(planner=pl, explainer=ex, memory=mem, reviewer=reviewer, policy=policy, progress=progress)


def tool_context() -> ToolContext:
    """For the UI layer, which may not import bistharness.tools directly."""
    return ToolContext.from_settings()
