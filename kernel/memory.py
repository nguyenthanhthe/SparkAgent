"""Persistent memory: SQLite for episodes/steps/tasks/audit + vector recall.

All SQL goes through parameter binding — no query in this module is built
by string formatting. The connection is owned by a worker thread (accessed
via ``asyncio.to_thread`` under a lock, WAL mode for concurrent readers).

Embeddings: Ollama embeddings when the local tier is up (model from
``memory.embedding_model``), otherwise a deterministic hashing embedder
(words + bigrams hashed into a fixed-width, L2-normalized vector). Recall
is exact cosine similarity over stored vectors — fine for a personal
agent's memory scale (thousands of entries).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import sqlite3
import struct
import threading
import time
from array import array
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from kernel.logging import get_logger

logger = get_logger("memory")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    final_answer TEXT,
    model_tier TEXT,
    steps INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT,
    text TEXT NOT NULL,
    embedding BLOB,
    meta TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL,
    goal TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    interval_seconds INTEGER,
    daily_at TEXT,
    next_run_at REAL NOT NULL,
    last_run_at REAL,
    last_status TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_steps_episode ON steps(episode_id);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(enabled, status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
"""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _pack(vector: list[float]) -> bytes:
    return array("f", vector).tobytes()


def _unpack(blob: bytes) -> array:
    values = array("f")
    values.frombytes(blob)
    return values


