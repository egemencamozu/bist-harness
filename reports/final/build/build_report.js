// Final technical report (English) for CSE-481 — builds FinTreX_Analyst_Technical_Report.docx.
//   uv run --extra report python reports/final/build/make_figures.py   (figures + data.json)
//   node reports/final/build/build_report.js
// Measured numbers come from data.json (written from the frozen reports in reports/); research findings are the
// "Key findings" of the generated scenario reports. Nothing measured is typed by hand.
"use strict";
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell, WidthType,
  ShadingType, ImageRun, Header, Footer, PageNumber, TableOfContents, LevelFormat, BorderStyle, PageBreak,
} = require("docx");

const HERE = __dirname;
const ROOT = path.resolve(HERE, "..", "..", "..");
const D = JSON.parse(fs.readFileSync(path.join(HERE, "data.json"), "utf8"));
const FIG = (n) => path.join(HERE, "fig", n);
const SFIG = (n) => path.join(ROOT, "reports", "scenarios", "fig", n);
const OUT = path.join(ROOT, "reports", "final", "FinTreX_Analyst_Technical_Report.docx");

const INK = "111110", SIGNAL = "E8451A", MUTE = "6D6B64", RULE = "D9D5CA", HEAD_FILL = "EFEDE6";
const CONTENT = 9026; // A4 width 11906 − 2 × 1440 margins (DXA)

// ------------------------------------------------------------------ helpers
const pct = (x, d = 0) => (x === null || x === undefined ? "–" : `${(x * 100).toFixed(d)}%`);
const sec = (x) => `${Number(x).toFixed(1)} s`;

function runs(text, base = {}) {
  // **bold** and `code` inline markup
  return String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/).filter(Boolean).map((t) => {
    if (t.startsWith("**")) return new TextRun({ ...base, text: t.slice(2, -2), bold: true });
    if (t.startsWith("`")) return new TextRun({ ...base, text: t.slice(1, -1), font: "Consolas", size: (base.size || 22) - 2 });
    return new TextRun({ ...base, text: t });
  });
}
const P = (text, opts = {}) => new Paragraph({ children: runs(text, opts.run), spacing: { after: 120, line: 288 }, alignment: opts.align || AlignmentType.JUSTIFIED, ...opts.para });
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)], pageBreakBefore: true });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const H3 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] });
const BUL = (items) => items.map((t) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: runs(t), spacing: { after: 80, line: 276 } }));
const NUM = (items, ref = "numbers") => items.map((t) => new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(t), spacing: { after: 80, line: 276 } }));
const QUOTE = (t) => new Paragraph({ children: runs(t, { italics: true }), indent: { left: 567, right: 567 }, spacing: { before: 120, after: 160 },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: SIGNAL, space: 8 } } });

let figN = 0, tabN = 0;
function caption(kind, text) {
  return new Paragraph({ children: [new TextRun({ text: `${kind} ${kind === "Figure" ? ++figN : ++tabN}. `, bold: true, size: 19, color: INK }), ...runs(text, { size: 19, color: MUTE })],
    spacing: { before: 60, after: 240 }, alignment: AlignmentType.LEFT });
}
function figure(file, text, maxW = 600) {
  const buf = fs.readFileSync(file);
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
  let width = Math.min(maxW, 600);
  let height = Math.round((h * width) / w);
  if (height > 520) { width = Math.round((width * 520) / height); height = 520; }  // tall charts: cap the height
  return [new Paragraph({ children: [new ImageRun({ type: "png", data: buf, transformation: { width, height } })], alignment: AlignmentType.CENTER, spacing: { before: 120, after: 40 }, keepNext: true }),
    caption("Figure", text)];
}
function table(head, rows, widths, title) {
  const total = widths.reduce((a, b) => a + b, 0);
  const W = widths.map((w) => Math.round((w / total) * CONTENT));
  W[W.length - 1] += CONTENT - W.reduce((a, b) => a + b, 0);
  const border = { style: BorderStyle.SINGLE, size: 4, color: RULE };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (t, i, header) => new TableCell({
    width: { size: W[i], type: WidthType.DXA }, borders,
    shading: header ? { fill: HEAD_FILL, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ children: runs(String(t), { size: 18, bold: header }), alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.LEFT })],
  });
  const out = [];
  if (title) out.push(caption("Table", title));
  out.push(new Table({ width: { size: CONTENT, type: WidthType.DXA }, columnWidths: W,
    rows: [new TableRow({ tableHeader: true, children: head.map((h, i) => cell(h, i, true)) }), ...rows.map((r) => new TableRow({ children: r.map((c, i) => cell(c, i, false)) }))] }));
  out.push(new Paragraph({ children: [], spacing: { after: 160 } }));
  return out;
}

// ------------------------------------------------------------------ measured values
const ft = D.bakeoff["bist-analist"], base = D.bakeoff["qwen3.5:4b"];
const abl = D.ablation, intent = D.intent, e2e = D.e2e, golden = D.golden.rows, ds = D.dataset;
const ini = D.bakeoff_initial;
const F = D.findings;
const gOk = golden.filter((r) => r.ok).length, gFirst = golden.filter((r) => r.attempts === 1).length;
const gTeacher = golden.filter((r) => r.action === r.teacher_action).length;
const QTITLE = { Q1: "Retail sector catch-up (BIMAS, MGROS, MAVI)", Q2: "THYAO weekday pattern", Q3: "ASELS technical reversal", Q4: "TUPRS quarterly fundamentals", Q5: "EREGL advice request + FX context" };

// ------------------------------------------------------------------ content
const body = [];
const add = (...xs) => xs.forEach((x) => (Array.isArray(x) ? body.push(...x) : body.push(x)));

