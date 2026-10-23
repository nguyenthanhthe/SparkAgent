# SparkAgent

> An autonomous 24/7 local AI agent kernel inspired by the Nous Hermes Agent and NVIDIA OpenShell architecture, optimized for RTX hardware (Nemotron / CUDA / ZCode API).

## Overview
SparkAgent is an experimental personal autonomous agent runtime running continuously in the background on Windows. It combines:
- **Kernel & Event Loop**: 24/7 asyncio ReAct state-machine with persistent task scheduling.
- **OpenShell Sandbox**: Windows subprocess isolation, path confinement, and execution guardrails.
- **Brain Engine**: Dual-tier LLM bridge with local GPU acceleration (NVIDIA Nemotron via Ollama/CUDA) and cloud fallback (ZCode GLM-5.3 1M context).
- **Self-Improving Tooling**: Dynamic skill generator enabling the agent to synthesize, test, and register new tools at runtime.
- **Long-term Memory**: SQLite + Vector Store indexing conversations, preferences, and workspace knowledge.

## Status
*Under active autonomous development via ZCode GLM-5.3.*
