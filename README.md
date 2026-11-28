# FinTreX Analyst — an agentic, evidence-first analytics harness for BIST 100

CSE-481 Engineering Economics term project, Akdeniz University (Fall 2026, instructor Dr. Alper Özcan).
Authors: Egemen Çamözü (20220808076), Batuhan Erdem (20230808611).

FinTreX Analyst answers Turkish questions about Borsa İstanbul stocks. A local, fine-tuned language model
(`bist-analist`, Qwen3.5-4B + QLoRA, served by Ollama) understands the question, proposes a tool plan and writes the
explanation — but it never computes a number. Fifteen deterministic MCP tools read a frozen, point-in-time database
(prices, KAP financial statements, macro series, news metadata), a 17-state harness controls every step (permissions,
as-of-date lock, evidence, risk gate, output validator, episodic memory, replay) and a human approves the decision.

> The LLM interprets and explains. Python tools compute. The harness controls. The backtest verifies. Evidence is
> logged. A human makes the final decision.

## Deliverables

| Deliverable | Where |
|---|---|
| **Final technical report** | [reports/final/FinTreX_Analyst_Technical_Report.pdf](reports/final/FinTreX_Analyst_Technical_Report.pdf) (also `.docx`) |
| Technical reversal report (S3, ASELS) | [reports/scenarios/s3_technical_reversal_asels.md](reports/scenarios/s3_technical_reversal_asels.md) |
| Sector laggard / catch-up report (S1, Retail) | [reports/scenarios/s1_sector_catch_up_retail.md](reports/scenarios/s1_sector_catch_up_retail.md) |
| Weekday and multi-day pattern report (S2, THYAO) | [reports/scenarios/s2_weekday_patterns_thyao.md](reports/scenarios/s2_weekday_patterns_thyao.md) |
| Quarterly fundamentals and price reaction (S4, TUPRS) | [reports/scenarios/s4_fundamental_reaction_tuprs.md](reports/scenarios/s4_fundamental_reaction_tuprs.md) |
| Macro and contextual evidence | [reports/scenarios/macro_context.md](reports/scenarios/macro_context.md) |
| Backtest results and benchmarks | [reports/scenarios/backtest_comparisons.md](reports/scenarios/backtest_comparisons.md) |
| Agent-harness experiment comparison (A–E ablation) | report §9.3, raw results in [reports/ablation/](reports/ablation/) |
| Data dictionary | [reports/data_dictionary.md](reports/data_dictionary.md) |
| Fixed study universe and sector map | [config/universe.yaml](config/universe.yaml) |
| MCP tools and stateful harness | [src/bistharness/tools/](src/bistharness/tools/), [src/bistharness/harness/](src/bistharness/harness/), [config/harness_policy.yaml](config/harness_policy.yaml) |
| Decision log and replay | web interface (below) and `python -m bistharness.harness replay` |

Every number in the research reports is formatted from a tool envelope and each report lists the `call_id` of every
tool call, so it can be replayed.

## Key results

| Measure | Result |
|---|---|
| Instructor's golden questions (fine-tuned model) | 5/5 passed, all on the first attempt, same action as the rule-based reference 5/5 |
| First-attempt validator pass, base → fine-tuned (20 questions) | 35% → 100% |
| Answers with invented numbers, base → fine-tuned | 15% → 0% |
| Unseen free-text questions understood (30), keyword rules / base / fine-tuned | 30% / 73% / 100% |
| Rule violations with the full harness (ablation levels D and E), both models | 0% |
| Automated tests | 351 (including a look-ahead "poisoned future row" test for every tool) |

Research findings are mostly negative and reported as such: no technical, calendar or fundamental pattern in
2024–2026 survives multiple-testing correction and out-of-sample checks, and no pre-registered strategy variant beats
XU100 after costs.

## Model identity

| | |
|---|---|
| Base model | Qwen3.5-4B, fine-tuned with QLoRA (r = 16, α = 32, 2 epochs, 10,596 examples from the project's own tools) |
| Weights file | `bist-4b-q8_0.gguf` (GGUF Q8_0, 4,482,403,040 bytes) |
| Weights SHA-256 | `747068ad68cca49daa750975332c9bf1964363a881c6056ea5f0c88e3dd2a201` |
| Ollama model `bist-analist` digest | `a4ea6fc7e1b2c4173f43d40ceaab9e2c30db4ca50ce68ed014ddf042af3b1d3a` (weights + temperature 0, seed 42, context 4,096) |

The setup scripts verify this hash after download, and every analysis records the model digest in the episodic memory.

## Running it

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com) 0.40.17, and for the
model a GPU with about 6–8 GB of memory (it also runs on CPU, slowly). The database and the model are not in git; they
are release assets of this repository (tag `assets-2026-11-20`, with `SHA256SUMS.txt`). The setup script downloads
them with the GitHub CLI (`gh auth login` first), verifies every sha256 and registers the model in Ollama:

```
uv sync --extra dev --extra llm --extra ui --extra mcp --extra report
bash setup/get_assets.sh                                        # macOS / Linux
powershell -ExecutionPolicy Bypass -File setup\get_assets.ps1   # Windows
uv run pytest -q
uv run python -m bistharness.ui.web     # FinTreX Analyst web interface -> http://127.0.0.1:8501
```

Reproducing the evaluation and the reports:

```
uv run python -m eval.run_golden --explainer llm --out reports/golden_final.json
uv run python -m eval.ablation
uv run python -m eval.robustness --set v2 --e2e
uv run --extra report python -m eval.scenario_reports s1 s2 s3 s4 macro backtest
uv run python -m bistharness.harness replay --decision D-...
```

A Docker setup (`docker-compose.yml`, Ollama + the app) is included but has not been tested end to end yet.

## Repository layout

```
config/      universe and sector map, harness policy (states, permissions, validation rules), news tags
src/bistharness/
  core/      schemas, point-in-time repository, calendar, hashing, number formatting
  data/      database schema and ingest adapters (prices, KAP, macro, news, speech)
  analytics/ pure functions: indicators, events, event study, sector, weekday, fundamentals, macro
  backtest/  execution engine and strategy variants A_TECH ... E_FULL_CONTEXTUAL
  tools/     the 15 MCP tools
  harness/   17-state runner, planners, evidence, validator, LLM client, memory, replay
  ui/web/    FinTreX Analyst web interface
training/    dataset generation, QLoRA training, GGUF export
eval/        golden questions, model comparison, ablation, robustness, research-report generator
reports/     research reports, evaluation results, final technical report
tests/       unit, parity (instructor's scripts), point-in-time and harness tests
```

Design decisions and the full rule set are recorded in [CLAUDE.md](CLAUDE.md) (in Turkish; it is the working
notebook of the project). Educational research tool — not investment advice.