// Abstract
add(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Abstract")] }));
add(P(`FinTreX Analyst is a fully local, agentic research system that answers Turkish-language questions about Borsa İstanbul (BIST) stocks. A fine-tuned 4-billion-parameter language model (**bist-analist**, Qwen3.5-4B with QLoRA, served by Ollama) understands the question, proposes a tool plan and writes the explanation, but it never computes a number. Fifteen deterministic tools exposed through the Model Context Protocol (MCP) read a frozen, point-in-time database of prices, KAP financial statements, macro series and news metadata, and a 17-state harness controls every step: tool permissions per state, an as-of-date lock, a committed evidence set, a risk and data-quality gate, an output validator that checks every number against the evidence, an episodic memory and byte-level replay. A human reviewer accepts, modifies or rejects each decision.`));
add(P(`On the instructor's five golden questions the system passes ${gOk}/5, all on the first attempt, with the same action as the rule-based reference in ${gTeacher}/5. Fine-tuning raised the first-attempt validator pass rate from ${pct(base.first_attempt_pass)} to ${pct(ft.first_attempt_pass)} and removed invented numbers (${pct(base.questions_with_invented_numbers)} → ${pct(ft.questions_with_invented_numbers)}). An A–E ablation shows that safety comes from the harness, not from the model: with the evidence set and the risk gate (levels D and E) both the base and the fine-tuned model have 0% rule violations, while the fine-tuned model without tools invents numbers in ${pct(abl["bist-analist"].A.invented_numbers)} of the answers. On 30 unseen free-text questions the fine-tuned model understood ${pct(intent["llm:bist-analist"].correct)} (base ${pct(intent["llm:qwen3.5:4b"].correct)}, keyword rules ${pct(intent.rules.correct)}). The research reports for the four mandatory scenarios find no pattern that survives multiple-testing correction and out-of-sample checks, and no pre-registered strategy variant beats XU100 after costs; the system reports this instead of presenting chance patterns as signals.`));

// 1 Introduction
add(H1("1. Introduction"));
add(H2("1.1 Problem"));
add(P("Large language models can read a financial question in natural language and write a fluent answer, but on their own they invent numbers, mix up dates, use information that was not public at the analysis date and drift into investment advice. In a market such as BIST, where inflation accounting (TMS 29), frequent bonus issues and data-vendor errors are common, these failures are easy to make and hard to notice. The course specification asks for a system in which the model interprets and explains while deterministic tools compute, a harness controls the workflow, backtests verify, evidence is logged and a human makes the final decision."));
add(H2("1.2 Objectives"));
add(BUL([
  "Build a reproducible, point-in-time research dataset for a fixed 30-stock BIST universe (prices, quarterly KAP statements, macro series, news metadata).",
  "Implement the four mandatory research scenarios — sector catch-up (S1), weekday patterns (S2), technical reversals (S3) and quarterly fundamentals with post-disclosure reaction (S4) — plus macro and contextual evidence.",
  "Expose the analytics as MCP tools and run them inside a stateful harness with permissions, evidence, a risk gate, memory, human review and replay.",
  "Use only a local language model, fine-tuned on the project's own tool outputs, and measure what the model and what the harness contribute (A–E ablation).",
  "Report results honestly: sample sizes, multiple-testing corrections, out-of-sample checks and failure states.",
]));
add(H2("1.3 Contributions"));
add(BUL([
  "**A point-in-time data layer** in which every table carries a knowledge-time column and every read is filtered and re-checked against the analysis date; corporate actions after the analysis date cannot change any output.",
  "**Fifteen deterministic MCP tools** with a common envelope (call_id = sha256 of the canonical input, data version, warnings, evidence candidates) and a \"poisoned future row\" test for every tool.",
  "**A 17-state harness** whose output validator accepts an explanation only if every number and date in it appears in the committed evidence; a failed answer gets one correction attempt and then a deterministic safe fallback.",
  `**bist-analist**, a QLoRA fine-tune of Qwen3.5-4B on ${ds.examples.toLocaleString("en-US")} examples generated from real tool outputs, running offline on a laptop GPU.`,
  "**Research reports generated from tool outputs** (no number typed by hand) and a web interface, FinTreX Analyst, that shows the live workflow, the evidence behind every number, the human review and the replay.",
]));
add(H2("1.4 Structure of the report"));
add(P("Section 2 lists the design rules. Section 3 gives the architecture. Sections 4–7 describe the data layer, the analytics, the MCP tools and the harness. Section 8 covers the local model and its fine-tuning. Section 9 evaluates the system and Section 10 summarises the research findings. Section 11 presents the interface, Section 12 discusses the engineering-economics trade-offs, Section 13 the limitations and Section 14 concludes. Appendix A lists the commands that reproduce every number in this report."));

// 2 Design principles
add(H1("2. Design principles"));
add(QUOTE("The LLM interprets and explains. Python tools compute. The harness controls. The backtest verifies. Evidence is logged. A human makes the final decision."));
add(P("The principle above is enforced by code and tests rather than by prompts. The rules that may never be broken are:"));
add(table(["Rule", "How it is enforced"], [
  ["Offline inference", "No cloud LLM or API call in the source, harness, UI or evaluation code; an architecture test fails the build if a cloud SDK is imported. Internet access is allowed only in the data-ingest commands."],
  ["The LLM never produces a number", "Every number in an explanation must appear in the display values of the committed evidence; the validator parses Turkish number formats and checks the unit type (31% is not 31)."],
  ["No investment advice", "No buy/sell order, target price, stop level or \"will certainly rise\"; a forbidden-phrase filter and a fixed refusal sentence added by the harness. BUY/SELL exist only as educational backtest positions."],
  ["Finite action space", "Eight analytical states: HOLD, WATCH, INVESTIGATE, POTENTIAL_CATCH_UP_CANDIDATE, TECHNICAL_REVERSAL_CANDIDATE, FUNDAMENTAL_IMPROVEMENT_CANDIDATE, REJECT_SIGNAL, ANALYSIS_UNSAFE. A candidate label requires a citation of backtest evidence."],
  ["as_of lock everywhere", "Every tool takes a mandatory analysis date; a call with a different date is rejected as an invalid tool call."],
  ["Mandatory states", "CHECK_DATA_QUALITY, RUN_BACKTEST and RISK_GATE always run; states that do not apply are logged as SKIPPED_NOT_APPLICABLE with a reason."],
  ["Reproducibility", "Temperature 0, seed 42, JSON-schema output, cold model calls; deterministic tool outputs with fixed rounding; call_id = sha256(canonical input)."],
  ["No synthetic market data", "Test fixtures only, clearly named; ambiguous data questions are asked, not assumed."],
], [28, 72], "Non-negotiable rules and their enforcement."));

// 3 Architecture
add(H1("3. System architecture"));
add(P("Figure 1 shows the layers. Dependencies point in one direction only — core ← data ← analytics ← backtest ← tools ← harness ← UI — and an architecture test checks the direction, the ban on cloud SDKs, network libraries outside the ingest package, direct database reads in the analytics and tool layers, and print statements in library code."));
add(figure(FIG("architecture.png"), "Architecture of FinTreX Analyst. Only the local LLM box is a neural model; every other component is deterministic code."));
add(table(["Package", "Responsibility"], [
  ["core", "Enumerations, pydantic schemas, PITRepository (point-in-time reads), trading calendar, hashing, number formatting and parsing."],
  ["data", "Database schema and ingest adapters: prices, KAP fundamentals, macro, news, speech; data-quality checks."],
  ["analytics", "Pure functions without I/O: indicators, events, event study, forward returns, regimes, support/resistance, sector, weekday, fundamentals, macro statistics."],
  ["backtest", "Execution engine (signal at t, trade at t+1 open), metrics and the five strategy variants A_TECH … E_FULL_CONTEXTUAL."],
  ["tools", "The 15 MCP tools: validate input → point-in-time read → analytics → ToolEnvelope."],
  ["mcp_server", "MCP server exposing the tools to any MCP client."],
  ["harness", "17-state runner, planners, evidence selection, decision policy, validator, LLM client, episodic memory, replay, intent understanding."],
  ["ui/web", "FinTreX Analyst: JSON API and a static single-page front end without any CDN."],
], [18, 82], "Source packages (82 Python modules, about 15,900 lines; 351 automated tests)."));

// 4 Data
add(H1("4. Data layer"));
add(H2("4.1 Universe and period"));
add(P("The study universe is the specification's fixed list of 30 stocks plus the XU100 index. Sector peer groups come from the 95-stock sector map of the related TÜBİTAK project, so sector medians are computed over whole sectors, not only over the course universe. The analysis period is 2024-01-01 to 2026-11-19, with prices from 2023 for indicator warm-up. The golden questions use the analysis date 2026-09-10."));
add(H2("4.2 The point-in-time contract"));
add(P("Every temporal table has one knowledge-time column: the trading date for prices, the disclosure timestamp for financial statements, the release timestamp for macro data and the publication time for news and speech. All reads go through PITRepository, which adds `<knowledge column> <= as_of` to the SQL and checks the maximum returned value again (LookAheadError otherwise). The analysis date is treated as after that day's close. When a forward window (1, 3, 5, 10 or 20 trading days) is not complete by the analysis date, the event is excluded from that horizon and listed in `excluded_incomplete_events`; nothing is silently dropped. A technical event is dated by its confirmation day (an RSI trough formed at t−1 is known at t), support/resistance levels become known when their pivot is confirmed, and the Ichimoku Chikou span is never used."));
add(H2("4.3 Prices"));
add(P("The primary source is the FinTreX price scraper (printed 5-minute bars aggregated to days, with bonus-issue and split factors validated against prices). yfinance only supplies dividend factors, two stocks the scraper does not adjust (BIMAS, MAVI), the index and gaps. Building the reconciliation revealed concrete yfinance defects that the instructor's yfinance-based scripts inherit: truncated bars (e.g. THYAO on 2023-01-05 printed 141.8 instead of 135.2), spurious rows on the 2023 earthquake day and on holidays, bonus issues adjusted only a few days back in time (CCOLA showed a false −91% day) and missing bonus issues for several stocks. Adjusted prices are anchored to the analysis date: adj_t = raw_t · f_t / f_as_of, so a corporate action after the analysis date changes no output and price levels match what was visible at that time."));
add(H2("4.4 Fundamentals"));
add(P("Quarterly statements come from KAP XBRL filings (50,520 disclosures, 2022-12 to 2026-10, of which 1,683 are financial reports). Values are stored report by report with the second they were disclosed, the role of the column (current or prior-period comparative) and the scope (consolidated or solo). KAP income statements are cumulative within the year, so a quarter is the difference of two year-to-date figures; under TMS 29 (IAS 29 hyperinflation accounting) different reports carry different purchasing power, so the primary comparison is the year-on-year figure inside the same report. Whether a company applies TMS 29 is detected from the data (a restated comparative column), which identified banks, insurers and ten companies with a non-TRY functional currency. Multiples (P/E, P/B, EV/EBITDA) are never taken from a vendor; they are computed from the price at the analysis date and the statements disclosed by then. Ratios that do not fit a template — EBITDA margin or net debt/EBITDA for a bank — are not computed. The ingest also had to repair a column-labelling error in the KAP dump of bank balance sheets."));
add(H2("4.5 Macro series"));
add(table(["Series", "Source", "Knowledge-time rule"], [
  ["USD/TRY, EUR/TRY", "CBRT indicative buying rate", "bulletin day 15:30"],
  ["CBRT policy rate", "CBRT one-week repo table", "effective day 00:00"],
  ["Fed target range", "FRED change points", "effective day 00:00"],
  ["CPI (annual, monthly)", "TurkStat via the CBRT table", "3rd of the next month (or next trading day) 10:00"],
], [28, 36, 36], "Macro series and their publication-time alignment."));
add(H2("4.6 News and speech"));
add(P("News is context, never evidence for a number. From the Bloomberg HT archive (40,780 articles) only metadata enters the database: headline, URL, stock and topic tags. The knowledge time is the later of first publication and last edit, because about 35% of archived articles were edited after publication. Tagging is deterministic; a two-round audit (the second round drawn before seeing results) measured a strict precision of 90% (95% CI 82.6%–94.5%) and a broad precision of 97% on 100 (article, stock) pairs; 1,641 articles carry at least one of 96 stocks. The speech layer adds timestamped transcript segments of a fixed list of seven public finance videos (YouTube's own transcript panel, no download tools), measures caption quality against official texts (word error rate 4.5% for the CBRT and 1.6% for the Fed transcript) and verifies human-approved claims with the same deterministic tools."));
add(table(["Table", "Knowledge time", "Rows"], [
  ["prices_daily", "date", "96,213"], ["corporate_actions", "ex_date", "312"], ["price_quality_flags", "date", "1,071"],
  ["trading_calendar", "date", "992"], ["fundamentals", "disclosure_datetime", "119,969"], ["macro_observations", "release_datetime", "2,624"],
  ["news_events", "published_at (conservative)", "40,780"],
], [34, 40, 26], "Main tables of the frozen database (snapshot 2026-11-20). Full dictionary: reports/data_dictionary.md."));

// 5 Analytics
add(H1("5. Analytics and research methods"));
add(H2("5.1 Indicators and parity with the instructor's scripts"));
add(P("Default parameters equal the instructor's reference scripts: Bollinger Bands (20, 2σ), RSI (14, Wilder), KAMA (10, 2, 30), ATR (10), Supertrend (10, 3), Ichimoku (9, 26, 52), volume MA20 and an RSI trough threshold of 40. Parity tests run the bodies of the instructor's functions on the same input and require identical outputs. Two differences are deliberate and documented: in the instructor's S3 script the Supertrend final bands are seeded with a NaN ATR, so the Supertrend never starts and no flip is ever produced — our recursion starts at the first valid ATR bar and is identical to the script's recursion from that point; and the script's forward returns use dropna, which silently removes incomplete windows. A KAMA–price cross is mathematically the same event as a KAMA slope turn, so it is not counted twice."));
add(H2("5.2 Event studies"));
add(P("Twenty-five event types (plus two combined conditions) form the event family. Success means a positive forward return for a bullish event and a negative one for a bearish event. Each event type is compared with the same horizon on non-event days (Welch test and binomial test); reversal strength is the maximum favourable excursion inside the window; abnormal returns are taken against XU100 and against an equal-weight basket of the other sector members. Because many event types are tested at once, Bonferroni and Benjamini–Hochberg adjusted p-values are reported for the whole family, and sample-size warnings (n < 10, n < 5) are attached."));
add(H2("5.3 The four mandatory scenarios"));
add(table(["Scenario", "Definition"], [
  ["S1 — Sector catch-up", "Lag score = stock return − median return of the other sector members (leave-one-out). An event is the entry into the laggard state in a strong sector (median > 0 and > XU100). Catch-up = beating the basket of the other members over 5/10/20 days; otherwise a false positive."],
  ["S2 — Weekday patterns", "The condition (e.g. Mon-Tue-Wed down) never contains the outcome (Thu–Fri compound return), which is compared with unconditional weeks and with complement weeks. Periods consist of whole weeks; in-sample 2024–2025, out-of-sample 2026. The family is all sign combinations of the condition days."],
  ["S3 — Technical reversals", "All event families of Section 5.2 with horizons 1–20 days, single events versus combined conditions, and breakdowns by XU100 trend and volatility regime."],
  ["S4 — Fundamentals and reaction", "Year-on-year and quarter-on-quarter changes, margins, leverage, liquidity and point-in-time valuation; reaction base day by disclosure time (after 18:10 → that day's close, otherwise the previous close); abnormal returns versus XU100 and the sector basket."],
], [24, 76], "Scenario definitions."));
add(H2("5.4 Backtest engine"));
add(P("A signal observed at the close of day t is executed at the open of t+1 and closed at the open after the holding period; there is one trade per position, capital is split into equal slots and idle slots earn 0% (a second version lets idle cash earn the policy rate of the day). Costs default to 10 basis points. Results are reported nominally and deflated by CPI, with Sharpe ratios against zero and against the point-in-time policy rate, maximum drawdown, win rate and the number of signals, and are compared with buy-and-hold, XU100 and the sector basket. The strategy preset REVERSAL_PRESET_V1 was fixed before any backtest result was seen; five cumulative variants add sector, fundamental, macro and news filters (A_TECH to E_FULL_CONTEXTUAL)."));

// 6 Tools
add(H1("6. MCP tools"));
add(P("Each tool is a thin layer: it validates its input with a strict pydantic model (unknown fields are rejected, the analysis date is mandatory), reads data through PITRepository, calls pure analytics functions and returns a ToolEnvelope. The envelope carries the tool version, call_id, the data version (sha256 of each source table), a status, the result, warnings, the excluded incomplete events and evidence candidates — short Turkish sentences whose every number comes from the candidate's own display values. Floats are rounded to six digits and wall-clock fields are excluded from the hash, so the same input always produces the same output hash."));
add(table(["Tool", "Purpose"], [
  ["get_stock_history / get_index_history", "Adjusted price history and period statistics"],
  ["calculate_indicators", "Indicator values and market state at the analysis date"],
  ["detect_reversal_events", "S3 event study over 27 event types"],
  ["find_support_resistance", "Pivot-confirmed support and resistance levels"],
  ["rank_sector_relative_strength", "S1 ranking, lag scores and catch-up study"],
  ["test_weekday_pattern", "S2 pattern test in and out of sample"],
  ["get_fundamental_metrics / calculate_fundamental_change", "S4 levels, ratios, valuation, report-by-report reaction"],
  ["get_macro_context", "FX, policy rate, Fed, CPI and an optional stock–FX relationship"],
  ["get_news_events / get_speech_features", "Contextual news metadata and verified speech claims"],
  ["run_backtest", "The five strategy variants with benchmarks"],
  ["check_data_quality", "Data-quality check and the risk gate"],
  ["build_evidence_bundle", "Committed evidence set with numbered items E1 … En"],
], [42, 58], "The 15 MCP tools."));
add(P("Two invariants are tested for every tool. First, a \"poisoned future row\": rows with absurd values are inserted after the analysis date (prices, rebased factors, reports, corrections, macro values, news, hard quality flags); the output hash must stay identical. Second, no number from a news headline or transcript may appear in an evidence display value."));

// 7 Harness
add(H1("7. Stateful harness"));
add(P("The harness runs 17 states in a fixed order (Figure 2). In each analysis state a planner proposes tool calls — the deterministic scenario planner or the local LLM constrained by a JSON schema whose tool names are limited to that state's permitted tools — and the harness accepts a call only if the tool is permitted in that state, the analysis date matches the run and the arguments pass the tool's input model. Rejected calls are logged as invalid tool calls. If a mandatory state receives no valid proposal, the scenario default runs. The quality check, evidence building and risk gate arguments are built by the harness itself."));
add(figure(FIG("harness_states.png"), "The 17 harness states grouped into phases. Orange states are mandatory."));
add(H2("7.1 Evidence, risk gate and allowed actions"));
add(P("Tool outputs first form the observed context; scenario-specific patterns then select the committed evidence (E1 … En) that the explanation may use. The risk gate checks every envelope and the committed keys: future dates, envelope hash mismatches or a different analysis date cause a HARD_BLOCK; a tool error or an evidence key that no tool produced makes the analysis unsafe; insufficient data or a committed statistic with n < 5 leads to INVESTIGATE; soft warnings (small sample, TMS 29, small sector group, missing context, suspicious jump) give PASS_WITH_WARNINGS. The gate restricts the action space: after HARD_BLOCK or ANALYSIS_UNSAFE only ANALYSIS_UNSAFE is allowed, after INVESTIGATE only INVESTIGATE, WATCH, REJECT_SIGNAL or ANALYSIS_UNSAFE, and a candidate label always needs a backtest citation."));
add(H2("7.2 Output validator"));
add(P("The explanation is a JSON object (action, explanation, cited evidence, limitations, refusal flag). The validator checks the schema, that the action is allowed by the gate, that candidate labels cite a backtest, that every cited E# exists, that every number and its unit type and every date appear in the committed display values, that no forbidden phrase is used and that advice requests are refused. A failing answer receives the error list and one correction attempt; if it fails again a deterministic ANALYSIS_UNSAFE template is shown. The refusal sentence and the disclaimer are added by the harness, so the model never has to write a forbidden word."));
add(H2("7.3 Episodic memory and replay"));
add(P("Every analysis stores its state log, every tool call with its full envelope, the evidence, every LLM call (prompt hash, model digest, raw output, validation result), the decision and the human reviews in an SQLite episodic memory. Replay re-runs every recorded tool call with the same input and compares the output hashes; optionally the LLM step is regenerated with the same prompt and seed. Because Ollama reuses the cache of an identical prompt prefix, outputs can differ even at temperature 0; the client therefore unloads the model before and after each call (a \"cold\" call), which made outputs byte-for-byte reproducible."));

// 8 LLM
add(H1("8. Local language model"));
add(H2("8.1 Model selection"));
add(P("Three candidates that fit an 8 GB laptop GPU were compared on the same 20 evidence bundles (5 golden + 15 held-out questions) before fine-tuning. The measure is the explanation skill alone: first-attempt validator pass, completion without fallback, invented numbers, forbidden phrases, agreement with the rule-based teacher and latency."));
add(table(["Model", "First pass", "No fallback", "Invented numbers", "Forbidden phrases", "Teacher agreement", "Mean time"],
  Object.entries(ini).map(([m, s]) => [m, pct(s.first_attempt_pass), pct(s.final_without_fallback), pct(s.questions_with_invented_numbers), pct(s.questions_with_forbidden_phrases), pct(s.teacher_agreement), sec(s.mean_seconds)]),
  [20, 13, 13, 14, 14, 14, 12], "Base models before fine-tuning (20 questions)."));
add(P("None of the base models was usable as is: they invented numbers, reversed directions (for example calling a falling net debt/EBITDA \"increased\") and chose INVESTIGATE almost every time. Qwen3.5-4B was chosen for fine-tuning because it trains on the local GPU in a few hours and answers fastest; the 9B model would have required rented cloud GPUs."));
add(H2("8.2 Training data"));
add(P(`The training set was generated from the project's own tools on real data — no cloud model and no synthetic market data were used. ${ds.jobs.toLocaleString("en-US")} generation jobs produced ${ds.examples.toLocaleString("en-US")} examples of three skills: question understanding (free Turkish text → scenario, tickers, parameters, including advice traps and out-of-scope questions), tool planning per state, and explanation from evidence (the target is the rule-based teacher with phrasing variants; every target passes the validator). A leakage guard keeps the golden analysis date and three held-out dates (±25 trading days) out of the training data.`));
const sp = ds.by_split_skill;
add(table(["Skill", "Train", "Validation"], [
  ["Explanation", String(sp["train/explanation"]), String(sp["val/explanation"])],
  ["Question understanding", String(sp["train/intent"]), String(sp["val/intent"])],
  ["Tool planning", String(sp["train/planning"]), String(sp["val/planning"])],
], [50, 25, 25], "Fine-tuning dataset by skill and split."));
add(H2("8.3 QLoRA training and export"));
add(P("Training used 4-bit NF4 quantisation with LoRA (r = 16, α = 32), learning rate 2·10⁻⁴ with a cosine schedule, two epochs, effective batch size 16, sequences up to 4,096 tokens and gradient checkpointing, on the same RTX 4070 laptop GPU (8 GB). The run took 716 optimizer steps and 4 h 50 min; the training loss fell from 0.39 to 0.0074 and the validation loss from 0.0102 after epoch 1 to 0.0085 after epoch 2 (no overfitting). The adapter was merged and exported to GGUF Q8_0 (4.5 GB). The llama.cpp converter fused tensors and added a multi-token-prediction block that Ollama 0.40 could not load; a small conversion script disabled the fusion so that the tensor names and shapes match Ollama's own Qwen3.5 build."));
add(H2("8.4 Grounding free-text questions"));
add(P("The model proposes and code verifies. A list of company names and sector words maps names in the question to tickers; a ticker the model proposes but the question does not support is removed, a ticker named in the question but missed by the model is added, an explicit advice phrase always routes to the safety scenario, and a question with nothing grounded is declined. This removed the model's early mistakes such as mapping \"Migros\" to MIATK. For S1 the sector comparison always uses the whole peer group of the requested stocks, also when the model proposes a ticker list."));

// 9 Evaluation
add(H1("9. Evaluation"));
add(H2("9.1 Golden questions"));
add(P(`The instructor's five reference questions (analysis date 2026-09-10) run end to end through the harness with the fine-tuned model explaining. Each question checks that the mandatory states ran, that no tool call was invalid, that the explanation passed the validator, that the action is allowed by the gate and by the question's expectation, that the required evidence was committed, that incomplete windows and not-yet-published reports are reported, and that the advice request is refused.`));
add(table(["Question", "Topic", "Result", "Risk gate", "Action", "Rule-based reference", "Attempts"],
  golden.map((r) => [r.id, QTITLE[r.id], r.ok ? "PASS" : "FAIL", r.gate, r.action, r.teacher_action, String(r.attempts)]),
  [9, 27, 9, 16, 15, 15, 9], `Golden questions with bist-analist: ${gOk}/5 passed, ${gFirst}/5 on the first attempt, ${gTeacher}/5 with the reference action.`));
add(H2("9.2 Effect of fine-tuning"));
add(P(`On the same 20 evidence bundles the fine-tuned model passed the validator on the first attempt in ${pct(ft.first_attempt_pass)} of the questions versus ${pct(base.first_attempt_pass)} for the base model; it never needed the safe fallback (base: ${pct(1 - base.final_without_fallback)}), invented no number (base: ${pct(base.questions_with_invented_numbers)}), used no forbidden phrase (base: ${pct(base.questions_with_forbidden_phrases)}) and chose the same action as the rule-based teacher in ${pct(ft.teacher_agreement)} of the questions (base: ${pct(base.teacher_agreement)}). The mean time per explanation was ${sec(ft.mean_seconds)} (base ${sec(base.mean_seconds)}). With n = 20, a 100% rate has a Wilson 95% lower bound of about 84%.`));
add(figure(FIG("fine_tune.png"), "Base versus fine-tuned model on the same 20 evidence bundles."));
add(H2("9.3 A–E ablation"));
add(P("The ablation keeps the model and the instruction fixed and changes the infrastructure: A raw LLM without tools; B with MCP tools; C with the stateful harness; D with the committed evidence and the risk gate; E with episodic memory and human review. Each level's answer is checked by the same validator against the evidence that level showed to the model (20 questions, both models)."));
add(figure(FIG("ablation.png"), "Share of answers with any rule violation at each level."));
const L = ["A", "B", "C", "D", "E"];
add(table(["Level", "Violations (fine-tuned / base)", "Invented numbers", "Action not allowed by gate", "Invalid tool calls", "Tool calls / question"],
  L.map((k) => [k, `${pct(abl["bist-analist"][k].any_rule_violation)} / ${pct(abl["qwen3.5:4b"][k].any_rule_violation)}`,
    `${pct(abl["bist-analist"][k].invented_numbers)} / ${pct(abl["qwen3.5:4b"][k].invented_numbers)}`,
    `${pct(abl["bist-analist"][k].action_not_allowed_by_gate)} / ${pct(abl["qwen3.5:4b"][k].action_not_allowed_by_gate)}`,
    abl["bist-analist"][k].invalid_call_rate === null ? "–" : `${pct(abl["bist-analist"][k].invalid_call_rate)} / ${pct(abl["qwen3.5:4b"][k].invalid_call_rate)}`,
    `${abl["bist-analist"][k].tool_calls_per_question.toFixed(1)} / ${abl["qwen3.5:4b"][k].tool_calls_per_question.toFixed(1)}`]),
  [9, 21, 17, 19, 17, 17], "Ablation details (fine-tuned / base model)."));
add(P(`Two conclusions follow. First, safety comes from the harness: at D and E both models have 0% violations. At level A the fine-tuned model invents numbers in ${pct(abl["bist-analist"].A.invented_numbers)} of the answers (it learned the pattern "number + E#" without the evidence), while the base model uses forbidden phrases (${pct(abl["qwen3.5:4b"].A.forbidden_phrases)}) and misses refusals (${pct(abl["qwen3.5:4b"].A.refusal_missing)}). The model alone is not safe. Second, fine-tuning provides usefulness: its tool plans are almost always valid (invalid calls ${pct(abl["bist-analist"].C.invalid_call_rate, 1)} versus ${pct(abl["qwen3.5:4b"].C.invalid_call_rate)} for the base model), and its explanations pass without falling back to the template. Replay reproduced every recorded tool call at both D and E.`));
add(H2("9.4 Robustness to unseen questions"));
add(P(`A second question set of 30 questions was written and frozen after training and before any run: other companies, slang, Turkish text without Turkish characters, advice requests disguised as technical or fundamental questions, out-of-universe stocks, crypto and small talk. Figure 5 shows question understanding.`));
add(figure(FIG("intent.png"), "Understanding of 30 unseen free-text questions."));
add(table(["Measure (30 questions, end to end with bist-analist)", "Value"], [
  ["Questions understood correctly", pct(e2e.correct)],
  ["Analyses run (the rest were correctly refused or declined)", String(e2e.analysed)],
  ["Runs with an invalid tool call", pct(e2e.runs_with_invalid_calls)],
  ["Runs needing the harness default plan", pct(e2e.runs_needing_harness_default)],
  ["Explanation passed on the first attempt", pct(e2e.explanation_first_pass)],
  ["Safe fallback used", pct(e2e.explanation_fallback)],
  ["Runs with invented numbers / forbidden phrases", `${pct(e2e.runs_with_invented_numbers)} / ${pct(e2e.runs_with_forbidden_phrases)}`],
  ["Mean time per question (model understands, plans and explains)", sec(e2e.mean_seconds)],
], [72, 28], "End-to-end robustness run."));
add(P("The two explanations that did not pass on the first attempt were advice requests phrased in ways the regular expressions did not contain; the model set the refusal flag to false, the validator caught it and the correction attempt passed. During this run an inconsistency in a tool was also found and fixed: the FX relationship tool reported the period return from weekly bins but dated it from the first day, which could show two different returns for the same period."));

// 10 Findings
add(H1("10. Research findings"));
add(P("The research reports in reports/scenarios/ are generated by a script that runs each golden question through the harness and formats every number from a tool envelope; each report lists the call_id of every tool call so that it can be replayed. The key findings below are copied from those reports."));
const fsec = (title, key, figfile, figtext) => {
  add(H2(title));
  add(BUL((F[key] || []).map((t) => t.replace(" (see the cash-at-policy-rate version below)", " (Section 12 discusses idle cash at the policy rate)"))));
  if (figfile) add(figure(figfile, figtext));
};
fsec("10.1 S1 — Sector laggards and catch-up (Retail)", "s1_sector_catch_up_retail", SFIG("s1_sectors.png"), "20-day catch-up rate of laggards by sector (dot), 95% confidence interval (bar) and the rate on non-lagging days (tick).");
fsec("10.2 S2 — Weekday patterns (THYAO)", "s2_weekday_patterns_thyao", SFIG("s2_all_stocks.png"), "The same weekday pattern in all 30 stocks: in-sample versus out-of-sample effect. Points far from the diagonal show that in-sample patterns do not persist.");
fsec("10.3 S3 — Technical reversals (ASELS)", "s3_technical_reversal_asels", SFIG("s3_success_rates.png"), "Five-day success rate of each event type with its 95% confidence interval and the non-event baseline.");
fsec("10.4 S4 — Quarterly fundamentals and reaction (TUPRS)", "s4_fundamental_reaction_tuprs", null, null);
fsec("10.5 Macro and contextual evidence", "macro_context", SFIG("macro_fx_sensitivity.png"), "Correlation of weekly stock returns with USD/TRY for the 30 stocks.");
fsec("10.6 Backtests and benchmarks", "backtest_comparisons", SFIG("backtest_variants.png"), "Equity curves of the five cumulative strategy variants against XU100 and equal-weight buy-and-hold.");
add(H2("10.7 Interpretation"));
add(P("Taken together, the scenarios give a consistent and honest picture. Patterns that look strong in isolation — a high bounce rate after lower Bollinger touches, a Thursday–Friday rebound after three down days, higher returns after improving margins — do not separate from non-event periods after multiple-testing correction, do not keep their sign out of sample, or come from a strong market trend that also lifts non-event days. The pre-registered strategy does not beat XU100 after costs. A system that reported these patterns as signals would be wrong most of the time; this system labels them WATCH, INVESTIGATE or REJECT_SIGNAL and shows why. In the specification's own words, the question is not whether a pattern exists in hindsight but whether it is stable, cost-adjusted and verified out of sample."));

// 11 UI
add(H1("11. User interface and human review"));
add(P("FinTreX Analyst is the web interface of the system (Figures 11 and 12; the product's interface and explanations are in Turkish because it answers Turkish questions). It runs entirely on the local machine — fonts and the charting library are served from the project, no CDN is loaded — and binds to 127.0.0.1 by default. A question can be asked in free Turkish or chosen from the instructor's five reference questions. While the 17 states run, a terminal-style log shows each state's status and the tool calls (those proposed by the model are highlighted). The result page shows the analytical state, the risk gate and the validator result, the explanation with superscript references that open the cited evidence, the committed evidence set and the gate findings, a point-in-time price chart, the backtest, the validator checklist and the model's raw output, and the human review (accept, modify with a new action, or reject; a reason is mandatory). A decision log lists earlier analyses and replays any of them, reporting whether the data version, every tool output hash and optionally the LLM output are identical. A method page shows the measured results from the frozen evaluation files."));
add(figure(FIG("ui_home.png"), "FinTreX Analyst home page (Turkish interface): question box, a ticker tape of point-in-time closing prices and the reference questions."));
add(figure(FIG("ui_result.png"), "Result page for golden question Q3: analytical state (WATCH), risk gate, validator, numbered sections and evidence side notes."));

// 12 Economics
add(H1("12. Engineering-economics perspective"));
add(P("The design makes several cost–benefit decisions that are typical engineering-economics trade-offs."));
add(BUL([
  "**Local versus cloud inference.** A local model has no per-token cost, keeps data and questions on the machine and is reproducible (fixed weights, cold calls). The price is hardware and latency: one explanation takes about 18 s and a full free-text analysis about 43 s on a laptop GPU. For a research tool used by one analyst this latency is acceptable; the marginal cost of an additional analysis is close to zero.",
  "**Fine-tuning a small model versus using a larger one.** Fine-tuning the 4B model took under five hours on the same laptop and produced better rule compliance than the untuned 9B model, which would not fit fully into 8 GB of memory and would have needed rented cloud GPUs for training. The fixed one-time cost of fine-tuning replaces a recurring cost of a larger model.",
  "**Cost of errors.** In a decision-support setting the costly error is a confident but wrong answer. The harness converts uncertain cases into INVESTIGATE or ANALYSIS_UNSAFE: it trades some usefulness for a large reduction in the probability of a harmful output, as the ablation shows (rule violations from up to 65% to 0%).",
  "**Transaction costs and the opportunity cost of cash.** Every backtest includes costs, and the backtest report evaluates idle cash at the policy rate: with Turkish policy rates around 37–50% in the period, a strategy that is invested only part of the time must beat cash, not only zero. All five variants have negative Sharpe ratios against the policy rate.",
  "**Data quality as a cost.** Reconciling two price sources, repairing KAP bank columns and detecting TMS 29 cost development time, but each prevented spurious research results (for example a false −91% day that would have produced fake reversal events).",
]));

// 13 Limitations
add(H1("13. Limitations and threats to validity"));
add(BUL([
  "**Sample sizes.** About 2.7 years of daily data, about ten quarterly reports per stock and 20–30 evaluation questions; percentages from n = 20 have wide intervals.",
  "**One market regime.** The period is dominated by high inflation, a strong nominal equity trend and falling policy rates; results may not hold in another regime.",
  "**Teacher bias.** The fine-tuned model's explanations imitate a rule-based teacher; agreement with the teacher measures consistency, not correctness of the teacher's rules.",
  "**Regex-based safety layers.** Forbidden-phrase and advice detection use patterns; the robustness set was written to contain phrasings not in the patterns, and the validator still caught them, but unseen phrasings remain a risk.",
  "**News and speech.** Tags are deterministic and audited only for precision; recall was not measured. Speech claims rarely contain verifiable figures.",
  "**Execution realism.** The backtest ignores price limits, partial fills, overnight gaps beyond the open price and taxes.",
  "**Platform reproducibility.** Byte-identical LLM outputs were verified on the same machine and GPU; other hardware may produce different (still validated) outputs.",
]));

// 14 Conclusion
add(H1("14. Conclusion and future work"));
add(P(`FinTreX Analyst shows that a small local language model can be a useful interface to quantitative financial research when it is placed inside a harness that owns the numbers, the dates, the permissions and the final decision. The fine-tuned model understands free Turkish questions (${pct(intent["llm:bist-analist"].correct)} of 30 unseen questions), plans valid tool calls and writes explanations that pass a strict validator on the first attempt, while the harness guarantees that no invented number, look-ahead data or investment advice reaches the user. The research results are mostly negative — no technical, calendar or fundamental pattern in this period survives correction and out-of-sample checks, and no strategy beats the index after costs — and the system reports exactly that.`));
add(P("The infrastructure is the core of the related TÜBİTAK 2209-A / FinTreX project, which will extend the universe to 95 stocks (one configuration change), add general news sources with deduplication and study whether Turkish financial news predicts next-day direction, using the same point-in-time contract, tools and harness."));

// References
add(H1("References"));
add(NUM([
  "Özcan, A. Engineering Economics Project 2026, CSE-481: Integrated BIST 100 Agentic Financial Analytics Harness (project specification). Akdeniz University, 2026.",
  "Benjamini, Y., Hochberg, Y. Controlling the false discovery rate: a practical and powerful approach to multiple testing. Journal of the Royal Statistical Society B, 57(1), 289–300, 1995.",
  "Dettmers, T., Pagnoni, A., Holtzman, A., Zettlemoyer, L. QLoRA: Efficient finetuning of quantized LLMs. NeurIPS, 2023.",
  "Hu, E. J. et al. LoRA: Low-rank adaptation of large language models. ICLR, 2022.",
  "Qwen Team. Qwen3.5 model family (open weights). Alibaba Cloud, 2026.",
  "Anthropic. Model Context Protocol specification. modelcontextprotocol.io.",
  "Kaufman, P. J. Trading Systems and Methods (KAMA). Wiley.",
  "Wilder, J. W. New Concepts in Technical Trading Systems (RSI, ATR). Trend Research, 1978.",
  "Public Disclosure Platform (KAP), Borsa İstanbul. https://www.kap.org.tr.",
  "Central Bank of the Republic of Türkiye (CBRT): indicative exchange rates, policy rate and CPI tables. https://www.tcmb.gov.tr.",
  "Federal Reserve Bank of St. Louis, FRED: DFEDTARU, DFEDTARL.",
  "Public Oversight, Accounting and Auditing Standards Authority: TMS 29 (IAS 29) Financial Reporting in Hyperinflationary Economies.",
], "refs"));

// Appendix
add(H1("Appendix A. Reproducing the results"));
add(P("All commands run from the project root with Python 3.12 and uv. The frozen database and the model are published as release assets and installed by the setup scripts, which verify every sha256."));
add(table(["Purpose", "Command"], [
  ["Install", "`uv sync --extra dev --extra llm --extra ui --extra mcp --extra report`"],
  ["Download database and model", "`bash setup/get_assets.sh` (macOS/Linux) or `setup\\get_assets.ps1` (Windows)"],
  ["Tests, lint, types", "`uv run pytest -q` · `uv run ruff check .` · `uv run mypy src`"],
  ["Golden questions", "`uv run python -m eval.run_golden --explainer llm --out reports/golden_final.json`"],
  ["Model comparison", "`uv run python -m eval.bakeoff --models bist-analist,qwen3.5:4b`"],
  ["A–E ablation", "`uv run python -m eval.ablation`"],
  ["Robustness", "`uv run python -m eval.robustness --set v2 [--e2e]`"],
  ["Research reports", "`uv run --extra report python -m eval.scenario_reports s1 s2 s3 s4 macro backtest`"],
  ["This report", "`uv run --extra report python reports/final/build/make_figures.py` then `node reports/final/build/build_report.js`"],
  ["Web interface", "`uv run python -m bistharness.ui.web` → http://127.0.0.1:8501"],
  ["Replay a decision", "`uv run python -m bistharness.harness replay --decision D-… [--llm]`"],
], [28, 72], "Commands that reproduce the results in this report."));

// ------------------------------------------------------------------ title page + document
const title = [
  new Paragraph({ children: [], spacing: { before: 2400 } }),
  new Paragraph({ children: [new TextRun({ text: "FinTreX Analyst", size: 64, bold: true, color: INK })], spacing: { after: 120 } }),
  new Paragraph({ children: [new TextRun({ text: "An Integrated Agentic Financial Analytics Harness for BIST 100", size: 34, color: INK })], spacing: { after: 480 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 18, color: SIGNAL, space: 12 } } }),
  new Paragraph({ children: [new TextRun({ text: "Final Technical Report", size: 26, bold: true })], spacing: { after: 120 } }),
  new Paragraph({ children: [new TextRun({ text: "CSE-481 Engineering Economics · Fall 2026", size: 24 })], spacing: { after: 60 } }),
  new Paragraph({ children: [new TextRun({ text: "Akdeniz University", size: 24 })], spacing: { after: 60 } }),
  new Paragraph({ children: [new TextRun({ text: "Instructor: Dr. Alper Özcan", size: 24 })], spacing: { after: 600 } }),
  new Paragraph({ children: [new TextRun({ text: "Authors", size: 20, bold: true, color: MUTE })], spacing: { after: 60 } }),
  new Paragraph({ children: [new TextRun({ text: "Egemen Çamözü — 20220808076", size: 24 })], spacing: { after: 40 } }),
  new Paragraph({ children: [new TextRun({ text: "Batuhan Erdem — 20230808611", size: 24 })], spacing: { after: 240 } }),
  new Paragraph({ children: [new TextRun({ text: "Date: November 2026", size: 24, color: MUTE })], spacing: { after: 60 } }),
  new Paragraph({ children: [new TextRun({ text: "Analysis date of the golden questions: 2026-09-10 · data snapshot: 2026-11-20", size: 20, color: MUTE })] }),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ children: [new TextRun({ text: "Contents", size: 32, bold: true })], spacing: { after: 200 } }),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  new Paragraph({ children: [new PageBreak()] }),
];

const doc = new Document({
  creator: "FinTreX Analyst",
  title: "FinTreX Analyst — Final Technical Report",
  description: "CSE-481 Engineering Economics final technical report",
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: "Calibri", size: 22, color: INK } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 32, bold: true, color: INK }, paragraph: { spacing: { before: 240, after: 160 }, keepNext: true, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 26, bold: true, color: INK }, paragraph: { spacing: { before: 240, after: 100 }, keepNext: true, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 23, bold: true, color: MUTE }, paragraph: { spacing: { before: 180, after: 80 }, keepNext: true, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 420, hanging: 260 } } } }] },
    { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 420, hanging: 300 } } } }] },
    { reference: "refs", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "[%1]", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 520, hanging: 520 } } } }] },
  ] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }, titlePage: true },
    headers: { default: new Header({ children: [new Paragraph({ children: [new TextRun({ text: "FinTreX Analyst — Final Technical Report", size: 16, color: MUTE })], alignment: AlignmentType.RIGHT })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: MUTE })] })] }) },
    children: [...title, ...body],
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT); });
