"""JSON inspection and querying for agent tool output."""

from __future__ import annotations

import json
from typing import Any


def parse(text: str) -> Any:
    return json.loads(text)


def get_path(data: Any, path: str) -> Any:
    """Dotted path with list indices: ``items.0.name`` -> data["items"][0]["name"]."""
    node = data
    for segment in _split_path(path):
        if isinstance(node, dict):
            if segment not in node:
                raise KeyError(f"key {segment!r} not found at {path!r}")
            node = node[segment]
        elif isinstance(node, list):
            try:
                index = int(segment)
            except ValueError as exc:
                raise KeyError(f"list index expected, got {segment!r} "
                               f"at {path!r}") from exc
            if not -len(node) <= index < len(node):
                raise IndexError(f"index {index} out of range at {path!r}")
            node = node[index]
        else:
            raise TypeError(f"cannot descend into "
                            f"{type(node).__name__} at {path!r}")
    return node


def _split_path(path: str) -> list[str]:
    return [segment for segment in path.split(".") if segment]


def search(data: Any, needle: str, *, in_keys: bool = True,
           in_values: bool = True) -> list[str]:
    """Return dotted paths whose key or value contains ``needle``."""
    hits: list[str] = []

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{prefix}.{key}" if prefix else str(key)
                if in_keys and needle.lower() in str(key).lower():
                    hits.append(here)
                if isinstance(value, str) and in_values and \
                        needle.lower() in value.lower():
                    if not (in_keys and needle.lower() in str(key).lower()):
                        hits.append(here)
                walk(value, here)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{prefix}.{index}" if prefix else str(index))

    walk(data, "")
    return hits


def shape(data: Any, depth: int = 0, max_depth: int = 4) -> Any:
    """Summarize structure: dicts -> key/type map, lists -> length + first."""
    if depth >= max_depth:
        return "…"
    if isinstance(data, dict):
        return {str(key): shape(value, depth + 1, max_depth)
                for key, value in list(data.items())[:20]}
    if isinstance(data, list):
        if not data:
            return "[]"
        return {"__len__": len(data), "first": shape(data[0], depth + 1,
                                                     max_depth)}
    return type(data).__name__


def stats(data: Any) -> dict:
    return {"root_type": type(data).__name__,
            "dict_keys": len(data) if isinstance(data, dict) else None,
            "list_len": len(data) if isinstance(data, list) else None,
            "leaf_count": _leaf_count(data)}


def _leaf_count(node: Any) -> int:
    if isinstance(node, dict):
        return sum(_leaf_count(v) for v in node.values())
    if isinstance(node, list):
        return sum(_leaf_count(v) for v in node)
    return 1


def safe_dump(data: Any, indent: int | None = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent, default=str)
