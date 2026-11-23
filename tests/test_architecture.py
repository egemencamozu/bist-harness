"""Static architecture rules, checked on every test run (CLAUDE.md §1, §2, §5, §12).

* layer direction: core <- data <- analytics <- backtest <- tools <- mcp_server/harness <- ui
  (analytics is pure: no data/IO layer; harness does no financial computation: no analytics/backtest);
* no cloud-LLM SDK anywhere in src/ (offline inference);
* network libraries only in bistharness.data.ingest (analysis always reads the frozen snapshot);
* analytics/ and tools/ never read data directly (no sqlite3/duckdb, no pd.read_*, no open()) — only PITRepository;
* no print() in library code (only in `main()` functions and `__main__.py` CLIs);
* absolute imports only.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "bistharness"

ALLOWED_LAYERS: dict[str, frozenset[str]] = {
    "core": frozenset({"core"}),
    "data": frozenset({"core", "data"}),
    "analytics": frozenset({"core", "analytics"}),
    "backtest": frozenset({"core", "analytics", "backtest"}),
    "tools": frozenset({"core", "data", "analytics", "backtest", "tools"}),
    "mcp_server": frozenset({"core", "data", "tools", "mcp_server"}),
    "harness": frozenset({"core", "data", "tools", "harness"}),
    "ui": frozenset({"core", "data", "harness", "ui"}),
}
CLOUD_LLM_SDKS = (
    "openai",
    "anthropic",
    "google.generativeai",
    "google.genai",
    "mistralai",
    "cohere",
    "groq",
    "litellm",
    "langchain_openai",
    "langchain_anthropic",
)
NETWORK_LIBS = ("yfinance", "requests", "httpx", "aiohttp", "urllib3", "urllib.request", "socket")
DIRECT_DATA_LIBS = ("sqlite3", "duckdb", "pyarrow")
NO_DIRECT_READ_LAYERS = frozenset({"analytics", "tools"})


def _matches(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def _imports(tree: ast.AST) -> Iterator[tuple[str, int, int]]:
    """(module, line, relative level) for every import, including function-local ones."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno, 0
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", node.lineno, node.level


def _print_calls_outside_main(tree: ast.AST) -> Iterator[int]:
    def visit(node: ast.AST, in_main: bool) -> Iterator[int]:
        for child in ast.iter_child_nodes(node):
            child_in_main = in_main or (isinstance(child, ast.FunctionDef) and child.name == "main")
            is_print = isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "print"
            if is_print and not child_in_main:
                yield child.lineno
            yield from visit(child, child_in_main)

    yield from visit(tree, False)


def _direct_reads(tree: ast.AST) -> Iterator[tuple[str, int]]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "open":
            yield "open()", node.lineno
        elif isinstance(f, ast.Attribute) and f.attr.startswith("read_") and isinstance(f.value, ast.Name):
            if f.value.id in {"pd", "pandas", "pl", "polars"}:
                yield f"{f.value.id}.{f.attr}()", node.lineno
        elif isinstance(f, ast.Attribute) and f.attr in {"read_text", "read_bytes", "open"}:
            yield f".{f.attr}()", node.lineno


def violations(module: str, tree: ast.AST) -> list[str]:
    """All rule violations of one module. `module` is its dotted name, e.g. 'bistharness.data.ingest.prices'."""
    parts = module.split(".")
    layer = parts[1] if len(parts) >= 2 else None  # None: package root (bistharness/__init__.py)
    is_cli = parts[-1] == "__main__"
    out: list[str] = []
    for imported, line, level in _imports(tree):
        where = f"{module}:{line}"
        if level:
            out.append(f"{where} relative import (use absolute 'bistharness.' imports)")
            continue
        if _matches(imported, CLOUD_LLM_SDKS):
            out.append(f"{where} imports cloud LLM SDK '{imported}' (offline inference only)")
        if _matches(imported, NETWORK_LIBS) and not module.startswith("bistharness.data.ingest"):
            out.append(f"{where} imports network library '{imported}' outside bistharness.data.ingest")
        if layer in NO_DIRECT_READ_LAYERS and _matches(imported, DIRECT_DATA_LIBS):
            out.append(f"{where} imports '{imported}' in {layer}/ (read through PITRepository)")
        if layer and imported.startswith("bistharness."):
            target = imported.split(".")[1]
            if target not in ALLOWED_LAYERS[layer]:
                out.append(f"{where} layer '{layer}' must not import layer '{target}' ({imported})")
    if layer in NO_DIRECT_READ_LAYERS:
        out += [
            f"{module}:{line} direct read {what} in {layer}/ (use PITRepository)" for what, line in _direct_reads(tree)
        ]
    if not is_cli:
        out += [f"{module}:{line} print() in library code (use logging)" for line in _print_calls_outside_main(tree)]
    return out


def _source_modules() -> Iterator[tuple[str, ast.AST]]:
    for path in sorted(SRC.rglob("*.py")):
        parts = list(path.relative_to(SRC.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        yield ".".join(parts), ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_every_layer_directory_is_classified() -> None:
    layers = {p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    assert layers == set(ALLOWED_LAYERS), f"unclassified or missing layers: {layers ^ set(ALLOWED_LAYERS)}"


def test_source_tree_obeys_architecture_rules() -> None:
    found = [v for module, tree in _source_modules() for v in violations(module, tree)]
    assert not found, "\n".join(found)


@pytest.mark.parametrize(
    ("module", "code", "expected"),
    [
        ("bistharness.analytics.x", "import sqlite3", "read through PITRepository"),
        ("bistharness.tools.x", "import pandas as pd\ndef f():\n    return pd.read_csv('a.csv')", "direct read"),
        ("bistharness.analytics.x", "from bistharness.data.db import connect", "must not import layer 'data'"),
        ("bistharness.harness.x", "from bistharness.analytics import indicators", "must not import layer 'analytics'"),
        ("bistharness.core.x", "from bistharness.tools import t", "must not import layer 'tools'"),
        ("bistharness.harness.llm_client", "import openai", "cloud LLM SDK"),
        ("bistharness.harness.llm_client", "from anthropic import Anthropic", "cloud LLM SDK"),
        ("bistharness.tools.x", "def f():\n    import yfinance", "network library"),
        ("bistharness.data.quality", "def report():\n    print('x')", "print() in library code"),
        ("bistharness.data.x", "from . import db", "relative import"),
    ],
)
def test_checker_detects_violations(module: str, code: str, expected: str) -> None:
    found = violations(module, ast.parse(code))
    assert any(expected in v for v in found), found


@pytest.mark.parametrize(
    ("module", "code"),
    [
        ("bistharness.data.ingest.yahoo", "def f():\n    import yfinance"),
        ("bistharness.data.quality", "def main():\n    print('report')"),
        ("bistharness.data.ingest.__main__", "print('x')"),
        ("bistharness.tools.x", "from bistharness.core.pit import PITRepository"),
        ("bistharness.harness.llm_client", "import ollama"),
    ],
)
def test_checker_allows_legitimate_code(module: str, code: str) -> None:
    assert violations(module, ast.parse(code)) == []
