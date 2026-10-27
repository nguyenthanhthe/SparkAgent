# HTTP API

Machine-readable spec: `GET /api/openapi.json` (OpenAPI 3.0). Summary:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | daemon status (uptime, brain tiers, tools, approvals, quarantine stats) |
| GET | `/api/tasks?status=&limit=` · POST `/api/tasks` | list (allowlisted `status` filter) / submit goals (`interval_seconds` ≥ 60 for recurring, `depends_on` for chains) |
| GET | `/api/tasks/{id}` | task detail with `blocked_by` |
| POST | `/api/tasks/{id}/{cancel\|pause\|resume}` | task control (emits scheduler events) |
| GET | `/api/episodes?limit=` | recent episodes with outcomes |
| GET | `/api/episodes/{id}` | episode detail + step replay + `step_count` |
| GET | `/api/memories?q=` | hybrid semantic recall |
| DELETE | `/api/memories/{key}` | operator forget (audited) |
| GET | `/api/skills` · POST `/api/skills` | list / create (operator source) |
| POST | `/api/skills/{name}/approve` | activate a pending skill |
| GET | `/api/approvals` | operator approval queue |
| POST | `/api/approvals/{id}/{approve\|deny}` | decide |
| GET | `/api/quarantine?reason=` | quarantined content (reason filter) |
| GET | `/api/quarantine/{id}` | one item: record + content |
| POST | `/api/quarantine/{id}/{release\|restore\|delete}` | sanitized release / two-step restore / deletion |
| GET | `/api/backup` | backup window listing (name, age, tag) |
| GET | `/api/docs/{name}` | allowlisted runbook text (e.g. `runbook-backups`) |
| GET | `/api/brain` | tier health, stats, cache, costs (`costs_last_7_days`), lifecycle |
| GET | `/api/adapters` | tier stats + per-adapter ping latency (`interface.ping_skip` opts out) |
| GET | `/api/db/{table}` | read-only lookups (episodes, steps, memories, tasks, audit) |
| GET | `/api/health` | subsystem health report |
| GET | `/metrics` | Prometheus exposition |
| GET | `/api/stream` | SSE: live redacted log lines |

## Authentication

The dashboard binds `127.0.0.1` by default — localhost only. To expose
it, set `SPARKAGENT_WEB_TOKEN`: every `/api` request must then carry
`Authorization: Bearer <token>` (or `?token=` for SSE).

## CLI

```
python -m interface.cli status
python -m interface.cli submit "summarize today's gpu metrics"
python -m interface.cli approvals          # then: approve <id>
python -m interface.cli mem "gpu thermal"
```

The CLI refuses non-loopback URLs unless `SPARKAGENT_CLI_ALLOW_REMOTE=1`
is set — deliberate friction against leaking agent data to a typo.
