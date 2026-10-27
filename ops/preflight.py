"""Combined operator preflight — one command before starting the daemon.

    python -m ops.preflight [--data-dir PATH] [--json]

Checks, in order:
1. config loads and required sections are present;
2. brain tier health (at least one tier usable);
3. data-directory disk usage below the warn threshold;
4. backup freshness (newest archive < 24h old, window non-empty).

Exit codes: 0 = all clear, 1 = something needs attention, 2 = hard
error (config unreadable). Individual check results are always printed
so a failure is actionable, not just signaled.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from kernel.config import Config


async def _brain_check(config: Config) -> dict:
    from brain.preflight import preflight
    report = await preflight(config, with_chat=False)
    return {"ok": report["healthy"],
            "detail": f"local={report['local']['ok']} "
                      f"remote={report['remote']['ok']}"}


def _disk_check(data_dir: Path) -> dict:
    from ops.diskwatch import DEFAULT_WARN_MB, check_usage
    report = check_usage(data_dir)
    return {"ok": report.level == "ok",
            "detail": f"{report.total_mb:.1f} MB "
                      f"(warn at {report.warn_threshold_mb:g} MB, "
                      f"level={report.level})"}


def _backup_check(config: Config) -> dict:
    """Warn when the newest archive is stale (>24h) or none exists —
    a backup window you never exercise is a hope, not a backup."""
    import time as _time
    from ops.backup import list_backups
    listing = list_backups(config.root / config.get("ops.backup_dir",
                                                    "backups"))
    archives = listing["archives"]
    if not archives:
        return {"ok": False,
                "detail": "no backups found — run python -m ops.backup "
                          "create"}
    age_hours = archives[0]["age_s"] / 3600
    if age_hours > 24:
        return {"ok": False,
                "detail": f"newest backup is {age_hours:.0f}h old "
                          f"({archives[0]['name']}) — schedule a create"}
    return {"ok": True,
            "detail": f"newest backup {age_hours:.1f}h old "
                      f"({archives[0]['name']})"}


def _config_check(config_path: str | None) -> tuple[Config | None, dict]:
    try:
        config = Config.load(config_path) if config_path else Config.load()
        return config, {"ok": True,
                        "detail": f"agent={config.get('agent.name')} "
                                  f"root={config.root}"}
    except Exception as exc:   # noqa: BLE001 — report, don't crash
        return None, {"ok": False, "detail": str(exc)[:200]}


async def preflight_all(data_dir: Path,
                        config_path: str | None = None) -> list[dict]:
    config, config_result = _config_check(config_path)
    checks = [{"name": "config", **config_result}]
    if config is not None:
        checks.append({"name": "brain", **await _brain_check(config)})
    else:
        checks.append({"name": "brain", "ok": False,
                       "detail": "skipped — config unreadable"})
    checks.append({"name": "disk",
                   **_disk_check(data_dir)})
    if config is not None:
        checks.append({"name": "backup",
                       **_backup_check(config)})
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ops.preflight",
        description="Combined config/brain/disk preflight before "
                    "starting the daemon.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help="data directory to measure (default: ./data)")
    parser.add_argument("--config", type=str, default=None,
                        help="path to config.yaml")
    parser.add_argument("--json", action="store_true",
                        help="emit check results as JSON")
    args = parser.parse_args(argv)

    try:
        checks = asyncio.run(preflight_all(args.data_dir, args.config))
    except Exception as exc:   # noqa: BLE001 — hard error
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"checks": checks}, indent=2))
    else:
        for check in checks:
            mark = "ok" if check["ok"] else "ATTENTION"
            print(f"{check['name']:<8} {mark:<10} {check['detail']}")

    if not any(check["name"] == "config" and check["ok"]
               for check in checks):
        return 2
    return 0 if all(check["ok"] for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
