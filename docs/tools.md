# Tool reference

Tools are the agent's typed capabilities. Every call passes argument
validation, is audited on the bus, and returns text safe for the model
(truncated, redacted). Handlers may raise `ToolFailure` — it becomes an
observation the model can react to, never a crash.

## Built-ins

| Tool | Purpose |
|---|---|
| `system_status` | GPU (util/VRAM/temp/power), RAM, disk snapshot |
| `web_fetch` | SSRF-guarded fetch of public http(s); HTML→text; prompt-guarded |
| `calculate` | AST-interpreted math (no eval): functions, constants, DoS guards |
| `text_analysis` | summary / word frequencies / URL-email-date-number extraction / slugify |
| `json_query` | dotted-path get, needle search, shape/stats over JSON |
| `csv_analyze` | typed describe, filter (`== != > < >= <= contains`), sort, aggregate, group |
| `statistics` | summary, quantiles, pearson, regression, moving average, robust outliers |
| `remember` / `recall_memory` | long-term memory write + hybrid semantic recall |
| `ask_human` | queue a question for the operator (approval workflow) |
| `skill_create` / `skill_list` / `skill_approve` | self-authoring tools (see below) |
| `swarm_delegate` / `debate` / `consensus` | multi-agent execution patterns |

## SkillForge (agent-authored tools)

The model proposes `{name, description, parameters, code}`. Validation:

1. regex pre-scan (imports, dunders, dangerous builtins, size cap)
2. AST walk — no `Import`/`ImportFrom`, no `_FORBIDDEN_NAMES`, no dunder
   attribute access
3. loaded via `importlib` into a namespace pre-seeded with safe builtins,
   a fixed stdlib module set, and guarded helpers:

```
fetch(url)                       # same SSRF-guarded fetcher
read_file(path) / list_dir(path) # sandbox + project, size-capped
write_file(path, content)        # sandbox-only, 64 KB cap
run_command(program, *args)      # full OpenShell policy
log(message)                     # one line in the daemon log stream
```

Execution is timeout-wrapped (sync code runs in a worker thread so
timeouts can cancel it). Default posture: new skills are **pending**
until an operator approves via dashboard, Telegram, or CLI. Autonomous
mode (`tools.skillforge.autonomous: true`) activates immediately — use it
only if you accept the residual risk.

## Writing your own builtin

```python
from tools.registry import Tool, ToolContext, ToolRegistry

def register_tools(registry: ToolRegistry) -> None:
    async def hello(ctx: ToolContext, name: str) -> str:
        return f"hello {name}"

    registry.register(Tool(
        name="hello",
        description="Say hello (demo builtin).",
        parameters={"name": {"type": "string", "required": True}},
        handler=hello))
```

Register in `kernel/daemon.py` and it appears in the model's tool list
and the dashboard automatically.
