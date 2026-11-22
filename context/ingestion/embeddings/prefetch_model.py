#!/usr/bin/env python3
"""Image-build step: fetch the pinned model and its remote-code repo into HF_HOME so runs can be fully offline.

The model's remote code loads its tokenizer by repo name without a revision, which resolves the `main` ref
in the offline cache. Point `main` at the pinned commit so that lookup yields exactly the pinned files
(standard pinned cache layout).
"""
import argparse
from pathlib import Path

from huggingface_hub import snapshot_download
from huggingface_hub.constants import HF_HUB_CACHE

MODEL_FILES = ["config.json", "model.safetensors", "special_tokens_map.json", "tokenizer.json",
               "tokenizer_config.json", "vocab.json"]


def pin_main(repo, revision):
    ref = Path(HF_HUB_CACHE) / ("models--" + repo.replace("/", "--")) / "refs" / "main"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text(revision)


p = argparse.ArgumentParser()
p.add_argument("--model", required=True)
p.add_argument("--model-revision", required=True)
p.add_argument("--code-repo", required=True)
p.add_argument("--code-revision", required=True)
a = p.parse_args()
print(snapshot_download(a.model, revision=a.model_revision, allow_patterns=MODEL_FILES))
print(snapshot_download(a.code_repo, revision=a.code_revision))
pin_main(a.model, a.model_revision)
pin_main(a.code_repo, a.code_revision)
