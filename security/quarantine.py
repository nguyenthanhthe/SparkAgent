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
    def __init__(self, root: Path, max_total_bytes: int = MAX_TOTAL_BYTES):
        self.root = root
        self.max_total_bytes = max_total_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------- api
    def put(self, content: str, reason: str, meta: dict | None = None) -> dict:
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

    def list(self, limit: int = 100) -> list[dict]:
        records = []
        for meta_path in self.root.glob("*.json"):
            try:
                records.append(json.loads(
                    meta_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return records[:limit]

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
