# SparkAgent

> An autonomous 24/7 local AI agent kernel inspired by the **Nous Hermes Agent** and **NVIDIA OpenShell** sandbox architecture — optimized for RTX hardware (local Nemotron via Ollama/CUDA, with remote GLM fallback).

## Overview

SparkAgent is a personal autonomous agent runtime that runs continuously in the
background on Windows. It combines:

- **Kernel** (`kernel/`) — a 24/7 asyncio daemon hosting a ReAct state machine,
  a persistent task scheduler, and SQLite + vector long-term memory.
- **OpenShell sandbox** (`openshell/`) — a safe process executor with program
  allowlists, a dangerous-command denylist, path confinement, and an encrypted
  secret vault with log redaction.
- **Brain** (`brain/`) — a dual-tier LLM bridge: Tier 1 runs NVIDIA Nemotron
  locally through Ollama on the GPU; Tier 2 falls back to a remote GLM
  (OpenAI-compatible) endpoint when the local tier is unhealthy or out of VRAM.
- **Tools** (`tools/`) — system monitor (NVIDIA-SMI / VRAM), a hard SSRF-guarded
  web fetcher, and **SkillForge**: the agent can write, sandbox-check, and
  register *new tools for itself* at runtime.
- **Interface** (`interface/`) — a minimal local web dashboard (live logs,
  task submission, memory search) and a Telegram gateway for remote control.

## Architecture

```
                         ┌──────────────────────────────┐
        Telegram ───────▶│       interface/             │◀──── Web dashboard
        gateway          │  (aiohttp server + bot)      │      127.0.0.1:8788
                         └──────────────┬───────────────┘
                                        │ submit / query
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
                     │ Tier1: Ollama    │      │ registry + sysmon +   │
                     │  Nemotron/CUDA   │      │ webfetch + skillforge │
                     │ Tier2: GLM API   │      └──────────┬────────────┘
                     └──────────────────┘                 │ spawn
                                                          ▼
                                                ┌───────────────────────┐
                                                │     openshell/        │
                                                │ policy · executor ·   │
                                                │ vault (secrets)       │
                                                └───────────────────────┘
```

## Status

*Under active autonomous development.* Build order: scaffold → openshell →
brain → tools → kernel → interface → entrypoint. See git history for progress.

## Safety model (summary)

1. **Program allowlist** — only bare, pre-approved executable names may spawn.
2. **Denylist guard** — destructive patterns (`format`, `del /f /q`,
   `shutdown`, `reg add`, fork bombs, `curl | sh`, encoded PowerShell, …)
   are rejected before spawn.
3. **Path confinement** — any path-like argument must resolve inside the
   sandbox or the project root; UNC paths rejected.
4. **No shell** — processes are spawned with `create_subprocess_exec`,
   never through `cmd /c` / PowerShell string interpretation.
5. **SSRF guard** — the web fetcher only speaks http(s), validates ports,
   and refuses hosts resolving to loopback/private/reserved/CGNAT ranges,
   re-validating on every redirect hop.
6. **Secret vault** — credentials come from env vars or an encrypted local
   vault file; a redaction layer masks secret values in all logs and tool
   output.
7. **Skill sandbox** — agent-written tools pass AST static analysis (no
   imports, no dunder access, no eval/exec/open), run with restricted
   builtins, and only touch the outside world through guarded helpers
   (`fetch`, `read_file`, `write_file`, `run_command`). By default new
   skills require operator approval.

## Usage

*Being filled in as modules land — see sections below (Work in progress).*

## Experimental ideas

- Agent-authored skills with a self-review loop (write → static check →
  smoke-test → optional operator approval → register).
- VRAM-aware routing: skip the local tier when free VRAM drops below a
  threshold (mid-generation spikes on small laptop GPUs).
- Hashing-embedder fallback so semantic memory works with zero extra
  downloads, upgradeable to Ollama embeddings for quality.

---
*SparkAgent is experimental software. The OpenShell policy layer is a
guardrail, not a VM: run it under a regular (non-admin) user account.*