class HashingEmbedder:
    """Dependency-free deterministic embedder (bag of hashed words + bigrams)."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = re.findall(r"[a-z0-9]{2,}", text.lower())
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"),
                                     digest_size=8).digest()
            index = struct.unpack(">I", digest[:4])[0] % self.dim
            sign = 1.0 if digest[4] % 2 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


@dataclass
class MemoryHit:
    id: int
    kind: str
    key: str | None
    text: str
    score: float
    created_at: str


class Memory:
    def __init__(self, db_path: Path,
                 embedder_fn: Callable[[str], Any] | None = None,
                 embed_dim: int = 384, recall_k: int = 5,
                 retention_days: int = 30):
        """``embedder_fn`` is an async callable text->vector (the brain's
        ``embed``), or None to use the built-in hashing embedder."""
        self.db_path = db_path
        self._embedder_fn = embedder_fn
        self._hashing = HashingEmbedder(embed_dim)
        self.recall_k = recall_k
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._vector_dim_warned = False

    # ----------------------------------------------------------------- setup
    def connect_sync(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info("memory open: %s", self.db_path)

    async def connect(self) -> None:
        await asyncio.to_thread(self.connect_sync)

    async def close(self) -> None:
        def _close() -> None:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
        await asyncio.to_thread(self._close_locked_impl, _close)

    def _close_locked_impl(self, fn) -> None:
        with self._lock:
            fn()

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("memory not connected (call connect() first)")
        return self._conn

    def _run(self, fn, *args, **kwargs):
        """Run a DB operation in the worker thread while holding the lock."""
        def guarded():
            conn = self._require_conn()
            with self._lock:
                return fn(conn, *args, **kwargs)
        return asyncio.to_thread(guarded)

    # -------------------------------------------------------------- episodes
    async def start_episode(self, goal: str, source: str) -> int:
        def op(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO episodes (created_at, source, goal, status) "
                "VALUES (?, ?, ?, 'running')",
                (_now_iso(), source, goal[:2000]))
            conn.commit()
            return int(cursor.lastrowid)
        return await self._run(op)

    async def log_step(self, episode_id: int, idx: int, kind: str,
                       content: str) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO steps (episode_id, idx, kind, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (episode_id, idx, kind, content[:8000], _now_iso()))
            conn.commit()
        await self._run(op)

    async def finish_episode(self, episode_id: int, status: str,
                             final_answer: str | None, model_tier: str,
                             steps: int) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE episodes SET status = ?, final_answer = ?, "
                "model_tier = ?, steps = ? WHERE id = ?",
                (status, (final_answer or "")[:8000], model_tier, steps,
                 episode_id))
            conn.commit()
        await self._run(op)

    async def recent_episodes(self, limit: int = 20) -> list[dict]:
        def op(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                "SELECT id, created_at, source, goal, status, final_answer, "
                "model_tier, steps FROM episodes ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
            return [dict(row) for row in rows]
        return await self._run(op)

    # --------------------------------------------------------------- memories
    async def embed(self, text: str) -> list[float]:
        if self._embedder_fn is not None:
            try:
                vector = await self._embedder_fn(text)
                if vector:
                    return vector
            except Exception as exc:  # noqa: BLE001 — fall back quietly
                logger.debug("async embedder failed, using hashing: %s", exc)
        return self._hashing.embed(text)

    async def remember(self, text: str, kind: str = "note",
                       key: str | None = None, meta: dict | None = None) -> int:
        vector = await self.embed(text)
        def op(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO memories (created_at, kind, key, text, embedding, meta) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_now_iso(), kind, key, text[:8000], _pack(vector),
                 json.dumps(meta) if meta else None))
            conn.commit()
            return int(cursor.lastrowid)
        return await self._run(op)

    async def recall(self, query: str, k: int | None = None) -> list[MemoryHit]:
        k = k or self.recall_k
        query_vec = await self.embed(query)
        def op(conn: sqlite3.Connection) -> list[MemoryHit]:
            rows = conn.execute(
                "SELECT id, kind, key, text, embedding, created_at FROM memories "
                "ORDER BY id DESC LIMIT 5000").fetchall()
            hits: list[MemoryHit] = []
            for row in rows:
                blob = row["embedding"]
                if not blob:
                    continue
                stored = _unpack(bytes(blob))
                if len(stored) != len(query_vec):
                    continue  # embedder changed between writes
                score = sum(a * b for a, b in zip(query_vec, stored))
                hits.append(MemoryHit(id=row["id"], kind=row["kind"],
                                      key=row["key"], text=row["text"],
                                      score=score, created_at=row["created_at"]))
            hits.sort(key=lambda h: h.score, reverse=True)
            return hits[:k]
        return await self._run(op)

    # ------------------------------------------------------------------ tasks
    async def submit_task(self, goal: str, source: str,
                          priority: int = 5, interval_seconds: int | None = None,
                          daily_at: str | None = None) -> int:
        next_run = time.time()
        if daily_at:
            next_run = _next_daily(daily_at)
        def op(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO tasks (created_at, updated_at, source, goal, "
                "priority, interval_seconds, daily_at, next_run_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                (_now_iso(), _now_iso(), source, goal[:2000], priority,
                 interval_seconds, daily_at, next_run))
            conn.commit()
            return int(cursor.lastrowid)
        return await self._run(op)

    async def due_tasks(self, now: float | None = None, limit: int = 10) -> list[dict]:
        def op(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE enabled = 1 AND status = 'pending' "
                "AND next_run_at <= ? ORDER BY priority ASC, next_run_at ASC "
                "LIMIT ?", (now or time.time(), limit)).fetchall()
            return [dict(row) for row in rows]
        return await self._run(op)

    async def mark_task_running(self, task_id: int) -> bool:
        def op(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'running', updated_at = ?, "
                "last_run_at = ? WHERE id = ? AND status = 'pending'",
                (_now_iso(), time.time(), task_id))
            conn.commit()
            return cursor.rowcount > 0
        return await self._run(op)

    async def finish_task(self, task_id: int, success: bool,
                          max_failures: int = 3) -> None:
        row = (await self.list_tasks(task_id=task_id) or [None])[0]
        next_run = row.get("next_run_at") if row else None
        if row and row.get("interval_seconds"):
            next_run = time.time() + row["interval_seconds"]
        elif row and row.get("daily_at"):
            next_run = _next_daily(row["daily_at"])
        failures = 0 if success else ((row or {}).get("consecutive_failures", 0) or 0) + 1
        enabled = 0 if (not success and failures >= max_failures
                        and row and row.get("interval_seconds")) else 1

        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE tasks SET next_run_at = ?, consecutive_failures = ?, "
                "last_status = ?, enabled = ?, updated_at = ? WHERE id = ?",
                (next_run if next_run is not None else time.time(), failures,
                 "done" if success else "failed", enabled, _now_iso(), task_id))
            conn.commit()
        await self._run(op)

    async def reset_stale_running(self) -> int:
        """At boot, put 'running' tasks (crashed daemon) back to pending."""
        def op(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'pending', updated_at = ? "
                "WHERE status = 'running'", (_now_iso(),))
            conn.commit()
            return cursor.rowcount
        return await self._run(op)

    async def list_tasks(self, task_id: int | None = None,
                         limit: int = 50) -> list[dict]:
        def op(conn: sqlite3.Connection) -> list[dict]:
            if task_id is not None:
                rows = conn.execute("SELECT * FROM tasks WHERE id = ?",
                                    (task_id,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY enabled DESC, priority ASC, "
                    "id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]
        return await self._run(op)

    async def cancel_task(self, task_id: int) -> bool:
        def op(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "UPDATE tasks SET enabled = 0, status = 'cancelled', "
                "updated_at = ? WHERE id = ? AND enabled = 1",
                (_now_iso(), task_id))
            conn.commit()
            return cursor.rowcount > 0
        return await self._run(op)

    async def pause_resume(self, task_id: int, enabled: bool) -> bool:
        def op(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "UPDATE tasks SET enabled = ?, status = ?, updated_at = ? "
                "WHERE id = ?",
                (1 if enabled else 0, "pending" if enabled else "paused",
                 _now_iso(), task_id))
            conn.commit()
            return cursor.rowcount > 0
        return await self._run(op)

    # ------------------------------------------------------------------ audit
    async def audit(self, actor: str, action: str, detail: str | None) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO audit (created_at, actor, action, detail) "
                "VALUES (?, ?, ?, ?)",
                (_now_iso(), actor, action, (detail or "")[:2000]))
            conn.commit()
        await self._run(op)

    async def recent_audit(self, limit: int = 100) -> list[dict]:
        def op(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
            return [dict(row) for row in rows]
        return await self._run(op)

    # ------------------------------------------------------------ maintenance
    async def housekeeping(self) -> dict[str, int]:
        cutoff = (datetime.now() - timedelta(days=self.retention_days)
                  ).isoformat(timespec="seconds")
        def op(conn: sqlite3.Connection) -> dict[str, int]:
            cur1 = conn.execute("DELETE FROM steps WHERE created_at < ?",
                                (cutoff,))
            cur2 = conn.execute("DELETE FROM episodes WHERE created_at < ? "
                                "AND status != 'running'", (cutoff,))
            conn.commit()
            return {"steps_pruned": cur1.rowcount,
                    "episodes_pruned": cur2.rowcount}
        return await self._run(op)


def _next_daily(hhmm: str, now: datetime | None = None) -> float:
    """Unix time of the next occurrence of ``HH:MM`` local time."""
    try:
        hour_s, minute_s = hhmm.strip().split(":")
        hour, minute = int(hour_s), int(minute_s)
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError(f"invalid daily_at {hhmm!r} (expected HH:MM)")
    now = now or datetime.now()
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.timestamp()
