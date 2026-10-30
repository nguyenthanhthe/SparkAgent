# Configuration reference

Defaults live in `kernel/config.py`. Overrides: `config.yaml` < environment (`SPARKAGENT_` prefix, `__` nesting — e.g. `SPARKAGENT_BRAIN__LOCAL__MODEL`). Credentials never appear here; they come from env/vault.

## `agent`

| Path | Default | Notes |
|---|---|---|
| `agent.name` | `sparkagent` |  |
| `agent.max_steps` | `12` | ReAct iterations per episode before failing |
| `agent.poll_seconds` | `5` | scheduler tick interval |
| `agent.concurrency` | `2` | max simultaneous ReAct episodes |
| `agent.heartbeat_seconds` | `30` | system snapshot cadence |

## `brain`

| Path | Default | Notes |
|---|---|---|
| `brain.local.enabled` | `True` |  |
| `brain.local.base_url` | `http://127.0.0.1:11434` | Ollama endpoint (Tier 1) |
| `brain.local.model` | `nemotron-mini` | local model — `ollama pull <model>` |
| `brain.local.timeout` | `180.0` |  |
| `brain.local.num_ctx` | `8192` |  |
| `brain.local.temperature` | `0.4` |  |
| `brain.remote.enabled` | `True` |  |
| `brain.remote.chat_url` | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | OpenAI-compatible endpoint (Tier 2) |
| `brain.remote.model` | `glm-5.3` | remote model name |
| `brain.remote.timeout` | `120.0` |  |
| `brain.remote.temperature` | `0.4` |  |
| `brain.fallback_after_failures` | `2` | tier failures before cooldown |
| `brain.vram_guard_mb` | `1024` | min free VRAM to use Tier 1 |
| `brain.health_ttl` | `30.0` |  |
| `brain.daily_budget_usd` | `5.0` | daily remote-tier spend cap (veto) |
| `brain.cache_responses` | `False` |  |
| `brain.cache_entries` | `256` |  |
| `brain.cache_ttl` | `900.0` |  |

The daily budget veto: once the cost tracker's `today_usd` reaches
`brain.daily_budget_usd`, remote-tier chats are vetoed (the local tier
keeps working). Today's spend and the cap surface in `/api/brain`'s
`budget` block and in the dashboard cost panel; the veto also shows up
as a chat failure with "budget" in the detail.

## `memory`

| Path | Default | Notes |
|---|---|---|
| `memory.db_path` | `data/sparkagent.db` | SQLite database location |
| `memory.embedding_model` | `nomic-embed-text` | Ollama embeddings (falls back to hashing) |
| `memory.embed_dim` | `384` |  |
| `memory.recall_k` | `5` |  |
| `memory.retention_days` | `30` | episode/step pruning horizon |

## `openshell`

| Path | Default | Notes |
|---|---|---|
| `openshell.timeout` | `60.0` |  |
| `openshell.max_output_bytes` | `131072` |  |
| `openshell.allow_shell` | `False` |  |
| `openshell.execs_per_minute` | `30.0` | per-program rate limit (0 = off) |
| `openshell.profile` | `standard` | strict | standard | development |
| `openshell.backend` | `auto` |  |
| `openshell.sandbox_name` | `sparkagent` |  |
| `openshell.minimum_version` | `0.1.0` |  |
| `openshell.allowed_programs` | `['python', 'py', 'pip', 'git', 'node', 'npm', 'nvidia-smi', 'where', 'tasklist', 'systeminfo']` | executable allowlist (bare names) |

## `tools`

| Path | Default | Notes |
|---|---|---|
| `tools.webfetch.max_bytes` | `2097152` |  |
| `tools.webfetch.timeout` | `30.0` |  |
| `tools.webfetch.allowed_ports` | `[80, 443, 8080, 8443]` | fetchable ports |
| `tools.webfetch.max_chars` | `6000` |  |
| `tools.webfetch.prompt_guard` | `True` | scan fetched text for injections |
| `tools.skillforge.autonomous` | `False` | skills activate without approval |
| `tools.skillforge.exec_timeout` | `30.0` |  |
| `tools.skillforge.sign_skills` | `True` | HMAC-sign skills (needs vault key) |

## `interface`

| Path | Default | Notes |
|---|---|---|
| `interface.web.enabled` | `True` |  |
| `interface.web.host` | `127.0.0.1` | dashboard bind (keep 127.0.0.1) |
| `interface.web.port` | `8788` |  |
| `interface.telegram.enabled` | `False` |  |
| `interface.telegram.allowed_chat_ids` | `[]` | who may command the bot |

## `logging`

| Path | Default | Notes |
|---|---|---|
| `logging.level` | `INFO` | INFO | DEBUG | json (JSON-lines output) |
| `logging.file` | `data/logs/sparkagent.log` |  |
