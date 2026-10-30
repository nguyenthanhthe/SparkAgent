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
    depends_on TEXT,
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
    tags: list[str] | None = None   # episode tags for episode-linked hits
    snippet: str | None = None      # excerpt with matched terms marked


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
        self.last_recall_pool_size: int | None = None
        self.retention_days = retention_days
        self.graph_store = None   # optional GraphStore for graph-boosted recall
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
        self._migrate()
        self._conn.commit()
        logger.info("memory open: %s", self.db_path)

    def _migrate(self) -> None:
        """Idempotent lightweight migrations (additive columns only)."""
        existing = {row["name"] for row in self._conn.execute(
            "PRAGMA table_info(episodes)")}
        if "tags" not in existing:
            self._conn.execute(
                "ALTER TABLE episodes ADD COLUMN tags TEXT DEFAULT '[]'")
            logger.info("migration: added episodes.tags")
        task_cols = {row["name"] for row in self._conn.execute(
            "PRAGMA table_info(tasks)")}
        if "depends_on" not in task_cols:
            self._conn.execute(
                "ALTER TABLE tasks ADD COLUMN depends_on TEXT")
            logger.info("migration: added tasks.depends_on")

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
        tags = extract_tags(goal)

        def op(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO episodes (created_at, source, goal, status, "
                "tags) VALUES (?, ?, ?, 'running', ?)",
                (_now_iso(), source, goal[:2000], json.dumps(tags)))
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

    async def recent_episodes(self, limit: int = 20,
                              tag: str | None = None) -> list[dict]:
        """Newest episodes; ``tag`` filters on the episodes' tag list."""
        wanted = (tag or "").lower().lstrip("#")

        def op(conn: sqlite3.Connection) -> list[dict]:
            if wanted:
                rows = conn.execute(
                    "SELECT id, created_at, source, goal, status, "
                    "final_answer, model_tier, steps, tags FROM episodes "
                    "WHERE tags LIKE ? ORDER BY id DESC LIMIT ?",
                    (f'%"{wanted}"%', limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, created_at, source, goal, status, "
                    "final_answer, model_tier, steps, tags FROM episodes "
                    "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                try:
                    item["tags"] = json.loads(item.get("tags") or "[]")
                except json.JSONDecodeError:
                    item["tags"] = []
                results.append(item)
            return results
        return await self._run(op)

    async def episode_detail(self, episode_id: int) -> dict | None:
        """Full episode record plus its ordered step replay."""
        def op(conn: sqlite3.Connection) -> dict | None:
            row = conn.execute(
                "SELECT id, created_at, source, goal, status, final_answer, "
                "model_tier, steps FROM episodes WHERE id = ?",
                (episode_id,)).fetchone()
            if row is None:
                return None
            detail = dict(row)
            steps = conn.execute(
                "SELECT idx, kind, content, created_at FROM steps "
                "WHERE episode_id = ? ORDER BY idx", (episode_id,)).fetchall()
            detail["step_log"] = [dict(step) for step in steps]
            detail["step_count"] = len(detail["step_log"])
            return detail
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
                       key: str | None = None, meta: dict | None = None,
                       with_stamp: bool = False):
        """Store a memory; returns the row id (default) or, with
        ``with_stamp=True``, a dict carrying the exact ``created_at``
        stamp that was persisted — callers no longer guess the stamp
        from the clock."""
        if not (text or "").strip():
            raise ValueError("memory text must be non-empty")
        vector = await self.embed(text)
        created_at = _now_iso()

        def op(conn: sqlite3.Connection):
            cursor = conn.execute(
                "INSERT INTO memories (created_at, kind, key, text, embedding, meta) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (created_at, kind, key, text[:8000], _pack(vector),
                 json.dumps(meta) if meta else None))
            conn.commit()
            if with_stamp:
                return {"id": int(cursor.lastrowid),
                        "created_at": created_at}
            return int(cursor.lastrowid)
        return await self._run(op)

    async def recall(self, query: str, k: int | None = None,
                     kinds: list[str] | None = None,
                     exclude_kinds: list[str] | None = None,
                     created_after: str | None = None,
                     ids: list[int] | None = None,
                     snippet_width: int = 220,
                     highlight: str | None = None) -> list[MemoryHit]:
        """Hybrid recall: cosine vectors fused with BM25 lexical matches.

        ``kinds`` optionally restricts results (e.g. ``["digest",
        "episode"]``); ``exclude_kinds`` is the complement — drop those
        kinds (e.g. ``["note"]``) from the candidate pool.
        ``created_after`` keeps only rows stamped after the given
        ``YYYY-MM-DD[THH:MM:SS]`` instant; ``ids`` pins the candidate
        pool to explicit row ids (direct re-ranking lookups).
        Filtering happens in SQL, parameter-bound. Digest markers stay
        excluded unless explicitly asked for via ``kinds``.
        """
        # an explicit k=0 is honored (pool probe: scan happens, the
        # pool size lands in last_recall_pool_size, no hits returned);
        # only None falls back to the default
        k = self.recall_k if k is None else k
        query_vec = await self.embed(query)

        def op(conn: sqlite3.Connection) -> list[MemoryHit]:
            # the SQL text is static; the only dynamic part is the count
            # of '?' placeholder tokens, and every value rides bound
            if kinds:
                sql = ("SELECT id, kind, key, text, embedding, created_at "
                       "FROM memories WHERE kind IN ("
                       + ", ".join("?" * len(kinds)) + ") ")
                params: list = list(kinds)
            else:
                # digest markers are bookkeeping, not knowledge — exclude
                # unless the caller asks for them by kind
                sql = ("SELECT id, kind, key, text, embedding, created_at "
                       "FROM memories WHERE kind != 'digest-marker' ")
                params = []
            if exclude_kinds:
                sql += ("AND kind NOT IN ("
                        + ", ".join("?" * len(exclude_kinds)) + ") ")
                params.extend(exclude_kinds)
            if created_after:
                # created_at is ISO local time; a date-only bound
                # compares lexicographically against the zero time
                raw = created_after.strip()
                probe = raw if "T" in raw else raw + "T00:00:00"
                try:
                    time.strptime(probe, "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    raise ValueError(
                        "created_after must be YYYY-MM-DD or "
                        "YYYY-MM-DDTHH:MM:SS, got "
                        f"{created_after!r}") from None
                sql += "AND created_at > ? "
                params.append(probe)
            if ids:
                sql += ("AND id IN ("
                        + ", ".join("?" * len(ids)) + ") ")
                params.extend(int(i) for i in ids)
            rows = conn.execute(sql + "ORDER BY id DESC LIMIT 5000",
                                tuple(params)).fetchall()
            # candidate-pool size, exposed for recall tuning (why did
            # my kind filter return nothing? how wide was the scan?)
            self.last_recall_pool_size = len(rows)
            from memory_search.hybrid import HybridRanker
            ranker = HybridRanker(recency_weight=0.0)
            vector_by_id: dict[str, tuple[str, float]] = {}
            for row in rows:
                blob = row["embedding"]
                stored = None
                if blob:
                    values = _unpack(bytes(blob))
                    if len(values) == len(query_vec):
                        stored = sum(a * b for a, b in zip(query_vec, values))
                doc_id = str(row["id"])
                ranker.add(doc_id, row["text"],
                           metadata={"kind": row["kind"], "key": row["key"],
                                     "created_at": row["created_at"],
                                     "score": stored})
                if stored is not None:
                    vector_by_id[doc_id] = (row["text"], stored)
            hits: list[MemoryHit] = []
            for hit in ranker.search(query, top=k):
                row_meta = hit.metadata
                hits.append(MemoryHit(
                    id=int(hit.doc_id), kind=row_meta.get("kind", "note"),
                    key=row_meta.get("key"), text=hit.text,
                    score=hit.fused_score + (vector_by_id.get(hit.doc_id,
                                                              ("", 0.0))[1]
                                             or 0.0),
                    created_at=row_meta.get("created_at", "")))
            hits.sort(key=lambda h: h.score, reverse=True)
            if self.graph_store is not None:
                from memory_search.graph_boost import GraphBooster
                booster = GraphBooster(self.graph_store)
                for hit in hits:
                    hit.score += booster.boost(query, hit.text)
                hits.sort(key=lambda h: h.score, reverse=True)
            # same key can reach the ranker twice (episode-linked rows);
            # keep only the best-scoring hit per key so recall pages
            # don't waste slots on duplicates
            deduped: dict[str, MemoryHit] = {}
            for hit in hits:
                key = hit.key if hit.key is not None else f"__id:{hit.id}"
                if key not in deduped or hit.score > deduped[key].score:
                    deduped[key] = hit
            hits = list(deduped.values())[:k]
            self._attach_episode_tags(conn, hits)
            if snippet_width > 0:
                from memory_search.snippets import highlight_snippet
                for hit in hits:
                    hit.snippet = highlight_snippet(
                        hit.text, highlight or query, width=snippet_width)
            # snippet_width <= 0 skips the windowing entirely — callers
            # that only need ids/scores pay no snippet cost
            return hits
        return await self._run(op)

    @staticmethod
    def _attach_episode_tags(conn: sqlite3.Connection,
                             hits: list[MemoryHit]) -> None:
        """Fill ``tags`` for hits whose key links an episode
        (``episode:<id>``) — one bounded query, JSON-parsed."""
        ids = []
        for hit in hits:
            if hit.key and hit.key.startswith("episode:"):
                try:
                    ids.append(int(hit.key.split(":", 1)[1]))
                except ValueError:
                    continue
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, tags FROM episodes WHERE id IN ({placeholders})",
            tuple(ids)).fetchall()
        tags_by_id: dict[int, list[str]] = {}
        for row in rows:
            try:
                tags_by_id[int(row["id"])] = json.loads(row["tags"] or "[]")
            except (json.JSONDecodeError, ValueError, TypeError):
                tags_by_id[int(row["id"])] = []
        for hit in hits:
            if hit.key and hit.key.startswith("episode:"):
                try:
                    hit.tags = tags_by_id.get(int(hit.key.split(":", 1)[1]),
                                              [])
                except ValueError:
                    pass

    # ------------------------------------------------------------------ tasks
    @staticmethod
    def _parse_depends(raw: str | None) -> list[int]:
        """Parse a ``depends_on`` JSON column into a list of task ids."""
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            return []
        if not isinstance(value, list):
            return []
        return [int(v) for v in value if isinstance(v, (int, float))]

    async def submit_task(self, goal: str, source: str,
                          priority: int = 5, interval_seconds: int | None = None,
                          daily_at: str | None = None,
                          depends_on: list[int] | None = None) -> int:
        next_run = time.time()
        if daily_at:
            next_run = _next_daily(daily_at)
        deps_json: str | None = None
        if depends_on:
            deps = sorted({int(d) for d in depends_on if int(d) > 0})
            if not deps:
                raise ValueError("depends_on must contain positive task ids")

            def check(conn: sqlite3.Connection) -> None:
                # walk the full transitive closure: the new task must not
                # join (or hang off) a dependency cycle — a stuck chain is
                # invisible until someone wonders why nothing runs
                frontier = list(deps)
                graph: dict[int, list[int]] = {}
                seen: set[int] = set()
                while frontier:
                    placeholders = ", ".join("?" for _ in frontier)
                    rows = conn.execute(
                        f"SELECT id, depends_on FROM tasks "
                        f"WHERE id IN ({placeholders})",
                        tuple(frontier)).fetchall()
                    missing = sorted(set(frontier)
                                     - {row["id"] for row in rows})
                    if missing:
                        raise ValueError(
                            f"unknown dependency task id(s): {missing}")
                    nxt: list[int] = []
                    for row in rows:
                        edges = self._parse_depends(row["depends_on"])
                        graph[row["id"]] = edges
                        if row["id"] in seen:
                            continue
                        seen.add(row["id"])
                        nxt.extend(d for d in edges if d not in seen)
                    frontier = nxt
                graph[_NEW_TASK_NODE] = deps   # sentinel: the task to create
                cycle = find_cycle(graph)
                if cycle:
                    raise ValueError(
                        "dependency cycle detected: "
                        + " -> ".join(str(node) for node in cycle))
            await self._run(check)
            deps_json = json.dumps(deps)

        def op(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO tasks (created_at, updated_at, source, goal, "
                "priority, interval_seconds, daily_at, depends_on, "
                "next_run_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                (_now_iso(), _now_iso(), source, goal[:2000], priority,
                 interval_seconds, daily_at, deps_json, next_run))
            conn.commit()
            return int(cursor.lastrowid)
        return await self._run(op)

    async def due_tasks(self, now: float | None = None,
                        limit: int = 10) -> list[dict]:
        def op(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE enabled = 1 AND status = 'pending' "
                "AND next_run_at <= ? ORDER BY priority ASC, next_run_at ASC "
                "LIMIT ?", (now or time.time(), limit * 3)).fetchall()
            # dependency gate: a task runs only when every depends_on task
            # has settled to 'done' (failed deps block forever until retried)
            dep_ids: set[int] = set()
            parsed: dict[int, list[int]] = {}
            for row in rows:
                deps = self._parse_depends(row["depends_on"])
                if deps:
                    parsed[row["id"]] = deps
                    dep_ids.update(deps)
            if not parsed:
                return [dict(row) for row in rows[:limit]]
            placeholders = ", ".join("?" for _ in dep_ids)
            done = {row["id"] for row in conn.execute(
                f"SELECT id FROM tasks WHERE id IN ({placeholders}) "
                f"AND status = 'done'", tuple(dep_ids))}
            ready: list[dict] = []
            for row in rows:
                deps = parsed.get(row["id"])
                if deps is None or all(d in done for d in deps):
                    ready.append(dict(row))
                    if len(ready) >= limit:
                        break
            return ready
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
            recurring = bool(row and (row.get("interval_seconds")
                                      or row.get("daily_at")))
            # recurring tasks re-arm as pending (next_run_at drives them);
            # one-shots settle to done/failed (retry_one_shot can re-arm)
            status = "pending" if recurring else \
                ("done" if success else "failed")
            conn.execute(
                "UPDATE tasks SET next_run_at = ?, consecutive_failures = ?, "
                "last_status = ?, enabled = ?, status = ?, updated_at = ? "
                "WHERE id = ?",
                (next_run if next_run is not None else time.time(), failures,
                 "done" if success else "failed", enabled, status,
                 _now_iso(), task_id))
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
                         limit: int = 50,
                         status: str | None = None) -> list[dict]:
        def op(conn: sqlite3.Connection) -> list[dict]:
            if task_id is not None:
                rows = conn.execute("SELECT * FROM tasks WHERE id = ?",
                                    (task_id,)).fetchall()
            elif status is not None:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status = ? "
                    "ORDER BY enabled DESC, priority ASC, id DESC LIMIT ?",
                    (status, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY enabled DESC, priority ASC, "
                    "id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]
        return await self._run(op)

    async def retry_one_shot(self, task_id: int, next_run_at: float) -> bool:
        """Re-arm a one-shot task for a retry (status back to pending)."""
        def op(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "UPDATE tasks SET status = 'pending', next_run_at = ?, "
                "updated_at = ? WHERE id = ? AND status IN "
                "('done', 'failed') AND interval_seconds IS NULL "
                "AND daily_at IS NULL",
                (next_run_at, _now_iso(), task_id))
            conn.commit()
            return cursor.rowcount > 0
        return await self._run(op)

    async def blocked_by(self, task_id: int) -> list[int]:
        """Unsatisfied dependency ids for a task (empty when runnable)."""
        def op(conn: sqlite3.Connection) -> list[int]:
            rows = conn.execute(
                "SELECT depends_on, status FROM tasks WHERE id = ?",
                (task_id,)).fetchall()
            if not rows:
                return []
            deps = self._parse_depends(rows[0]["depends_on"])
            if not deps or rows[0]["status"] == "done":
                return []
            placeholders = ", ".join("?" for _ in deps)
            done = {row["id"] for row in conn.execute(
                f"SELECT id FROM tasks WHERE id IN ({placeholders}) "
                f"AND status = 'done'", tuple(deps))}
            return [dep for dep in deps if dep not in done]
        return await self._run(op)

    async def blocked_pending_tasks(self, limit: int = 50) -> list[dict]:
        """Enabled pending tasks that are dependency-blocked, each with
        its unsatisfied dependency ids (feeds scheduler blocked/released
        events)."""
        def op(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                "SELECT id, goal, depends_on FROM tasks WHERE enabled = 1 "
                "AND status = 'pending' ORDER BY priority ASC, id ASC "
                "LIMIT ?", (limit * 3,)).fetchall()
            dep_ids: set[int] = set()
            parsed: dict[int, list[int]] = {}
            for row in rows:
                deps = self._parse_depends(row["depends_on"])
                if deps:
                    parsed[row["id"]] = deps
                    dep_ids.update(deps)
            if not parsed:
                return []
            placeholders = ", ".join("?" for _ in dep_ids)
            done = {row["id"] for row in conn.execute(
                f"SELECT id FROM tasks WHERE id IN ({placeholders}) "
                f"AND status = 'done'", tuple(dep_ids))}
            blocked = []
            for row in rows:
                deps = parsed.get(row["id"])
                if deps is None:
                    continue
                unsatisfied = [d for d in deps if d not in done]
                if unsatisfied:
                    blocked.append({"id": row["id"], "goal": row["goal"],
                                    "blocked_by": unsatisfied})
                    if len(blocked) >= limit:
                        break
            return blocked
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

    async def forget(self, key: str) -> int:
        """Delete every memory row carrying ``key`` (operator action;
        callers must audit). Returns how many rows were actually
        removed — 0 means the key was already absent, which is distinct
        from an empty key (a programming error, raised as such)."""
        if not key:
            raise ValueError("forget needs a non-empty key")

        def op(conn: sqlite3.Connection) -> int:
            cursor = conn.execute("DELETE FROM memories WHERE key = ?",
                                  (key,))
            conn.commit()
            return cursor.rowcount
        return await self._run(op)

    async def rename_key(self, old: str, new: str) -> int:
        """Re-key memories from ``old`` to ``new`` (operator repair for
        mistyped keys; callers must audit). Returns the row count.
        Refuses when ``new`` is already taken — merging keys silently
        would blur two distinct memories."""
        if not old or not new or old == new:
            raise ValueError("rename_key needs two distinct non-empty keys")

        def op(conn: sqlite3.Connection) -> int:
            taken = conn.execute("SELECT COUNT(*) AS n FROM memories "
                                 "WHERE key = ?", (new,)).fetchone()
            if int(taken["n"]) > 0:
                raise ValueError(f"key {new!r} already exists — forget it "
                                 "first if the merge is intended")
            cursor = conn.execute(
                "UPDATE memories SET key = ? WHERE key = ?", (new, old))
            conn.commit()
            return cursor.rowcount
        return await self._run(op)

    async def count(self, kind: str | None = None,
                    key_contains: str | None = None) -> int:
        """Total memory rows, optionally restricted to one kind and/or
        rows whose ``key`` contains the given substring — the cheap
        totals dashboards poll (e.g. count episode-tagged rows whose key
        carries an episode id)."""
        def op(conn: sqlite3.Connection) -> int:
            clauses, params = [], []
            if kind is not None:
                clauses.append("kind = ?")
                params.append(kind)
            if key_contains:
                clauses.append("key LIKE ?")
                params.append("%" + key_contains + "%")
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            row = conn.execute("SELECT COUNT(*) AS n FROM memories" + where,
                               tuple(params)).fetchone()
            return int(row["n"])
        return await self._run(op)

    async def digest_markers(self) -> list[dict]:
        """All digest-marker memories (``[digested] <goal>`` rows) — the
        consolidation dedupe's view of what was already distilled."""
        def op(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                "SELECT key, text FROM memories WHERE kind = "
                "'digest-marker' ORDER BY id ASC").fetchall()
            return [dict(row) for row in rows]
        return await self._run(op)

    async def recent_audit(self, limit: int = 100) -> list[dict]:
        def op(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
            return [dict(row) for row in rows]
        return await self._run(op)

    async def episodes_without_digest(self, since_iso: str,
                                      limit: int = 50) -> list[dict]:
        """Finished episodes after ``since_iso`` that have no digest memory
        keyed on their id — the consolidation job's work queue. Whitespace
        -only goals are skipped: nothing to distill."""
        def op(conn: sqlite3.Connection) -> list[dict]:
            rows = conn.execute(
                "SELECT id, goal, final_answer, tags FROM episodes "
                "WHERE status = 'done' AND created_at >= ? "
                "AND TRIM(goal) != '' "
                "AND id NOT IN (SELECT CAST(REPLACE(key, 'episode:', '') "
                "AS INTEGER) FROM memories WHERE key LIKE 'episode:%') "
                "ORDER BY id LIMIT ?", (since_iso, limit)).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                try:
                    item["tags"] = json.loads(item.get("tags") or "[]")
                except (json.JSONDecodeError, TypeError):
                    item["tags"] = []
                results.append(item)
            return results
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


_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4,
             "sat": 5, "sun": 6}

# sentinel node id standing for "the task being created" during the
# submit-time cycle walk (real ids are always positive)
_NEW_TASK_NODE = -1


def find_cycle(edges: dict[int, list[int]]) -> list[int] | None:
    """Return the first dependency cycle as a node path, or None.

    Iterative DFS over ``node -> its dependencies``; a node listed as its
    own dependency comes back as a single-element cycle. Nodes referenced
    but absent from ``edges`` are treated as leaves.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = dict.fromkeys(edges, WHITE)
    for root in edges:
        if color[root] != WHITE:
            continue
        color[root] = GRAY
        path = [root]
        stack = [(root, iter(edges[root]))]
        while stack:
            node, children = stack[-1]
            descended = False
            for child in children:
                if child not in edges:
                    continue
                state = color.get(child, WHITE)
                if state == GRAY:
                    return path[path.index(child):]
                if state == WHITE:
                    color[child] = GRAY
                    path.append(child)
                    stack.append((child, iter(edges[child])))
                    descended = True
                    break
            if not descended:
                color[node] = BLACK
                path.pop()
                stack.pop()
    return None


_TAG_RE = re.compile(r"#([a-z][a-z0-9_-]{0,31})", re.IGNORECASE)


def extract_tags(text: str, max_tags: int = 5) -> list[str]:
    """Pull #hashtags out of a goal for episode classification."""
    seen: list[str] = []
    for match in _TAG_RE.finditer(text or ""):
        tag = match.group(1).lower()
        if tag not in seen:
            seen.append(tag)
        if len(seen) >= max_tags:
            break
    return seen


def parse_daily_spec(spec: str) -> tuple[set[int], list[tuple[int, int]]]:
    """Parse a daily_at spec: ``[days@]HH:MM[,HH:MM...]``.

    Examples: ``09:00`` · ``09:00,17:30`` · ``mon-fri@09:00`` ·
    ``mon,wed,fri@08:00,20:00``. No days part means every day.
    Returns (weekday set as ints, [(hour, minute), ...]).
    """
    original = spec
    days: set[int] = set(_WEEKDAYS.values())
    if "@" in spec:
        day_part, _, time_part = spec.partition("@")
        if not day_part.strip():
            raise ValueError(f"invalid daily_at {original!r} "
                             "(empty weekday list)")
        days = set()
        for token in day_part.split(","):
            token = token.strip().lower()
            if not token:
                continue
            if "-" in token:
                start_name, _, end_name = token.partition("-")
                if start_name not in _WEEKDAYS or end_name not in _WEEKDAYS:
                    raise ValueError(f"bad weekday range {token!r}")
                start, end = _WEEKDAYS[start_name], _WEEKDAYS[end_name]
                days.update(range(min(start, end), max(start, end) + 1))
            elif token in _WEEKDAYS:
                days.add(_WEEKDAYS[token])
            else:
                raise ValueError(f"bad weekday {token!r}")
        spec = time_part
    times = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        hour_s, _, minute_s = token.partition(":")
        try:
            hour, minute = int(hour_s), int(minute_s)
        except ValueError as exc:
            raise ValueError(f"invalid daily_at {original!r} "
                             "(expected HH:MM)") from exc
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError(f"invalid daily_at time {token!r}")
        times.append((hour, minute))
    if not times:
        raise ValueError(f"invalid daily_at {original!r} (no times)")
    return days, times


def _next_daily(spec: str, now: datetime | None = None) -> float:
    """Unix time of the next occurrence of the daily spec (local time)."""
    days, times = parse_daily_spec(spec)
    now = now or datetime.now()
    for offset in range(8):                     # at most a week ahead
        candidate_day = now + timedelta(days=offset)
        if candidate_day.weekday() not in days:
            continue
        for hour, minute in sorted(times):
            candidate = candidate_day.replace(hour=hour, minute=minute,
                                              second=0, microsecond=0)
            if candidate > now:
                return candidate.timestamp()
    raise ValueError(f"unreachable daily_at spec {spec!r}")  # pragma: no cover
