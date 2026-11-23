"""Frozen raw snapshots: every file is listed with its sha256 so later runs can prove they read the same bytes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bistharness.core.errors import SnapshotIntegrityError
from bistharness.core.hashing import file_sha256, sha256_hex

MANIFEST_NAME = "manifest.json"


def write_manifest(snapshot_dir: Path, *, source: str, params: dict[str, Any]) -> dict[str, Any]:
    files = sorted(p for p in snapshot_dir.rglob("*") if p.is_file() and p.name != MANIFEST_NAME)
    entries = {p.relative_to(snapshot_dir).as_posix(): file_sha256(p) for p in files}
    manifest: dict[str, Any] = {
        "source": source,
        "snapshot": snapshot_dir.name,
        "created_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": params,
        "files": entries,
    }
    # content hash covers files + params, not the creation time
    manifest["content_sha256"] = sha256_hex({"source": source, "params": params, "files": entries})
    (snapshot_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def read_manifest(snapshot_dir: Path) -> dict[str, Any]:
    path = snapshot_dir / MANIFEST_NAME
    if not path.exists():
        raise SnapshotIntegrityError(f"manifest missing: {path}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def verify_manifest(snapshot_dir: Path) -> dict[str, Any]:
    """Re-hash every file; raise SnapshotIntegrityError on any difference."""
    manifest = read_manifest(snapshot_dir)
    problems: list[str] = []
    for rel, digest in manifest["files"].items():
        p = snapshot_dir / rel
        if not p.exists():
            problems.append(f"missing: {rel}")
        elif file_sha256(p) != digest:
            problems.append(f"changed: {rel}")
    extra = {
        p.relative_to(snapshot_dir).as_posix()
        for p in snapshot_dir.rglob("*")
        if p.is_file() and p.name != MANIFEST_NAME
    } - set(manifest["files"])
    problems.extend(f"unlisted: {e}" for e in sorted(extra))
    if problems:
        raise SnapshotIntegrityError(f"{snapshot_dir}: " + "; ".join(problems[:10]))
    return manifest
