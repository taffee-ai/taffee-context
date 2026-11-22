#!/usr/bin/env python3
"""
turbo_distiller.py: Milestone 8 Qwen Distiller Client Layer.

Provides QwenDistillerClient for optional SLM distillation (mode=turbo+qwen).
Communicates with an external HTTP sidecar service (QWEN_ENDPOINT) running
on dedicated GPU/Metal/hardware.

Design & Hard Guarantees:
  1. Mutual Exclusivity: mode=turbo+qwen and mode=turbo+jev are strictly mutually exclusive.
     If both ENABLE_QWEN_DISTILLER and ENABLE_LAYA_JEV are enabled, ValueError is raised immediately.
  2. Zero Overhead: When ENABLE_QWEN_DISTILLER is false/unset, zero network calls are made,
     zero external processes are spawned, and memory/latency overhead is strictly 0.
  3. Payload Isolation: Distilled output is placed exclusively in the top-level
     `derived_summary` field containing `model`, `model_revision`, `source_lines_referenced`,
     and `text`.
  4. Evidence Immutability: `code_evidence` is strictly byte-identical with and without the
     distiller. The distiller never mutates, truncates, or edits code lines.
  5. Determinism Documentation: `derived_summary` is documented as outside the byte-identical
     guarantee (greedy decoding is used by the sidecar to keep outputs as stable as possible).
  6. Robust Fallback: If the sidecar service times out (QWEN_TIMEOUT_S), connection is refused,
     returns malformed JSON, or fails, the client gracefully falls back to the plain pack,
     notes the fallback in `pack["validation"]["reasons"]`, and NEVER crashes or raises.
"""

import os
import sys
import json
import time
import logging
import urllib.request
import urllib.error
import asyncio
from typing import Dict, Any, List, Optional

logger = logging.getLogger("turbo_distiller")


class QwenDistillerClient:
    """Client for optional Qwen Distillation Sidecar Service."""

    def __init__(self, endpoint: Optional[str] = None, timeout_s: Optional[float] = None):
        self.enabled = os.environ.get("ENABLE_QWEN_DISTILLER", "").lower() in ("true", "1", "yes")
        self.endpoint = endpoint or os.environ.get("QWEN_ENDPOINT", "http://127.0.0.1:8000/distill")
        
        raw_timeout = timeout_s if timeout_s is not None else os.environ.get("QWEN_TIMEOUT_S", "2.0")
        try:
            self.timeout_s = float(raw_timeout)
        except (ValueError, TypeError):
            self.timeout_s = 2.0

        # Enforce strict mutual exclusivity with Laya JEV
        self._enforce_mutual_exclusivity()

    def _enforce_mutual_exclusivity(self) -> None:
        """Enforces mutual exclusivity between turbo+qwen and turbo+jev modes."""
        if not self.enabled:
            return
        jev_enabled = os.environ.get("ENABLE_LAYA_JEV", "").lower() in ("true", "1", "yes")
        if jev_enabled:
            raise ValueError(
                "Mutual exclusivity violation: ENABLE_QWEN_DISTILLER and ENABLE_LAYA_JEV "
                "cannot both be true (mode=turbo+qwen and mode=turbo+jev are strictly mutually exclusive)"
            )

    def distill_sync(self, task: str, pack: Dict[str, Any]) -> Dict[str, Any]:
        """
        Synchronously distill a context pack using the external Qwen sidecar.
        
        Returns the pack with `derived_summary` populated on success,
        or the original pack with a validation note on fallback.
        `code_evidence` is NEVER mutated.
        """
        if not self.enabled:
            return pack

        # Prepare source line references from code evidence
        code_evidence = pack.get("code_evidence", [])
        source_refs = []
        snippets = []
        for c in code_evidence:
            f = c.get("file", "unknown")
            s = c.get("startLine", 0)
            e = c.get("endLine", 0)
            source_refs.append(f"{f}:L{s}-L{e}")
            lines = c.get("raw_lines") or c.get("lines") or []
            content_str = "\n".join(lines) if isinstance(lines, list) else str(lines)
            snippets.append({
                "file": f,
                "startLine": s,
                "endLine": e,
                "content": content_str
            })

        # Prepare payload for Qwen sidecar
        payload = {
            "task": task,
            "repo": pack.get("metadata", {}).get("repoId", ""),
            "anchors": [a.get("label", "") for a in pack.get("architectural_anchors", [])],
            "snippets": snippets,
            "max_tokens": 256
        }

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint,
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                status_code = resp.getcode()
                if status_code != 200:
                    raise RuntimeError(f"Qwen sidecar returned HTTP status {status_code}")
                body = resp.read().decode("utf-8")
                data = json.loads(body)

            summary_text = data.get("text") or data.get("summary")
            if not summary_text or not isinstance(summary_text, str):
                raise ValueError("Malformed reply: missing or invalid 'text'/'summary' field")

            model_name = data.get("model", "Qwen2.5-Coder-0.5B-Instruct")
            model_revision = data.get("model_revision", data.get("revision", "pinned-offline"))

            # Populate derived_summary in isolated top-level field
            pack["derived_summary"] = {
                "model": model_name,
                "model_revision": model_revision,
                "source_lines_referenced": source_refs,
                "text": summary_text
            }
            return pack

        except urllib.error.HTTPError as e:
            err_msg = f"HTTP {e.code}"
            logger.warning("Qwen distiller HTTP error: %s", err_msg)
            self._record_fallback(pack, f"HTTP error {e.code}")
            return pack
        except urllib.error.URLError as e:
            err_msg = f"Connection failed: {e.reason}"
            logger.warning("Qwen distiller unreachable: %s", err_msg)
            self._record_fallback(pack, "service unreachable")
            return pack
        except TimeoutError:
            logger.warning("Qwen distiller timed out after %.1fs", self.timeout_s)
            self._record_fallback(pack, f"timeout > {self.timeout_s}s")
            return pack
        except json.JSONDecodeError:
            logger.warning("Qwen distiller returned non-JSON payload")
            self._record_fallback(pack, "malformed non-JSON reply")
            return pack
        except Exception as e:
            logger.warning("Qwen distiller failed: %s", e)
            self._record_fallback(pack, str(e))
            return pack

    async def distill(self, task: str, pack: Dict[str, Any]) -> Dict[str, Any]:
        """Asynchronously distill a context pack without blocking event loop."""
        if not self.enabled:
            return pack
        return await asyncio.to_thread(self.distill_sync, task, pack)

    def enhance_pack(self, builder: Any, repo: str, task: str, max_tokens: int = 4000, commit: Optional[str] = None) -> Dict[str, Any]:
        """Convenience method coordinating builder pack creation and Qwen distillation."""
        pack = builder.build_pack(repo=repo, task=task, max_tokens=max_tokens, commit=commit)
        if self.enabled:
            return self.distill_sync(task, pack)
        return pack

    def _record_fallback(self, pack: Dict[str, Any], reason: str) -> None:
        """Safely appends fallback diagnostic into pack validation object."""
        if "derived_summary" in pack:
            del pack["derived_summary"]
        validation = pack.setdefault("validation", {})
        reasons = validation.setdefault("reasons", [])
        msg = f"Qwen distiller fallback ({reason}); algorithmic core pack preserved"
        if msg not in reasons:
            reasons.append(msg)
