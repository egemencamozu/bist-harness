"""MCP server exposing the 15 deterministic tools (mcp >= 2: MCPServer).

Each MCP tool has the same flat keyword arguments as its pydantic input model (as_of_date required) and returns the
ToolEnvelope as JSON. Invalid calls return {"status": "ERROR", "error": ...} instead of raising, so the harness can
log them as invalid_tool_call. Runs fully offline over stdio:  uv run python -m bistharness.mcp_server
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer

from bistharness.core.errors import AsOfRequiredError, DataNotFoundError
from bistharness.tools import REGISTRY, TOOL_NAMES, ToolContext, ToolInputError, run_tool
from bistharness.tools.base import ToolDef

INSTRUCTIONS = (
    "Deterministic, point-in-time BIST analytics tools. Every tool requires as_of_date (YYYY-MM-DD) and never returns "
    "information published after it. Numbers in explanations must be copied from evidence_candidates[].display. "
    "Educational research only: no investment advice, no orders, no target prices."
)


def call(name: str, arguments: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    try:
        return run_tool(name, arguments, ctx).model_dump(mode="json")
    except (ToolInputError, AsOfRequiredError, DataNotFoundError, ValueError) as exc:
        return {"tool": name, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}


def _wrapper(td: ToolDef, ctx: ToolContext) -> Callable[..., dict[str, Any]]:
    params = []
    for fname, f in td.input_model.model_fields.items():
        default = inspect.Parameter.empty if f.is_required() else f.get_default(call_default_factory=True)
        params.append(
            inspect.Parameter(fname, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=f.annotation)
        )

    def fn(**kwargs: Any) -> dict[str, Any]:
        return call(td.name, kwargs, ctx)

    fn.__name__ = td.name
    fn.__doc__ = td.description
    fn.__signature__ = inspect.Signature(params, return_annotation=dict[str, Any])  # type: ignore[attr-defined]
    fn.__annotations__ = {**{p.name: p.annotation for p in params}, "return": dict[str, Any]}
    return fn


def build_server(ctx: ToolContext | None = None) -> MCPServer:
    context = ctx or ToolContext.from_settings()
    server: MCPServer = MCPServer(name="bistharness", instructions=INSTRUCTIONS, version="1.0.0")
    for name in TOOL_NAMES:
        td = REGISTRY[name]
        server.add_tool(_wrapper(td, context), name=td.name, description=td.description)
    return server


def main() -> None:
    build_server().run("stdio")
