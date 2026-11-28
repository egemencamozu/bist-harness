# Data dictionary — `data/db/bist.sqlite` (snapshot 2026-11-20)

Every temporal table carries a single **knowledge-time** column. All reads go through `core/pit.py::PITRepository`
with the filter `<knowledge column> <= as_of` (as_of = after that day's close, `YYYY-MM-DD 23:59:59`) and the result
is checked again on return (`LookAheadError`). Times are Europe/Istanbul local time. Snapshot `D` contains only data
completed or published before `D`. Raw sources are frozen under `data/raw/<source>/<D>/` with a sha256 manifest.

| Table | Knowledge time | Source | Rows | Ingest command |
|---|---|---|---|---|
| `prices_daily` | `date` (close) | FinTreX price-scraper (primary) + yfinance (supplementary) | 96,213 | `ingest prices` |
| `corporate_actions` | `ex_date` | price-scraper `adj_factor` (bonus issues / splits) + yfinance (dividends) | 312 | `ingest prices` |
| `price_quality_flags` | `date` (NULL = undated) | price reconciliation + quality checks | 1,071 | `ingest prices` |
| `trading_calendar` | `date` | price-scraper majority calendar + XU100 | 992 | `ingest prices` |
| `fundamentals` | `disclosure_datetime` | KAP XBRL "Financial Report" filings (kapdata dump) | 119,969 | `ingest fundamentals` |
| `fundamental_issues` | `disclosure_datetime` | fundamentals ingest warnings | 16 | `ingest fundamentals` |
| `macro_observations` | `release_datetime` | CBRT (FX, policy rate, CPI table), FRED | 2,624 | `ingest macro` |
| `news_events` | `published_at` (conservative) | Bloomberg HT archive (metadata only) | 40,780 | `ingest news` |
| `speech_segments` | `published_at` | speech/video layer (`feature/speech-layer`) | 0 in the release DB | `ingest speech` |
| `speech_claims` | `published_at` | human-approved speech claims (speech layer) | created by `ingest speech --include-reviews` | `ingest speech` |
| `instruments`, `universe_membership` | — (static) | `config/universe.yaml` | 97 / 126 | `ingest prices` |
| `ingest_log`, `meta` | — | identity of every ingest, `data_version`, coverage ends | — | all |

## prices_daily

| Column | Description |
|---|---|
| `ticker`, `date` | key; verified BIST trading days only |
| `open`, `high`, `low`, `close` | prices **as printed** that day (raw), TRY |
| `volume` | shares traded as printed (price-scraper; otherwise yfinance, turnover-preserving) |
| `cum_factor` | cumulative adjustment factor (split / bonus issue × dividend); last day = 1 |
| `price_source` | `price_scraper` / `yfinance` / `price_scraper_raw` (which source set the day's level) |
| `factor_source` | source of the factor |

Read path (`PITRepository.prices`): `adj_t = raw_t · cum_factor_t / cum_factor_asof` — **anchored to as_of**, so
corporate actions after as_of change no output; returns include dividends (the instructor's `auto_adjust=True`
definition). Volume is scaled so that turnover is preserved. The raw columns are also returned as `raw_*`.

## fundamentals (report-centred long format)

| Column | Description |
|---|---|
| `fiscal_period` | fiscal quarter of the value (company fiscal calendar; MAVI's fiscal year ends in January) |
| `period_start`, `period_end`, `duration` | flows: `3M` quarter / `6M`, `9M`, `12M` cumulative from the start of the year (as on KAP); balance sheet: `instant` |
| `report_period`, `disclosure_index` | the report that published the value and its KAP disclosure number (`kap.org.tr/tr/Bildirim/<no>`) |
| `role` | `current` = value in its own report; `prior` = comparative column of a later report |
| `scope` | `consolidated` / `solo` |
| `statement`, `metric` | `balance` / `income` / `cashflow`; canonical metric name (`config/fundamentals.yaml`) |
| `value`, `unit` | value normalised to TRY (expense items negative) |
| `tms29_adjusted` | whether the report is restated under hyperinflation accounting (TMS 29 / IAS 29; detected from the data) |
| `source_ref` | `kap:<disclosure>#<XBRL item(s)>` — evidence traceability |

The PIT default is `role="current"`: every value as first published (plus that report's KAP corrections, kept as
separate versions). Comparatives restated under TMS 29 are visible with `role=None`. Ratios (P/E, P/B, margins, net
debt) are not stored here; the analytics layer computes them from the as_of price and the statements known at as_of.

Statement formats and metrics (`config/fundamentals.yaml`):
- `tfrs` (industrials / holdings / REITs / brokers): revenue, cost_of_sales, gross_profit, marketing/admin/rnd_expense,
  other_operating_income/expense, operating_profit, finance_income/costs, net_monetary_position, profit_before_tax,
  tax_expense, net_income, net_income_parent, depreciation_amortization, operating_cash_flow, capex, dividends_paid,
  total_assets, current/noncurrent_assets, cash, trade_receivables, inventories, current/noncurrent_liabilities,
  total_liabilities, total_equity, equity_parent, issued_capital, financial_debt.
- `bank` (BRSA): interest_income/expense, net_interest_income, net_fee_commission_income, trading_income,
  gross_operating_profit, expected_credit_losses, personnel_expense, other_operating_expense, operating_profit,
  net_income(_parent), total_assets, cash, loans, deposits, total_equity, issued_capital.
- `insurance` (IPSRA): gross_written_premiums, technical_balance, investment_income, profit_before_tax,
  net_income(_parent), operating_cash_flow, total_assets, current_assets/liabilities, cash, total_equity, issued_capital.

Known gaps: no KAP data for TRALT; YKBNK `issued_capital` fails the bank column repair (16 warnings); coverage end
`meta.fundamentals_coverage_end` = 2026-10-02 19:56:09 (no 2026 Q3 reports).

## macro_observations

| `series_code` | Unit | Source | `release_datetime` rule |
|---|---|---|---|
| `USDTRY`, `EURTRY` | TRY | CBRT indicative FX buying rate (daily XML) | bulletin day 15:30 |
| `TCMB_POLICY_RATE` | % | CBRT one-week repo table (dated by effective day) | effective day 00:00 (at most 1 day conservative) |
| `FED_TARGET_UPPER`, `FED_TARGET_LOWER` | % | FRED DFEDTARU / DFEDTARL (change points only) | effective day 00:00 |
| `TUFE_YOY`, `TUFE_MOM` | % | TurkStat CPI (CBRT table), `obs_date` = first day of the month | 3rd of the following month or the next trading day, 10:00 |

Level series (policy rate, Fed) are step functions: the value at time t = the last observation with
`release_datetime <= t`.

## news_events (metadata only, no article text)

| Column | Description |
|---|---|
| `published_at` | **knowledge time** = max(first publication, last edit): the archived text may have been edited later |
| `first_published_at` | first publication time (display only) |
| `title`, `url`, `source` | headline and source link (`bloomberght`) |
| `tickers` | JSON list; an alias in the headline, or the code or at least two alias mentions in the body (`config/news.yaml`); market-summary pages count headline matches only |
| `topics`, `event_type` | deterministic topic tags; `event_type` = the first topic in priority order (earnings > dividend > …) |

News is contextual evidence only: it never replaces numerical data, and numbers inside it cannot enter the committed
evidence without verification by deterministic tools. Articles with at least one stock tag: 1,641 (96 stocks; tagging
precision in `reports/news_tagging_audit.md`). Summary pages listing many codes keep headline matches only. Topic tags
are keyword-based (coarse).

## speech_segments and speech_claims (speech layer)

`speech_segments` holds 60-second transcript segments of a fixed list of public finance videos
(`data/manual/videos.csv`): `source_id`, `segment_start`, `segment_end`, `published_at` (video publication time; for live
streams the end of the broadcast), `url`, `speaker`, `channel`, `text`, `topics`, `stance`, `quality` (1 − word error rate
of the captions against an official text) and `ingest_id`. Transcripts are pasted from YouTube's own transcript panel
and are not committed to git, so the table is empty in the released database. `speech_claims` holds claims extracted
by the local model and approved by a human, dated by the video's publication time; it is created by
`ingest speech --include-reviews`.
