#!/usr/bin/env bash
# macOS / Linux twin of setup/get_assets.ps1: downloads the frozen database + the fine-tuned model from the private
# GitHub release, verifies every sha256, installs them (data/db/bist.sqlite, models/bist-4b-q8_0.gguf) and registers
# the Ollama model "bist-analist".
#
#   bash setup/get_assets.sh               # DB + model (~4,5 GB)
#   bash setup/get_assets.sh --skip-model  # DB only (~15 MB)
#
# Needs: gh (GitHub CLI, logged in with access to the repo); for the model: Ollama running.
set -euo pipefail
TAG="${TAG:-assets-2026-11-20}"
REPO="${REPO:-egemencamozu/bist-harness}"
SKIP_MODEL=0
[ "${1:-}" = "--skip-model" ] && SKIP_MODEL=1

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DL="$ROOT/.assets"
mkdir -p "$DL" "$ROOT/data/db" "$ROOT/models"

sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
check() {  # check <path> <name-in-SHA256SUMS>
  local expected
  expected="$(grep -E "^[0-9a-f]{64}  $2\$" "$DL/SHA256SUMS.txt" | cut -d' ' -f1)"
  [ -n "$expected" ] || { echo "no checksum for $2" >&2; exit 1; }
  [ "$(sha "$1")" = "$expected" ] || { echo "sha256 mismatch for $2 ($1)" >&2; exit 1; }
  echo "  ok  $2"
}

echo "[1/4] downloading release $TAG ..."
PATTERNS=(--pattern SHA256SUMS.txt --pattern bist.sqlite.gz)
[ "$SKIP_MODEL" = 1 ] || PATTERNS+=(--pattern 'bist-4b-q8_0.gguf.part*')
gh release download "$TAG" --repo "$REPO" --dir "$DL" --clobber "${PATTERNS[@]}"

echo "[2/4] database ..."
check "$DL/bist.sqlite.gz" bist.sqlite.gz
gunzip -c "$DL/bist.sqlite.gz" > "$ROOT/data/db/bist.sqlite"
check "$ROOT/data/db/bist.sqlite" bist.sqlite
[ "$SKIP_MODEL" = 1 ] && { echo "done (model skipped)."; exit 0; }

echo "[3/4] model (joining parts) ..."
for p in "$DL"/bist-4b-q8_0.gguf.part*; do check "$p" "$(basename "$p")"; done
cat "$DL"/bist-4b-q8_0.gguf.part0 "$DL"/bist-4b-q8_0.gguf.part1 "$DL"/bist-4b-q8_0.gguf.part2 > "$ROOT/models/bist-4b-q8_0.gguf"
check "$ROOT/models/bist-4b-q8_0.gguf" bist-4b-q8_0.gguf

echo "[4/4] ollama create bist-analist ..."
cat > "$ROOT/models/Modelfile" <<'EOF'
FROM ./bist-4b-q8_0.gguf
RENDERER qwen3.5
PARSER qwen3.5
PARAMETER temperature 0
PARAMETER seed 42
PARAMETER num_ctx 4096
EOF
(cd "$ROOT/models" && ollama create bist-analist -f Modelfile)
ollama list
echo "done. The downloaded parts in .assets/ can be deleted."
