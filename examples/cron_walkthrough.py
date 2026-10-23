"""Scheduling walkthrough — every task shape SparkAgent supports.

Covers one-shot, interval, daily multi-time, and weekday-filtered
schedules, plus the retry behavior for transient failures — offline:

    python examples/cron_walkthrough.py
"""

import asyncio
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.memory import Memory, _next_daily   # noqa: E402


async def main() -> None:
    memory = Memory(Path(tempfile.mkdtemp()) / "cron.db",
                    embedder_fn=None, embed_dim=64)
    await memory.connect()

    one_shot = await memory.submit_task("summarize today's gpu metrics",
                                        "operator")
    hourly = await memory.submit_task("check gpu temperature", "operator",
                                      interval_seconds=3600)
    daily = await memory.submit_task("morning report", "operator",
                                     daily_at="09:00,17:30")
    weekdays = await memory.submit_task("weekday backup audit", "operator",
                                        daily_at="mon-fri@18:30")

    print("submitted:")
    for task_id in (one_shot, hourly, daily, weekdays):
        row = (await memory.list_tasks(task_id=task_id))[0]
        due = datetime.fromtimestamp(row["next_run_at"])
        print(f"  #{task_id} {row['goal'][:32]:<34} next: {due}")

    now = datetime(2026, 10, 23, 18, 0)          # a Friday evening
    print("\nnext runs computed from Friday 18:00:")
    for spec in ("09:00", "09:00,17:30", "mon-fri@09:00", "sat,sun@10:00"):
        nxt = datetime.fromtimestamp(_next_daily(spec, now))
        delta = nxt - now
        print(f"  {spec:<16} -> {nxt:%a %H:%M}  (in {delta})")

    # retry behavior: a failed one-shot re-arms with backoff
    await memory.mark_task_running(one_shot)
    await memory.finish_task(one_shot, success=False)
    rearmed = await memory.retry_one_shot(one_shot,
                                          (datetime.now()
                                           + timedelta(minutes=2)).timestamp())
    row = (await memory.list_tasks(task_id=one_shot))[0]
    print(f"\nfailed one-shot re-armed for retry: {rearmed} "
          f"(status={row['status']})")

    await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
