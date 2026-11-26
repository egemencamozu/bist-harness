"""Show live local Speech Layer progress without running or restarting any job."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OLLAMA_ARCHIVE = "ollama-windows-amd64.zip"
# Published byte sizes for the releases pinned by setup/resume_assets.ps1.
DOWNLOADS = (
    ("Ollama 0.40.17", "ollama.runtime", ((OLLAMA_ARCHIVE, 1_618_522_644),)),
    (
        "bist-analist GGUF",
        "install.bist-4b-q8_0.gguf",
        (
            ("bist-4b-q8_0.gguf.part0", 1_572_864_000),
            ("bist-4b-q8_0.gguf.part1", 1_572_864_000),
            ("bist-4b-q8_0.gguf.part2", 1_336_675_040),
        ),
    ),
)


def read_stages(root: Path) -> dict[str, list[tuple[bool, str]]]:
    stages: dict[str, list[tuple[bool, str]]] = {}
    for line in (root / "TASKS.md").read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("## "):
            tasks: list[tuple[bool, str]] = []
            stages[line[3:]] = tasks
        elif stages and line.startswith(("- [x] ", "- [ ] ")):
            stages[next(reversed(stages))].append((line[3] == "x", line[6:]))
    if not stages or not all(stages.values()):
        raise ValueError("TASKS.md içindeki aşama veya görev listesi eksik.")
    return stages


def received_bytes(cache: Path, name: str, expected: int) -> int:
    candidates = [*cache.glob(f"*/{name}"), *cache.glob(f"*/{name}.partial")]
    if name == OLLAMA_ARCHIVE:
        candidates.append(cache / "ollama-0.40.17-windows-amd64.zip.partial")
    sizes = [0]
    for path in candidates:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue  # Promotion can rename a file between listing and stat.
        if size <= expected:
            sizes.append(size)
    return max(sizes)


def render(root: Path, previous: dict[str, tuple[float, int]]) -> str:
    stages = read_stages(root)
    entries = json.loads((root / "CHECKPOINT.json").read_text(encoding="utf-8-sig"))["entries"]
    current = next((name for name, tasks in stages.items() if not all(done for done, _ in tasks)), None)
    all_tasks = [task for tasks in stages.values() for task in tasks]
    remaining = sum(not done for done, _ in all_tasks)
    local_time = datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M:%S")
    lines = [
        f"BIST Harness / Speech Layer     {local_time} (İstanbul)",
        "",
        f"Şu an: {current or 'Tüm aşamalar tamamlandı'}",
        f"Görevler: {len(all_tasks) - remaining}/{len(all_tasks)} tamamlandı, {remaining} kaldı",
        "",
    ]
    for name, tasks in stages.items():
        finished = sum(done for done, _ in tasks)
        status = "Tamamlandı" if finished == len(tasks) else "Şu an" if name == current else "Bekliyor"
        lines.append(f"{name}  [{status} · {finished}/{len(tasks)}]")
        if name == current:
            lines.extend(f"  - {task}" for done, task in tasks if not done)

    extraction = root / ".assets" / "speech-extraction.json"
    if extraction.is_file():
        speech = json.loads(extraction.read_text(encoding="utf-8"))
        lines.extend(
            (
                "",
                f"İddia çıkarımı · {speech['done']}/{speech['total']} segment · {speech['claims']} inceleme adayı",
                f"  Son kayıt: {speech['source']} · yeniden denenebilir: {speech['failed']}",
            )
        )

    lines.extend(("", "İndirmeler"))
    now = time.monotonic()
    for label, operation, files in DOWNLOADS:
        state = entries.get(operation, {}).get("status", "pending")
        if state == "pending":
            file_states = {entries.get(f"download.{name}", {}).get("status") for name, _ in files}
            if "in_progress" in file_states:
                state = "in_progress"
            elif "failed" in file_states:
                state = "failed"
        total = sum(size for _, size in files)
        received = sum(received_bytes(root / ".assets", name, size) for name, size in files)
        last_sample = previous.get(operation)
        previous[operation] = (now, received)
        if state == "completed":
            lines.append(f"  {label}: SHA-256 doğrulandı ve kuruldu")
            continue
        detail = {
            "pending": "Kurulum bekliyor",
            "failed": "İşlem hata kaydetti",
            "in_progress": "Doğrulama bekliyor" if received == total else "İndirme kaydı açık",
        }.get(state, state)
        if 0 < received < total and last_sample:
            before, count = last_sample
            elapsed = now - before
            if elapsed > 0 and received > count:
                minutes = max(1, round((total - received) * elapsed / (received - count) / 60))
                hours, minutes = divmod(minutes, 60)
                estimate = f"{hours} sa {minutes} dk" if hours else f"{minutes} dk"
                detail = f"Hız bu düzeyde kalırsa yaklaşık {estimate}"
            elif received == count:
                detail += " · Son ölçümde bayt artışı yok"
        lines.append(f"  {label}: {received / total:.1%} · {(total - received) / 2**20:,.0f} MiB kaldı · {detail}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Show one snapshot and exit")
    args = parser.parse_args()
    previous: dict[str, tuple[float, int]] = {}
    try:
        while True:
            try:
                output = render(ROOT, previous)
            except (OSError, ValueError, KeyError) as exc:
                if args.once:
                    parser.exit(1, f"Durum okunamadı: {exc}\n")
                output = f"Durum okunamadı: {exc}"
            if args.once:
                print(output)
                return 0
            if os.name == "nt":
                os.system("cls")
            else:
                print("\033[2J\033[H", end="")
            print(output, "\n\n10 saniyede bir yenilenir. Çıkış için Ctrl+C.", flush=True)
            time.sleep(10)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
