"""Brain preflight — check every configured tier before starting work.

    python -m brain.preflight [--config PATH] [--json] [--chat]

Reports per-tier health (local Ollama, remote GLM) and exits with a
machine-usable code so startup scripts and runbooks can gate on it:
0 = at least one tier usable, 1 = no tier usable, 2 = configuration or
runtime error. ``--chat`` additionally sends a tiny completion through
the normal failover path (records cost when usage is reported).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

from kernel.config import Config


async def preflight(config: Config, with_chat: bool = False) -> dict:
    """Probe both tiers; returns {healthy, local, remote, chat?}."""
    from openshell.vault import SecretVault
    from brain.bridge import Brain
    from kernel.bus import EventBus

    brain = Brain(config, SecretVault(), EventBus())
    try:
        health = await brain.health()
        report = {"healthy": False,
                  "local": health["local"],
                  "remote": health["remote"]}
        if with_chat:
            t0 = time.perf_counter()
            try:
                response = await brain.chat(
                    [{"role": "user",
                      "content": "Reply with the single word: ok"}])
                report["chat"] = {"ok": bool(response.text.strip()),
                                  "model": response.model,
                                  "chars": len(response.text),
                                  "duration_ms": round(
                                      (time.perf_counter() - t0) * 1000, 1)}
            except Exception as exc:   # noqa: BLE001 — report, don't crash
                report["chat"] = {"ok": False, "error": str(exc)[:200],
                                  "duration_ms": round(
                                      (time.perf_counter() - t0) * 1000, 1)}
        chat_ok = report.get("chat", {}).get("ok", True)
        report["healthy"] = ((report["local"]["ok"]
                              or report["remote"]["ok"]) and chat_ok)
        return report
    finally:
        await brain.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m brain.preflight",
        description="Check brain tier health before starting the daemon.")
    parser.add_argument("--config", type=str, default=None,
                        help="path to config.yaml (default: auto-discover)")
    parser.add_argument("--chat", action="store_true",
                        help="also send a tiny test completion")
    parser.add_argument("--json", action="store_true",
                        help="emit the report as JSON")
    args = parser.parse_args(argv)

    try:
        config = Config.load(args.config) if args.config else Config.load()
    except Exception as exc:   # noqa: BLE001 — config errors are fatal
        print(f"error loading config: {exc}", file=sys.stderr)
        return 2

    try:
        report = asyncio.run(preflight(config, with_chat=args.chat))
    except Exception as exc:   # noqa: BLE001 — runtime errors are fatal
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        for tier in ("local", "remote"):
            entry = report[tier]
            state = "ok" if entry["ok"] else "down"
            duration = entry.get("duration_ms")
            timing = f" in {duration:g}ms" if duration is not None else ""
            print(f"{tier:8s} {state:5s} "
                  f"model={entry.get('model')} ({entry['detail']}"
                  f"{timing})")
        if "chat" in report:
            chat = report["chat"]
            if chat["ok"]:
                print(f"chat     ok     model={chat.get('model')} "
                      f"({chat.get('chars')} chars)")
            else:
                print(f"chat     down   ({chat.get('error')})")
        print(f"overall  {'ok' if report['healthy'] else 'no tier usable'}")
    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
