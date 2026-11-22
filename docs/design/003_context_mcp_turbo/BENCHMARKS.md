# Benchmarks: MCP-Turbo

> **Experimental; did not work as designed.** See [README.md](README.md). This page keeps only measurements of the models themselves (memory, load and inference time on a 2-core laptop CPU), which do not depend on any repository. Pack speed, token savings and recall have not been measured on public repositories, and the projected figures in the original design were never measured.

## Model-only measurements (Phase 0)

Empirical measurements gathered in single-process container runs on the reference test host environment:
* **Host Hardware**: 2-core / 4-thread laptop CPU, no swap, one container at a time.
* **Software Base**: MCP base container image (Python 3.12, `torch` 2.8.0+cpu, `transformers` 4.57.1, Jina pinned) + Laya 0.3.22 (`pip --no-deps`) + `Qwen2.5-Coder-0.5B-Instruct`.

### Memory Footprints (Single Process RSS After Loading)

| Layer / Configuration | Resident RSS | Peak RAM | 2 GB Container Limit Result | 3 GB Container Limit Result | Increment over Jina Base |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Jina alone (Core MCP)** | 955 MB | 1,239 MB | **PASS** (Normal execution) | PASS | Baseline |
| **Jina + Laya (english 421M fp32)** | 2,630 MB | 3,123 MB | **OOM-KILLED (exit 137)** | **PASS** (Clean run) | + 1,675 MB (~ +1.7 GB) |
| **Jina + Qwen (0.5B bf16)** | 1,775 MB | 1,776 MB | PASS | PASS | + 820 MB (~ +0.8 GB) |
| **Jina + Qwen (0.5B fp32)** | 2,516 MB | 3,264 MB | not tested (resident RSS exceeds 2 GB) | PASS | + 1,561 MB (~ +1.6 GB) |
| **Jina + Laya + Qwen (bf16)** | 3,168 MB | 3,402 MB | not tested (resident RSS exceeds 2 GB) | PASS (RSS includes reclaimable mapped pages) | + 2,213 MB (~ +2.2 GB) |

### Latency Profiles on CPU Test Host

| Component / Task | Measured Wall Time | Measurement Notes |
| :--- | :--- | :--- |
| **Laya Predict (Warm)** | **6.0 s** | 3 classification questions on ~270-char sample ticket. |
| **Laya First Call (Cold)** | **52 – 61 s** | Includes in-process weights loading and initialization. |
| *Laya Vendor Claim* | *~33 ms* | **Unverified**: Vendor figure on unspecified hardware; **not reachable** on CPU test host. |
| **Qwen 512-Token Prefill (fp32)** | **19.2 s** | Measured on CPU test host. |
| **Qwen 512-Token Prefill (bf16)** | **75 – 80 s** | CPU lacks native bf16 vector instructions. |
| *Qwen Decode per Token* | *N/A (Invalid)* | Test host numbers were warm-up artifacts (-0.85, -0.29, +36.5); omitted per benchmark integrity. |

### Disk & Model Assets

| Model Checkpoint | Disk Footprint | Compatibility / Runtime Requirement |
| :--- | :--- | :--- |
| **Laya 0.3.22 (ModernBERT 421M)** | 2.3 GB | Runs on `transformers` 4.57.1 / `torch` 2.8.0+cpu. Offline mode requires `LAYA_REVISION=reviewed`. |
| **Qwen2.5-Coder-0.5B-Instruct** | 0.95 GB | Requires GPU/Metal runtime for usable latency; infeasible on CPU. |

### Empirical Conclusions for Architecture
1. **Laya Colocation Feasibility**: Laya is the only optional layer that fits and executes cleanly on CPU in-process alongside Jina, provided the MCP container limit is raised.
2. **Container Limit Adjustment**: The MCP container memory limit must be set to **3.5 GB** for `mode=turbo+jev` (providing headroom over 2,630 MB resident RSS for the repository graph cache under real load). Core mode remains under the default 2 GB limit (~955 MB RSS).
3. **Qwen Process Boundary**: Qwen cannot run on CPU (19–80 s prefill) and a 3-in-1 container exceeds 3.4 GB RSS. Qwen is strictly confined to an external HTTP sidecar service (`QWEN_ENDPOINT`) on dedicated GPU or Apple Silicon Metal.
4. **Mutual Exclusivity**: `mode=turbo+jev` and `mode=turbo+qwen` must remain strictly mutually exclusive. Core turbo remains the zero-cost default.
