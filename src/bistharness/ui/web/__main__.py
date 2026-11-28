"""uv run python -m bistharness.ui.web [--host 127.0.0.1] [--port 8501] [--no-browser]"""

from __future__ import annotations

import argparse
import logging
import threading
import webbrowser
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bistharness.ui.web", description="FinTreX Analyst web UI")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: this machine only)")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument("--memory", type=Path, help="episodic memory file (default data/db/episodic.sqlite)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    import uvicorn

    from bistharness.ui.web.server import create_app

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"FinTreX Analyst -> {url}  (durdurmak için Ctrl+C)")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, (url,)).start()
    uvicorn.run(create_app(memory_path=args.memory), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
