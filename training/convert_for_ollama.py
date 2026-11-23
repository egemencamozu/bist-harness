"""Run llama.cpp's HF -> GGUF converter with the qwen35 tensor layout that Ollama's bundled llama.cpp can load.

  python training/convert_for_ollama.py <llama.cpp src dir> merged --no-mtp --outtype q8_0 --outfile x.gguf

Newer converters (b12648) fuse attn_qkv+attn_gate -> attn_qkv_gate and ssm_beta+ssm_alpha -> ssm_beta_alpha and
append the MTP (nextn) block; Ollama 0.40's runner expects the separate tensors (its own qwen3.5:4b GGUF has them)
and fails with "tensor 'blk.0.ssm_beta.weight' not found". The fused tensor is a plain row concatenation [a | b], so
disabling the merge table writes the original tensors unchanged. Setup tool only; never imported by the harness.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    src = Path(sys.argv[1]).resolve()
    script = src / "convert_hf_to_gguf.py"
    sys.path.insert(0, str(src))
    sys.path.insert(1, str(src / "gguf-py"))
    from conversion import qwen  # type: ignore[import-not-found]

    qwen.Qwen3_5TextModel._SHARED_INPUT_MERGES = ()
    sys.argv = [str(script), *sys.argv[2:]]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
