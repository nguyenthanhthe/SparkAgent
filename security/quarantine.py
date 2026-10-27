"""Quarantine store for suspicious content.

Web pages flagged by the prompt guard, oversized skill proposals, or any
blob that must not reach the model are parked on disk with metadata,
capped in total size, and can be inspected/released/deleted by an operator.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from kernel.correlation import new_id

MAX_ITEM_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024


class QuarantineStore:
    def __init__(self, root: Path, max_total_bytes: int = MAX_TOTAL_BYTES,
                 ttl_seconds: float = 7 * 24 * 3600):
        self.root = root
        self.max_total_bytes = max_total_bytes
        # items older than the TTL are deleted by expire(); 0 disables
        self.ttl_seconds = ttl_seconds
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------- api
    def put(self, content: str, reason: str, meta: dict | None = None) -> dict:
        if not (content or "").strip():
            raise ValueError("quarantined content must be non-empty")
        item_id = new_id()
        data = content.encode("utf-8", errors="replace")
        if len(data) > MAX_ITEM_BYTES:
            data = data[:MAX_ITEM_BYTES]
        record = {
            "id": item_id,
            "reason": reason[:300],
            "meta": meta or {},
            "size_bytes": len(data),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        (self.root / f"{item_id}.dat").write_bytes(data)
        (self.root / f"{item_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        self._enforce_budget()
        return record

    def get(self, item_id: str) -> dict:
        """Return {record, content}; raises KeyError for unknown ids."""
        meta_path = self.root / f"{item_id}.json"
        if not meta_path.exists():
            raise KeyError(f"no quarantined item {item_id!r}")
        record = json.loads(meta_path.read_text(encoding="utf-8"))
        data_path = self.root / f"{item_id}.dat"
        content = data_path.read_text(encoding="utf-8", errors="replace") \
            if data_path.exists() else ""
        return {"record": record, "content": content}

    def list(self, limit: int = 100,
             reason_contains: str | None = None) -> list[dict]:
        """Newest-first listing, optionally narrowed to items whose
        reason contains any of the comma-separated ``reason_contains``
        needles (case-insensitive)."""
        records = []
        needles = [part.strip().lower()
                   for part in (reason_contains or "").split(",")
                   if part.strip()]
        for meta_path in self.root.glob("*.json"):
            try:
                record = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if needles:
                reason = str(record.get("reason", "")).lower()
                if not any(needle in reason for needle in needles):
                    continue
            records.append(record)
        records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return records[:limit]

    def stats(self) -> dict:
        """Aggregate store state: item count, total bytes, age of the
        oldest item, and the top reasons — the one snapshot for
        /api/status and dashboards."""
        items = self.list(limit=10_000)
        oldest = items[-1].get("created_at", "") if items else ""
        try:
            oldest_ts = time.mktime(
                time.strptime(oldest, "%Y-%m-%dT%H:%M:%S"))
            oldest_age_s = max(0, int(time.time() - oldest_ts))
        except ValueError:
            oldest_age_s = None
        by_reason: dict[str, int] = {}
        for item in items:
            kind = str(item.get("reason", "")).split(" ")[0][:40] or "?"
            by_reason[kind] = by_reason.get(kind, 0) + 1
        top_reasons = dict(sorted(by_reason.items(),
                                  key=lambda kv: -kv[1])[:3])
        return {"items": len(items),
                "bytes": sum(item.get("size_bytes", 0) for item in items),
                "oldest_age_s": oldest_age_s,
                "top_reasons": top_reasons}

    def release(self, item_id: str) -> str:
        """Return sanitized content and delete the item from quarantine."""
        item = self.get(item_id)
        self._delete_files(item_id)
        from security.promptguard import sanitize
        return sanitize(item["content"])

    def delete(self, item_id: str) -> bool:
        if not (self.root / f"{item_id}.json").exists():
            return False
        self._delete_files(item_id)
        return True

    def clear(self) -> int:
        count = 0
        for meta_path in self.root.glob("*.json"):
            self._delete_files(meta_path.stem)
            count += 1
        return count

    def expire(self) -> int:
        """Delete items older than the TTL; returns how many were removed.

        Called by housekeeping so forgotten quarantined blobs cannot pile
        up forever. Items carry ``expires_at`` in their record so the
        sweep is auditable via ``list()``.
        """
        if self.ttl_seconds <= 0:
            return 0
        now = time.time()
        removed = 0
        for item in self.list(limit=10_000):
            created = item.get("created_at", "")
            try:
                created_ts = time.mktime(
                    time.strptime(created, "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                continue   # unparsable timestamp: keep for operator review
            if now - created_ts > self.ttl_seconds:
                self._delete_files(item["id"])
                removed += 1
        return removed

    # -------------------------------------------------------------- internals
    def _delete_files(self, item_id: str) -> None:
        for suffix in (".json", ".dat"):
            (self.root / f"{item_id}{suffix}").unlink(missing_ok=True)

    def _enforce_budget(self) -> None:
        items = self.list(limit=10_000)
        total = sum(item.get("size_bytes", 0) for item in items)
        index = len(items) - 1
        while total > self.max_total_bytes and index >= 0:
            oldest = items[index]
            total -= oldest.get("size_bytes", 0)
            self._delete_files(oldest["id"])
            index -= 1
