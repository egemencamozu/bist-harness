"""Ingest CLI (the only place where internet access is allowed).

uv run python -m bistharness.data.ingest prices --snapshot 2026-11-20 [--no-download]
uv run python -m bistharness.data.ingest fundamentals --snapshot 2026-11-20
uv run python -m bistharness.data.ingest macro --snapshot 2026-11-20 [--no-download]
uv run python -m bistharness.data.ingest news --snapshot 2026-11-20
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from bistharness.core.config import load_settings, load_universe


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bistharness.data.ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prices", help="freeze price snapshots and rebuild the price tables")
    p.add_argument("--snapshot", required=True, help="snapshot name = first day NOT included (YYYY-MM-DD)")
    p.add_argument("--no-download", action="store_true", help="fail instead of downloading a missing snapshot")
    f = sub.add_parser("fundamentals", help="freeze the KAP financial reports and rebuild the fundamentals tables")
    f.add_argument("--snapshot", required=True, help="snapshot name = first day NOT included (YYYY-MM-DD)")
    m = sub.add_parser("macro", help="freeze TCMB/FRED macro sources and rebuild macro_observations")
    m.add_argument("--snapshot", required=True, help="snapshot name = first day NOT included (YYYY-MM-DD)")
    m.add_argument("--no-download", action="store_true", help="fail instead of downloading a missing snapshot")
    n = sub.add_parser("news", help="freeze the Bloomberg HT archive and rebuild news_events (metadata only)")
    n.add_argument("--snapshot", required=True, help="snapshot name = first day NOT included (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.cmd == "prices":
        from bistharness.data.ingest import prices

        s = prices.run(load_settings(), load_universe(), args.snapshot, allow_download=not args.no_download)
        print(f"ingest_id     : {s.ingest_id}")
        print(f"tickers       : {s.tickers}")
        print(f"price rows    : {s.price_rows}  by source: {s.per_source}")
        print(f"calendar days : {s.calendar_days}")
        print(f"corp. actions : {s.actions}")
        print(f"flags         : {dict(sorted(s.flags.items()))}")
    elif args.cmd == "fundamentals":
        import pandas as pd

        from bistharness.data.ingest import fundamentals

        r = fundamentals.run(load_settings(), load_universe(), args.snapshot)
        print(f"ingest_id     : {r.ingest_id}")
        print(f"reports       : {r.reports}  tickers: {r.tickers}  rows: {r.rows}")
        print(f"coverage end  : {r.coverage_end}  (last KAP publish time in the snapshot)")
        print(f"no reports for: {r.missing_tickers}")
        print(f"issues        : {dict(sorted(r.issues.items()))}")
        with pd.option_context("display.max_rows", 500, "display.width", 200):
            print()
            print("metric coverage (share of reports with a current-period value):")
            print(r.metric_coverage.to_string(index=False))
            print()
            print("TMS 29 detected (latest report) vs config tms29_applies:")
            print(r.tms29[r.tms29["mismatch"]].to_string(index=False) or "  no mismatches")
    elif args.cmd == "macro":
        from bistharness.data.ingest import macro

        mr = macro.run(load_settings(), args.snapshot, allow_download=not args.no_download)
        print(f"ingest_id     : {mr.ingest_id}")
        print(mr.per_series.to_string(index=False))
    elif args.cmd == "news":
        from bistharness.data.ingest import news

        nr = news.run(load_settings(), args.snapshot)
        print(f"ingest_id     : {nr.ingest_id}")
        print(f"articles      : {nr.articles}  with tickers: {nr.with_tickers}  {nr.first} -> {nr.last}")
        print(f"per ticker    : {nr.per_ticker}")
        print(f"event types   : {nr.per_event_type}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
