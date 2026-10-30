"""Preflight demo: the preflight report path with fake brain tiers.

Drives :func:`brain.preflight.preflight` against a fake Brain whose
tiers report deterministic health — one healthy tier, one down — and
renders the same report the CLI prints, fully offline.

    python examples/preflight_demo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.preflight import preflight   # noqa: E402


class FakeBrain:
    """Deterministic tier health: local up, remote down."""

    def __init__(self):
        self.closed = False

    async def health(self):
        return {
            "local": {"ok": True, "detail": "ok", "duration_ms": 12.5,
                      "model": "fake-local"},
            "remote": {"ok": False, "detail": "connection refused",
                       "duration_ms": 0.3, "model": "fake-remote"},
        }

    async def chat(self, messages, **_kwargs):
        class _R:
            text = "ok"
            model = "fake-local"

        return _R()

    async def close(self):
        self.closed = True


def render(report: dict) -> str:
    lines = []
    for tier in ("local", "remote"):
        entry = report[tier]
        state = "ok" if entry["ok"] else "down"
        lines.append(f"{tier:8s} {state:5s} model={entry.get('model')} "
                     f"({entry['detail']} in {entry['duration_ms']:g}ms)")
    if "chat" in report:
        chat = report["chat"]
        if chat["ok"]:
            lines.append(f"chat     ok     model={chat.get('model')} "
                         f"({chat.get('chars')} chars "
                         f"in {chat['duration_ms']:g}ms)")
        else:
            lines.append(f"chat     down   ({chat.get('error')})")
    lines.append(f"overall  {'ok' if report['healthy'] else 'no tier usable'}")
    return "\n".join(lines)


async def _run() -> dict:
    from unittest.mock import patch
    with patch("brain.bridge.Brain", lambda *a, **k: FakeBrain()):
        return await preflight(type("C", (), {})(), with_chat=True)


def main() -> None:
    report = asyncio.run(_run())
    print(render(report))


if __name__ == "__main__":
    main()
