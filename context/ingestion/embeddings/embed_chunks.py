#!/usr/bin/env python3
"""Embed texts with a pinned local model. Input and output are JSON Lines files.

Input line:  {"id": "...", "text": "..."}   (text must already be cut to --max-chars)
Output line: {"id": "...", "embedding": [..]} written and flushed one at a time, so an
interrupted run leaves a valid prefix. A small --meta JSON file is written at the end.
No network call is made except the Hugging Face download of the pinned revisions.
"""
import argparse
import json
import os
import resource
import sys
import time


def rss_mb():
    with open('/proc/self/statm') as f:
        return int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE') / 1048576


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--model-revision", required=True)
    p.add_argument("--code-revision", required=True)
    p.add_argument("--dimension", type=int, required=True)
    p.add_argument("--max-chars", type=int, required=True)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--threads", type=int, default=2)
    a = p.parse_args()

    items = []
    with open(a.src, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if not isinstance(row.get("id"), str) or not isinstance(row.get("text"), str):
                raise SystemExit("bad input line")
            if len(row["text"]) > a.max_chars:
                raise SystemExit("input text exceeds --max-chars")
            items.append(row)

    import torch
    import transformers
    from transformers import AutoModel

    torch.set_num_threads(a.threads)
    t0 = time.perf_counter()
    # trust_remote_code executes Python fetched from the pinned code revision; the pin is what makes that reviewable.
    model = AutoModel.from_pretrained(a.model, trust_remote_code=True, revision=a.model_revision,
                                      code_revision=a.code_revision)
    load_seconds = time.perf_counter() - t0
    print(f"model loaded in {load_seconds:.1f}s; {len(items)} texts", file=sys.stderr, flush=True)

    t1 = time.perf_counter()
    with open(a.out, "w", encoding="utf-8") as out:
        for i, row in enumerate(items, 1):
            tokens = len(model.tokenizer(row["text"])["input_ids"])
            # Attention memory grows with the square of the token count; over-limit text is cut by the model and flagged.
            vec = [float(x) for x in model.encode([row["text"]], batch_size=1, max_length=a.max_tokens)[0]]
            if len(vec) != a.dimension:
                raise SystemExit(f"model returned dimension {len(vec)}, expected {a.dimension}")
            out.write(json.dumps({"id": row["id"], "embedding": vec, "tokens": tokens, "tokenTruncated": tokens > a.max_tokens}, allow_nan=False) + "\n")
            out.flush()
            if i % 25 == 0 or i == len(items):
                print(f"embedded {i}/{len(items)} ({time.perf_counter() - t1:.0f}s) rss={rss_mb():.0f}MB", file=sys.stderr, flush=True)
    meta = {"model": a.model, "modelRevision": a.model_revision, "codeRevision": a.code_revision,
            "dimension": a.dimension, "count": len(items), "loadSeconds": round(load_seconds, 2),
            "embedSeconds": round(time.perf_counter() - t1, 2), "torch": torch.__version__,
            "transformers": transformers.__version__,
            "peakRssMb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}
    with open(a.meta, "w", encoding="utf-8") as f:
        json.dump(meta, f)


if __name__ == "__main__":
    main()
