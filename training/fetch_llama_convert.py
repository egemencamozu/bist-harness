"""Fetch only what llama.cpp's HF -> GGUF converter needs (~4 MB instead of the ~40 MB source archive).

  python training/fetch_llama_convert.py --tag b12648 --dest .tools/llama.cpp-b12648/src

Files: convert_hf_to_gguf.py + conversion/** + gguf-py/gguf/** at the pinned tag (raw.githubusercontent.com; listing via the GitHub
contents API). The converter puts its sibling gguf-py/ on sys.path itself, so nothing is pip-installed. Setup tool
only (training environment); never imported by the harness.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

REPO = "ggml-org/llama.cpp"


def get(url: str, tries: int = 6) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bist-training-setup"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return bytes(r.read())
        except Exception as e:  # network hiccups: retry with backoff
            if i == tries - 1:
                raise
            print(f"  retry {i + 1} ({e})", flush=True)
            time.sleep(3 * (i + 1))
    raise RuntimeError("unreachable")


def listing(path: str, tag: str) -> list[dict[str, str]]:
    return list(json.loads(get(f"https://api.github.com/repos/{REPO}/contents/{path}?ref={tag}")))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True)
    p.add_argument("--dest", required=True)
    a = p.parse_args(argv)
    dest = Path(a.dest)
    files = ["convert_hf_to_gguf.py"]
    todo = ["gguf-py/gguf", "conversion"]  # recent tags split the converter into the conversion/ package
    while todo:
        d = todo.pop()
        for item in listing(d, a.tag):
            if item["type"] == "dir":
                todo.append(item["path"])
            elif item["type"] == "file":
                files.append(item["path"])
    for i, f in enumerate(sorted(files), 1):
        out = dest / f
        if out.exists() and out.stat().st_size > 0:
            continue
        data = get(f"https://raw.githubusercontent.com/{REPO}/{a.tag}/{f}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        print(f"  [{i}/{len(files)}] {f} ({len(data) // 1024} KB)", flush=True)
    print(f"fetched {len(files)} files -> {dest}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
