#!/usr/bin/env python3
"""Run LingBot-Map's demo_render/batch_demo.py with the model weights in bfloat16.

On a 16 GB GPU shared with a desktop session, batch_demo's float32 weights leave
LingBot about 0.5 GB short. The transformer backbone already runs under bfloat16
autocast, so its weights are kept in bfloat16 (the float32 output heads are untouched).
batch_demo itself, its arguments and its NPZ output are unchanged.

Usage (runs with LingBot's own Python environment):
    python adapters/lingbot_lowmem.py --lingbot-repo /path/to/lingbot-map  <batch_demo arguments...>
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

CHUNK = int(os.environ.get("LINGBOT_DEPTH_CHUNK", "2"))


def main() -> None:
    argv = sys.argv[1:]
    if "--lingbot-repo" not in argv:
        raise SystemExit("--lingbot-repo is required")
    i = argv.index("--lingbot-repo")
    repo = Path(argv[i + 1])
    rest = argv[:i] + argv[i + 2:]
    demo_dir = repo / "demo_render"
    sys.path[:0] = [str(demo_dir), str(repo)]

    import torch

    import batch_demo  # noqa: E402  (LingBot-Map's own script, imported unchanged)

    original = batch_demo.load_model

    def load_model_bf16(args, device):
        model = original(args, device)
        # only the transformer backbone: LingBot runs its camera/depth heads in float32 with
        # autocast switched off (gct_base.py), so those must keep float32 weights
        model.aggregator.to(torch.bfloat16)
        # the float32 DPT depth head upsamples 8 frames at a time by default; 2 at a time gives
        # the same output with a quarter of that peak memory
        head = getattr(model, "depth_head", None)
        if head is not None:
            fwd = head.forward

            def forward_small_chunks(*a, **k):
                k.setdefault("frames_chunk_size", CHUNK)
                return fwd(*a, **k)

            head.forward = forward_small_chunks
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            used = torch.cuda.memory_allocated() / 2**30
            print(f"[civil-scan] backbone weights cast to bfloat16 ({used:.2f} GiB allocated)", flush=True)
        return model

    batch_demo.load_model = load_model_bf16

    run_original = batch_demo.run_inference

    def run_inference_logged(model, images, args):
        # batch_demo catches every error and prints only its message; print where it happened
        try:
            return run_original(model, images, args)
        except Exception:
            import traceback

            traceback.print_exc()
            if torch.cuda.is_available():
                print(f"[civil-scan] peak GPU memory {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB", flush=True)
            raise

    batch_demo.run_inference = run_inference_logged
    sys.argv = [str(demo_dir / "batch_demo.py"), *rest]
    batch_demo.main()


if __name__ == "__main__":
    main()
