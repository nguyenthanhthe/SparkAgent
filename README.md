# ⚡ SparkAgent

> An autonomous **24/7 local AI agent framework** inspired by the **Nous Hermes Agent** and the **NVIDIA OpenShell** sandbox architecture — optimized for RTX hardware (local NVIDIA Nemotron via Ollama/CUDA, with a remote GLM fallback tier).

[![CI](https://github.com/nguyenthanhthe/SparkAgent/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

SparkAgent runs continuously in the background: it schedules goals, reasons over them with a ReAct loop, executes work through a policy-guarded sandbox, remembers everything in hybrid (BM25 + vector) memory, coordinates **multi-agent swarms**, writes **new tools for itself** under a sandbox + approval gate, and is driven from a web dashboard, CLI, or Telegram.

## What's inside

| Package | Highlights |
|---|---|
| `kernel/` | 24/7 supervised daemon, ReAct state machine, scheduler, SQLite + hybrid memory, metrics, health, tracing, rate limits, circuit breakers, retries |
| `openshell/` + `security/` | sandbox profiles, allow/deny policy engine, path confinement, env sanitization, SSRF guard, prompt-injection guard, quarantine, HMAC signatures, approvals |
| `brain/` | adapter framework (Ollama / OpenAI-compatible / mock), tier router with circuits + cache + cost ledger, context budgeting |
| `tools/` + `swarm/` | 15+ built-in tools, SkillForge (agent-authored, AST-sandboxed skills), planner/worker/critic/synthesizer pipelines, debate, consensus |
| `interface/` | dashboard (live logs, approvals, quarantine), OpenAPI spec, Prometheus metrics, CLI, Telegram bot |
| `memory_search/` | BM25, RRF hybrid ranking, entity graph, extractive summarizer |
| `ops/`, `benchmarks/`, `docs/`, `examples/` | backup/restore, Docker, micro-benchmarks, full docs, runnable demos |

Full documentation starts at [docs/index.md](docs/index.md).

---

## Architecture

```
                         ┌──────────────────────────────┐
        Telegram ───────▶│       interface/             │◀──── Web dashboard
        gateway          │  (aiohttp server + bot)      │      127.0.0.1:8788
                         └──────────────┬───────────────┘
                                        │ submit / query / approve
                                        ▼
   config.yaml + env    ┌───────────────────────────────────────────┐
   ┌───────────────┐    │               kernel/                     │
   │ kernel/config │───▶│  AgentDaemon (24/7 asyncio supervisor)    │
   └───────────────┘    │   ├── scheduler  (SQLite-backed tasks)    │
                        │   ├── react      (ReAct state machine)    │
                        │   ├── memory     (SQLite + vector store)  │
                        │   └── bus        (pub/sub: logs/audit)    │
                        └──────┬──────────────────────────┬─────────┘
                               │ thoughts                 │ actions
                               ▼                          ▼
                     ┌──────────────────┐      ┌───────────────────────┐
                     │     brain/       │      │      tools/           │
                     │ Tier 1: Ollama   │      │ registry · sysmon     │
                     │  Nemotron/CUDA   │      │ webfetch · skillforge │
                     │ Tier 2: GLM API  │      └──────────┬────────────┘
                     └──────────────────┘                 │ spawn / fetch
                                                          ▼
                                                ┌───────────────────────┐
                                                │     openshell/        │
                                                │ policy · executor ·   │
                                                │ vault (secrets)       │
                                                └───────────────────────┘
```

| Package | Responsibility |
|---|---|
| `kernel/` | 24/7 asyncio daemon, ReAct state machine, task scheduler, SQLite + vector memory, event bus, config |
| `openshell/` | Safe subprocess execution: program allowlist, denylist guard, path confinement, encrypted secret vault, log redaction |
| `brain/` | Dual-tier LLM bridge — Tier 1 local (Ollama/Nemotron on the GPU), Tier 2 remote (GLM, OpenAI-compatible) |
| `tools/` | Tool registry, GPU/system monitor, SSRF-guarded web fetcher, SkillForge (agent-authored tools) |
| `interface/` | Local web dashboard (SSE live logs) and Telegram gateway (chat-ID allowlist) |
| `main.py` | Single entry point: `--check`, `--once "goal"`, or the full daemon |

---

## Quickstart

Requirements: **Python 3.10+**, an NVIDIA GPU with recent drivers (optional
but recommended), [Ollama](https://ollama.com) for the local tier.

```powershell
git clone https://github.com/nguyenthanhthe/SparkAgent
cd SparkAgent
pip install -r requirements.txt

# local tier (optional — without it everything routes to the remote tier)
ollama pull nemotron-mini
ollama pull nomic-embed-text        # better semantic memory (optional)

# credentials — environment only, never in files
copy .env.example .env              # then edit: GLM_API_KEY=...
# (or set them as real environment variables)

python main.py --check              # offline self-test
python main.py                      # start the 24/7 daemon
```

Dashboard: **http://127.0.0.1:8788**

### Environment variables

| Variable | Purpose |
|---|---|
| `GLM_API_KEY` | remote tier API key (required for Tier 2) |
| `TELEGRAM_BOT_TOKEN` | Telegram gateway (optional; enable in config) |
| `SPARKAGENT_VAULT_KEY` | master key for the encrypted vault store (optional) |
| `SPARKAGENT_WEB_TOKEN` | if set, the dashboard API requires this Bearer token |
| `SPARKAGENT_<SECTION>__<KEY>` | override any config value (e.g. `SPARKAGENT_BRAIN__LOCAL__MODEL=llama3`) |

Secrets can also be stored encrypted: `python -m openshell.vault set GLM_API_KEY`.

### Usage

```powershell
python main.py                        # 24/7 daemon (scheduler + web + telegram)
python main.py --once "check GPU temperature and report"   # single episode
python main.py --check                # offline self-test
python -m unittest discover -s tests -t .                  # test suite
python -m openshell.vault set TELEGRAM_BOT_TOKEN           # encrypted secret
```

Dashboard & Telegram:

- Submit one-shot or recurring goals (`every 5 min / hourly / daily`)
- Watch live logs (SSE), GPU/VRAM/brain-tier status, task history
- Search long-term memory semantically
- Approve or hand-craft skills (operator actions)
- Telegram: `/status`, `/tasks`, `/task <goal>`, `/mem <query>`, `/skills`, `/approve <name>` — plain text becomes a task

---

## How the kernel works

- **ReAct protocol** — each turn the model must reply with exactly one JSON
  object: `{"thought", "action": {"name", "args"}}` or
  `{"thought", "final_answer"}`. Malformed replies become corrective
  observations (3 strikes → episode fails). Every thought/action/observation
  is persisted as episode steps.
- **Scheduler** — SQLite-backed queue. One-shot, `interval_seconds`
  recurring, and `daily_at HH:MM` tasks; atomic claim via conditional
  UPDATE; concurrency-limited episodes; recurring tasks auto-disable after
  3 consecutive failures; stale `running` tasks recovered on boot.
- **Memory** — episodes, steps, audit trail, and a vector store. Recall is
  cosine similarity over embeddings (Ollama `nomic-embed-text` when the
  local tier is up, a deterministic hashing embedder otherwise), injected
  into the system prompt of new episodes. Finished episodes summarize
  themselves into memory. Retention pruned via housekeeping.
- **Daemon supervision** — every loop (scheduler, heartbeat, audit
  persistence, housekeeping, web, telegram) runs under a supervisor that
  restarts it with exponential backoff. A 24/7 daemon must survive its own
  bugs.

### Brain: dual-tier routing

1. **Tier 1 (local)** — Nemotron on your RTX GPU via Ollama. Free,
   private, fast enough for most episodes.
2. **Tier 2 (remote)** — GLM through an OpenAI-compatible endpoint
   (needs `GLM_API_KEY`).

Routing details: a tier that fails twice in a row enters a 60 s cooldown so
episodes don't stall on a dead Ollama daemon; a VRAM guard skips the local
tier when free GPU memory drops below `brain.vram_guard_mb` (mid-generation
spikes on laptop GPUs); any tier exception fails over instead of crashing.
Stats per tier are exposed on the dashboard and `/api/status`.

### Built-in tools

| Tool | What it does |
|---|---|
| `system_status` | GPU (nvidia-smi: utilization, VRAM used/free, temp, power), RAM, disk snapshot |
| `web_fetch` | Fetches a **public** http(s) URL; HTML → readable text; size-capped, redirect-checked, SSRF-guarded |
| `skill_create` | The agent writes a new tool for itself (see below) |
| `skill_list` / `skill_approve` | List skills; approve pending ones (operator-only) |

### SkillForge — the agent improves itself

The model proposes `{name, description, parameters, code}`. SkillForge
validates it (AST: no imports, no `eval`/`exec`/`open`/dunder access),
loads it into a pre-seeded restricted namespace (safe builtins +
`json, re, math, statistics, datetime, itertools, collections, textwrap,
string, uuid, random` + guarded I/O helpers), and registers it as a real
tool under a timeout. The only I/O channels are:

- `fetch(url)` — the same SSRF-guarded fetcher as `web_fetch`
- `read_file(path)` / `list_dir(path)` — confined to sandbox + project
- `write_file(path, content)` — sandbox-only, 64 KB cap
- `run_command(program, *args)` — the OpenShell executor (full policy)
- `log(msg)` — a line in the daemon log stream

New skills stay **pending** until an operator approves them via the
dashboard or Telegram, unless `tools.skillforge.autonomous: true`.
Approved skills persist under `skills/` and reload on boot.

---

## Safety & sandbox policy (OpenShell)

1. **Program allowlist** — only bare, pre-approved executable names may
   spawn (`python`, `git`, `pip`, `nvidia-smi`, …; configurable). No
   `cmd`, no `powershell`, no path-like program names.
2. **Denylist guard** — destructive/obfuscated patterns are rejected before
   spawn: `format/rd/del` of system paths, `shutdown`, registry edits,
   `schtasks`, fork bombs, encoded PowerShell, `curl | sh`,
   defense-tampering, and more (defense in depth behind the allowlist).
3. **Path confinement** — path-like arguments must resolve (after `..`
   normalization) inside the sandbox (`data/sandbox`) or the project root;
   UNC paths are rejected; skill writes are sandbox-only.
4. **No shell** — processes spawn via `create_subprocess_exec`; arguments
   are never interpreted by a shell. Metacharacter checks apply only when
   shell mode is explicitly enabled.
5. **Kill trees & limits** — timeouts kill the whole process tree
   (`taskkill /T /F`); output capture is size-capped.
6. **SSRF guard** — the web fetcher only speaks http(s) on configured
   ports, resolves the host immediately before connecting, rejects
   loopback/private/link-local (incl. cloud metadata)/reserved/CGNAT
   ranges, unwraps IPv4-mapped IPv6, and re-validates every redirect hop.
7. **Secret vault & redaction** — credentials come only from environment
   variables or an encrypted store (stdlib authenticated encryption:
   HMAC-SHA256-derived keys, PRF stream cipher, constant-time tag).
   Known secret values and common key patterns are masked in every log
   line and tool output.
8. **Skill sandbox** — see SkillForge above: static AST validation,
   restricted namespace, guarded helpers, timeouts, operator approval.
9. **Audit trail** — every execution, tool call, skill proposal/approval,
   and task submission is written to the `audit` table.

> ⚠️ **Honest limits** — this is a *policy sandbox, not a VM*. A allowlisted
> `python` process still runs with your user account's normal privileges.
> Run SparkAgent under a regular (non-admin) account, keep the allowlist
> minimal, and use the approval gate for skills. Residual DNS-rebinding
> risk in the fetcher is mitigated (resolve-then-connect on the same tick)
> but not eliminated; for hostile environments put it behind an egress
> proxy.

---

## Configuration

Defaults live in `kernel/config.py`; `config.yaml` overrides them;
`SPARKAGENT_*` environment variables override everything. See
[config.example.yaml](config.example.yaml) for the annotated reference.
Key knobs:

| Path | Default | Meaning |
|---|---|---|
| `agent.max_steps` | 12 | ReAct iterations per episode |
| `agent.concurrency` | 2 | simultaneous episodes |
| `brain.local.model` | `nemotron-mini` | Ollama model (Tier 1) |
| `brain.remote.model` | `glm-5.3` | remote model (Tier 2) |
| `brain.vram_guard_mb` | 1024 | min free VRAM to use Tier 1 |
| `openshell.allowed_programs` | … | executable allowlist |
| `tools.skillforge.autonomous` | false | skills activate without approval |
| `tools.webfetch.allowed_ports` | 80/443/8080/8443 | fetchable ports |
| `interface.web.port` | 8788 | dashboard port (localhost bind) |
| `interface.telegram.allowed_chat_ids` | [] | who may talk to the bot |

## Repository layout

```
SparkAgent/
├── main.py                 # entry point (--check / --once / daemon)
├── config.example.yaml     # annotated configuration
├── kernel/                 # daemon, react, scheduler, memory, bus, metrics, health…
├── openshell/              # policy, vault (+CLI), executor, profiles, env guard
├── security/               # policy engine, approvals, prompt guard, quarantine, signatures
├── brain/                  # adapters (ollama/openai_compat/mock), router, cache, cost, context
├── tools/                  # registry, sysmon, webfetch, skillforge, stdlib tools
├── swarm/                  # mailbox, blackboard, orchestrator, consensus, critic, topologies
├── memory_search/          # BM25, hybrid ranker, graph store, summarizer
├── interface/              # web dashboard, CLI, telegram, OpenAPI
├── ops/ benchmarks/        # backup/restore, Docker, micro-benchmarks
├── docs/ examples/         # documentation site + runnable demos
├── tests/                  # 200+ unit tests (offline — no network, no LLM)
└── data/ skills/           # runtime artifacts          (gitignored)
```

## Experimental ideas

- ✅ Agent-authored skills with static sandbox analysis + approval gate
- ✅ VRAM-aware tier routing for small laptop GPUs
- ✅ Zero-dependency hashing embedder with transparent Ollama upgrade path
- 🔭 Self-review loop: agent smoke-tests its own new skill before proposing
- 🔭 Episode reflection: periodic memory consolidation into distilled notes
- 🔭 Multi-tenant goals with per-source quotas (web vs telegram vs scheduler)
- 🔭 MicroVM/WSL isolation tier for genuinely untrusted code

## Status

Built autonomously, module by module — one atomic, always-green commit per
component (see git history and [ROADMAP.md](ROADMAP.md)). Every commit keeps
`python -m unittest discover -s tests -t .` green; CI runs the suite on
Python 3.10/3.12 × Ubuntu/Windows.

---
*SparkAgent is experimental software. The OpenShell policy layer is a
guardrail, not a VM — run it under a non-admin user account.*
