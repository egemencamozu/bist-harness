#!/bin/sh
# One-off: registers models/bist-4b-q8_0.gguf as the Ollama model "bist-analist" (skipped if it already exists).
set -e
if [ ! -f /models/bist-4b-q8_0.gguf ]; then
  echo "models/bist-4b-q8_0.gguf bulunamadi (README.md: Model dosyasi)." >&2
  exit 1
fi
if ollama list | grep -q '^bist-analist'; then
  echo "bist-analist zaten kayitli."
else
  ollama create bist-analist -f /docker/Modelfile
fi
ollama list
