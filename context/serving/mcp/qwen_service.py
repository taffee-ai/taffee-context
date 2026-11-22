#!/usr/bin/env python3
"""
qwen_service.py: Milestone 8 Qwen-2.5-Coder-0.5B HTTP Sidecar Service.

Provides a lightweight, zero-dependency HTTP service wrapping
Qwen2.5-Coder-0.5B-Instruct running as an external container.

Endpoints:
  GET  /health  -> Health status, loaded model name and revision
  POST /distill -> Generates deterministic greedy summary of context snippets
"""

import os
import sys
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("qwen_service")

# Global model state
_tokenizer = None
_model = None
_model_revision = "ea3f2471cf"
MODEL_ID = "Qwen/Qwen2.5-Coder-0.5B-Instruct"


def load_model():
    """Load Qwen model and tokenizer offline from local HF cache."""
    global _tokenizer, _model, _model_revision
    if _model is not None:
        return

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "2")))
    hf_home = os.environ.get("HF_HOME", "/hf")
    logger.info("Loading Qwen model from HF_HOME=%s...", hf_home)

    # Detect local snapshot if available
    snapshot_dir = os.path.join(hf_home, "hub", "models--Qwen--Qwen2.5-Coder-0.5B-Instruct", "snapshots")
    model_path = MODEL_ID
    if os.path.isdir(snapshot_dir):
        subdirs = [d for d in os.listdir(snapshot_dir) if not d.startswith(".")]
        if subdirs:
            _model_revision = subdirs[0]
            model_path = os.path.join(snapshot_dir, _model_revision)
            logger.info("Found local offline snapshot: %s", model_path)

    _tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    _model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.float32,
        local_files_only=True
    )
    _model.eval()
    logger.info("Qwen2.5-Coder-0.5B-Instruct loaded successfully (revision=%s)", _model_revision[:10])


class QwenRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for Qwen Sidecar."""

    def do_GET(self):
        if self.path in ("/health", "/healthz"):
            self._send_json(200, {
                "status": "ready" if _model is not None else "initializing",
                "model": "Qwen2.5-Coder-0.5B-Instruct",
                "model_revision": _model_revision[:10]
            })
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path != "/distill":
            self._send_json(404, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 2 * 1024 * 1024:
            self._send_json(413, {"error": "Payload too large (> 2 MB)"})
            return

        body = self.rfile.read(content_length).decode("utf-8")
        try:
            payload = json.loads(body)
        except Exception:
            self._send_json(400, {"error": "Malformed JSON payload"})
            return

        task = payload.get("task", "")
        snippets = payload.get("snippets", [])
        anchors = payload.get("anchors", [])
        max_tokens = min(256, max(32, int(payload.get("max_tokens", 128))))

        source_refs = []
        context_blocks = []
        for s in snippets:
            f = s.get("file", "unknown")
            s_line = s.get("startLine", 0)
            e_line = s.get("endLine", 0)
            source_refs.append(f"{f}:L{s_line}-L{e_line}")
            content = s.get("content", "")
            context_blocks.append(f"File {f}:\n{content[:500]}")

        prompt_context = "\n---\n".join(context_blocks[:3])
        if _tokenizer and hasattr(_tokenizer, "apply_chat_template"):
            messages = [
                {"role": "system", "content": "You are a concise code architecture assistant. Summarize how the provided code implements the developer task in 1-2 factual sentences. Be direct and avoid repeating phrases."},
                {"role": "user", "content": f"Task: {task}\nKey Symbols: {', '.join(anchors[:5])}\nCode snippets:\n{prompt_context}\n\nProvide a factual 1-2 sentence architectural summary:"}
            ]
            prompt = _tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        else:
            prompt = (
                f"You are a technical code analyzer. Summarize how the following code addresses the task in 1-2 sentences.\n"
                f"Task: {task}\n"
                f"Key Symbols: {', '.join(anchors[:5])}\n"
                f"Code:\n{prompt_context}\n"
                f"Summary:"
            )

        try:
            summary = self._generate_summary(prompt, max_tokens)
            self._send_json(200, {
                "text": summary,
                "model": "Qwen2.5-Coder-0.5B-Instruct",
                "model_revision": _model_revision[:10],
                "source_lines_referenced": source_refs
            })
        except Exception as e:
            logger.error("Distillation generation failed: %s", e)
            self._send_json(500, {"error": f"Inference failed: {str(e)}"})

    def _generate_summary(self, prompt: str, max_new_tokens: int) -> str:
        """Deterministic greedy generation with anti-repetition guards (DEF-038)."""
        if _model is None or _tokenizer is None:
            raise RuntimeError("Model is not initialized")

        import torch
        # Cap generation to 96 tokens for a clean 1-2 sentence summary
        effective_tokens = min(max_new_tokens, 96)
        inputs = _tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1500)
        with torch.no_grad():
            outputs = _model.generate(
                **inputs,
                max_new_tokens=effective_tokens,
                do_sample=False,
                repetition_penalty=1.2,
                no_repeat_ngram_size=3,
                pad_token_id=_tokenizer.eos_token_id,
                eos_token_id=_tokenizer.eos_token_id
            )
        generated_ids = outputs[0][inputs["input_ids"].shape[1]:]
        text = _tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
        # Clean up any trailing broken sentences
        if text and not text.endswith((".", "!", "?")):
            last_period = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
            if last_period > 20:
                text = text[:last_period + 1]
        return text or "Architectural components implement handler and service flows for requested task."

    def _send_json(self, status: int, data: Dict[str, Any]):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(port: int = 8000):
    load_model()
    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, QwenRequestHandler)
    logger.info("Qwen HTTP Sidecar serving on 0.0.0.0:%d", port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down Qwen HTTP sidecar")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    port = int(os.environ.get("QWEN_PORT", "8000"))
    run_server(port)
