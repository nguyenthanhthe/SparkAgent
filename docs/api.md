# HTTP API

Machine-readable spec: `GET /api/openapi.json` (OpenAPI 3.0). Summary:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | daemon status (uptime, brain tiers, tools, approvals) |
| GET | `/api/tasks` · POST `/api/tasks` | list / submit goals (`interval_seconds` ≥ 60 for recurring) |
| POST | `/api/tasks/{id}/{cancel\|pause\|resume}` | task control |
| GET | `/api/episodes?limit=` | recent episodes with outcomes |
| GET | `/api/memories?q=` | hybrid semantic recall |
| GET | `/api/skills` · POST `/api/skills` | list / create (operator source) |
| POST | `/api/skills/{name}/approve` | activate a pending skill |
| GET | `/api/approvals` | operator approval queue |
| POST | `/api/approvals/{id}/{approve\|deny}` | decide |
| GET | `/api/quarantine` | quarantined content |
| POST | `/api/quarantine/{id}/{release\|delete}` | sanitized release / deletion |
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
