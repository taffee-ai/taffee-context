# 003 MCP turbo: status and honest result

**Status: experimental. It did not work as designed.** The code is kept, off by default, so anyone who wants to try it or improve it can. Nothing here is a performance claim.

## What it is

One MCP tool, `assemble_context_pack(repo, task, max_tokens)`, that tries to replace an agent's search loop with a single call. It embeds the task, fetches candidate chunks and their graph neighbours from Neo4j, ranks them, and packs the best ones into a token budget.

Two optional model layers sit on top. Both are off unless their flag is set, and they cannot both be on:

| Layer | Flag | Model | What it does |
|---|---|---|---|
| JEV | `ENABLE_LAYA_JEV=true` | [Laya](https://huggingface.co/convaiinnovations/laya) 0.3.22 (Apache-2.0), in process | Routes the task, prunes candidates and checks the pack |
| Distiller | `ENABLE_QWEN_DISTILLER=true` | Qwen2.5-Coder-0.5B-Instruct, as a separate HTTP service | Adds a short summary of the pack |

The default MCP image includes the pack tool but not Laya. `Dockerfile.jev` and `Dockerfile.qwen` build the optional layers.

## Why it didn't work

1. **It was never shown to help agents.** Internal agent tests did not support the idea that one pack beats letting the agent search, and no public evaluation of the pack exists yet. Our public eval (`eval/`) left this tool out.
2. **A single shot can't recover from a bad first pick.** If the ranking misses the file that answers the question, an agent given only the pack has nothing to check it with.
3. **The pack's self-check is not trustworthy.** Its validation compares task words with the packed text, and it can report `pass` for a pack that misses the answer.
4. **The ranking is untuned.** The scoring weights (vector 0.70, degree 0.15, lexical 0.15) have not been tested against a public labelled question set.
5. **The model layers are far too slow on CPU.** Model-only measurements on a 2-core laptop ([BENCHMARKS.md](BENCHMARKS.md)):
   - **Laya:** one 3-question prediction takes about 6 s warm and about 1 minute cold, and Jina plus Laya need about 2.6 GB (killed at a 2 GB limit). A pack calls Laya several times. The roughly 33 ms per call that Laya's authors report was on hardware we didn't have.
   - **Qwen:** a 512-token prompt takes 19 to 80 s, and the service needs about 2.2 GB.
   - Neither layer has been shown to improve answers.
6. **The headline numbers in the design were never measured.** The ~92% token saving, under 1 s latency and 94–98% recall in [DESIGN.md](DESIGN.md) and the original benchmark tables were targets written before the code existed.

**What holds up:** the pack is deterministic, keeps to its token budget, and its unit tests pass. That's all that is verified.

## If you want to try it

- Run `assemble_context_pack` with both flags off first. It is the cheapest path; its accuracy has not been publicly measured.
- The model layers need a GPU or Apple Silicon to be usable. We have no measurements there.
- An agent should get the pack *and* normal search tools, so it can check a bad pack. That combination was never tested.
- Our later public eval left this tool out; see `eval/DESIGN.md`.

## Where the model layers belong

Laya and Qwen are models, not context. They fit the capabilities pillar (roadmap P04 model adapters, P06 provider selection) better than this repository. The intended direction is for context to call a configured model through a capability interface, rather than to host model code and images here. They stay here until that interface exists.

## Reading the rest of this folder

The other files are the original design, requirements, decisions, test plan and assumptions. Where they make claims about speed, savings or recall, this page takes precedence. The development log (milestones, defects, verification runs) is not published; `DEF-nnn` numbers in code comments refer to it.

`m9/tasks-nest.json` holds five questions about NestJS (public), reused by the public eval.
