# Operations

Running SparkAgent as a 24/7 service.

## Starting

```powershell
pip install -r requirements.txt
python main.py                      # daemon (web on 127.0.0.1:8788)
python main.py --once "goal text"   # single episode
python main.py --check              # offline self-test
```

## Windows service

Run under Task Scheduler (survives reboots) or NSSM:

```
nssm install SparkAgent "C:\Python314\python.exe" "D:\Project\SparkAgent\main.py"
nssm set SparkAgent AppDirectory D:\Project\SparkAgent
nssm set SparkAgent AppStdout D:\Project\SparkAgent\data\logs\service.log
nssm start SparkAgent
```

## Docker

```
docker compose up -d                # dashboard on 127.0.0.1:8788
```

The container targets `host.docker.internal:11434` for Ollama; without a
GPU tier everything routes to the remote tier. Data and skills are named
volumes.

## Health & monitoring

- `GET /api/health` — subsystem checks (memory, brain, executor) with
  worst-status aggregation; the Docker healthcheck uses it.
- `GET /metrics` — Prometheus exposition (episode counters, GPU gauges,
  tool latency histograms, health level).
- `GET /api/status` — one-stop dashboard payload.
- `logging.level: json` — JSON-lines console output for shippers, with
  trace ids from the span system.

## Backups

```
python -c "from ops.backup import create_backup; from pathlib import Path; \
    print(create_backup(Path('data'), Path('backups')))"
```

Archives are zip + manifest with per-file SHA-256 and a set digest;
restore verifies every hash before writing (`restore_backup`). The vault
file is excluded — carry the master key separately.

## Upgrades

1. `git pull`
2. `python -m unittest discover -s tests -t .` — must be green
3. `python main.py --check`
4. restart the service (skills and memory are forward-compatible;
   schema changes run through `kernel/memory.py` DDL).

## Troubleshooting

| Symptom | Check |
|---|---|
| Episodes fail instantly | `/api/health` brain section; GLM_API_KEY set? Ollama pulled? |
| Local tier skipped | `brain.vram_guard_mb` vs free VRAM in `/api/status` |
| Web unreachable | port 8788 free? bound to 127.0.0.1 (SPARKAGENT_WEB_TOKEN?) |
| Tasks stuck 'running' | daemon restarted mid-episode — recovered on next boot |
| Skills not loading | `data/logs/sparkagent.log` load errors; signature key set? |
