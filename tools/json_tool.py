"""JSON inspection and querying for agent tool output."""

from __future__ import annotations

import json
import re
from typing import Any


def parse(text: str) -> Any:
    return json.loads(text)


def parse_jsonl(text: str) -> list[Any]:
    """Parse newline-delimited JSON; blank lines are skipped, malformed
    lines raise ValueError with the 1-based line number."""
    docs: list[Any] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            docs.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {lineno}: {exc}") from exc
    return docs


def get_path(data: Any, path: str) -> Any:
    """Dotted path with list indices and ``*`` wildcards.

    ``items.0.name`` -> data["items"][0]["name"];
    ``items.*.name`` -> every name across the list; wildcards nest
    (``a.*.b.*``) and over dicts spread values instead of elements."""
    return _descend(data, _split_path(path), path)


def _descend(node: Any, segments: list[str], full_path: str) -> Any:
    if not segments:
        return node
    segment, rest = segments[0], segments[1:]
    if segment == "*":
        if isinstance(node, dict):
            children = list(node.values())
        elif isinstance(node, list):
            children = node
        else:
            raise TypeError(f"wildcard needs a list or dict, got "
                            f"{type(node).__name__} at {full_path!r}")
        results = [_descend(child, rest, full_path) for child in children]
        if rest:
            # spread semantics: deeper wildcards/paths merge into one list
            flat: list[Any] = []
            for result in results:
                if isinstance(result, list):
                    flat.extend(result)
                else:
                    flat.append(result)
            results = flat
        return results
    if isinstance(node, dict):
        if segment not in node:
            raise KeyError(f"key {segment!r} not found at {full_path!r}")
        return _descend(node[segment], rest, full_path)
    if isinstance(node, list):
        try:
            index = int(segment)
        except ValueError as exc:
            raise KeyError(f"list index expected, got {segment!r} "
                           f"at {full_path!r}") from exc
        if not -len(node) <= index < len(node):
            raise IndexError(f"index {index} out of range at {full_path!r}")
        return _descend(node[index], rest, full_path)
    raise TypeError(f"cannot descend into "
                    f"{type(node).__name__} at {full_path!r}")


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
            "leaf_count": _leaf_count(data),
            "depth": _depth(data),
            "nesting": _nesting(data) if isinstance(data, dict) else {},
            "sample": data[0] if isinstance(data, list) and data else None}


def _depth(data: Any) -> int:
    """Longest chain of nested dict/list containers below the root
    (a scalar document has depth 0)."""
    if not isinstance(data, (dict, list)):
        return 0
    if isinstance(data, dict):
        children = data.values()
    else:
        children = data
    return 1 + max((_depth(child) for child in children), default=0)


def _nesting(data: Any, max_depth: int = 3) -> dict[str, int]:
    """Dotted prefix -> direct-child count for nested dicts, depth-capped
    and width-capped so pathological inputs stay bounded."""
    out: dict[str, int] = {}

    def walk(node: Any, prefix: str, depth: int) -> None:
        if depth > max_depth or not isinstance(node, dict):
            return
        if prefix:
            out[prefix] = len(node)
        for key, value in list(node.items())[:20]:
            walk(value, f"{prefix}.{key}" if prefix else str(key),
                 depth + 1)

    walk(data, "", 0)
    return out


def where_help() -> dict:
    """Self-describing filter reference so an agent can rediscover the
    term grammar without leaving the tool surface."""
    return {
        "terms": "key<op>value, ';' separated (up to 8 terms)",
        "operators": {"=": "equal", "!=": "not equal", ">": "greater",
                      "<": "less", ">=": "at least", "<=": "at most",
                      "~=": "contains (case-insensitive)",
                      "^=": "starts with (case-insensitive)",
                      "$=": "ends with (case-insensitive)"},
        "coercion": "numeric fields compare numerically; booleans match "
                    "1/0/true/false; everything else compares as string",
        "examples": ["age>=30", "status!=done", "name~=bob", "enabled=1",
                     "path~=.md;size>1024"],
    }


def top_keys(data: Any, prefix: str = "") -> dict[str, str]:
    """Top-level dict keys mapped to their value type names — the
    fastest way to answer 'what's in this object?'. With ``prefix``,
    only keys starting with it (case-insensitive) are returned."""
    if not isinstance(data, dict):
        return {}
    needle = prefix.lower()
    return {str(key): type(value).__name__
            for key, value in list(data.items())[:20]
            if not needle or str(key).lower().startswith(needle)}


def _leaf_count(node: Any) -> int:
    if isinstance(node, dict):
        return sum(_leaf_count(v) for v in node.values())
    if isinstance(node, list):
        return sum(_leaf_count(v) for v in node)
    return 1


def safe_dump(data: Any, indent: int | None = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent, default=str)


# --------------------------------------------------------------- row filter
_TERM_RE = re.compile(r"^\s*([\w.*\[\]-]+)\s*(>=|<=|!=|~=|\^=|\$=|>|<|=)\s*(.*?)\s*$")
_OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "~=": lambda a, b: str(b).lower() in str(a).lower(),
    "^=": lambda a, b: str(a).lower().startswith(str(b).lower()),
    "$=": lambda a, b: str(a).lower().endswith(str(b).lower()),
}
MAX_FILTER_TERMS = 8


def filter_rows(rows: list[Any], where: str) -> list[Any]:
    """Filter a list of dicts with ``;``-separated comparison terms
    (``age>=30``, ``name=alice``, ``status!=done``). Numeric comparison
    kicks in when the field value is a number; otherwise terms compare
    as strings. Rows missing the key never match."""
    terms = [term for term in (part.strip()
                               for part in where.split(";")) if term]
    if len(terms) > MAX_FILTER_TERMS:
        raise ValueError(f"at most {MAX_FILTER_TERMS} filter terms")
    for term in terms:
        match = _TERM_RE.match(term)
        if not match:
            raise ValueError(f"bad filter term {term!r} — want key>=value")
        key, op, raw = match.groups()
        rows = [row for row in rows if _matches(row, key, op, raw)]
    return rows


def _matches(row: Any, key: str, op: str, raw: str) -> bool:
    if not isinstance(row, dict):
        return False
    try:
        value = get_path(row, key)
    except (KeyError, IndexError, TypeError):
        return False
    if isinstance(value, bool):
        expected: Any = raw.strip().lower() in ("1", "true", "yes", "on")
    elif isinstance(value, (int, float)):
        try:
            expected = float(raw)
        except ValueError:
            expected = raw
    else:
        expected = raw
    try:
        return _OPS[op](value, expected)
    except TypeError:
        return False


def sort_rows(rows: list[Any], key: str, descending: bool = False) \
        -> list[Any]:
    """Order list rows by a dotted key; rows missing the key (or with
    null) sort last. Numeric ordering when every present value is a
    number, string ordering otherwise — never raises on mixed data."""
    def value_of(row: Any):
        if isinstance(row, dict):
            try:
                return get_path(row, key)
            except (KeyError, IndexError, TypeError):
                return None
        return None

    values = [value_of(row) for row in rows]
    present = [v for v in values if v is not None]
    numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                  for v in present)
    key_of = (lambda v: v) if numeric else (lambda v: str(v))
    ranked = sorted((i for i, v in enumerate(values) if v is not None),
                    key=lambda i: key_of(values[i]), reverse=descending)
    missing = [i for i, v in enumerate(values) if v is None]
    return [rows[i] for i in ranked + missing]


def first_row(rows: list[Any], where: str = "",
              last: bool = False) -> Any:
    """Head (or tail) row access, with an optional filter applied first.
    Returns None when nothing matches — the caller decides if that's an
    error."""
    if where:
        rows = filter_rows(rows, where)
    if not rows:
        return None
    return rows[-1] if last else rows[0]


def group_rows(rows: list[Any], key: str) -> dict[str, int]:
    """Count rows grouped by the value of a dotted key; rows missing the
    key count under the empty string. Values are stringified so the
    result is always JSON-safe."""
    counts: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict):
            try:
                value = get_path(row, key)
            except (KeyError, IndexError, TypeError):
                value = None
        else:
            value = None
        bucket = "" if value is None else str(value)
        counts[bucket] = counts.get(bucket, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def unique_values(rows: list[Any], key: str) -> list[str]:
    """Sorted distinct stringified values of a dotted key; rows missing
    the key contribute nothing."""
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            value = get_path(row, key)
        except (KeyError, IndexError, TypeError):
            continue
        if value is not None:
            seen.add(str(value))
    return sorted(seen)


def pluck(rows: list[Any], key: str) -> list[Any]:
    """Extract one dotted key from every row as a flat array (dict.get
    semantics: missing keys become None, order preserved)."""
    out: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(None)
            continue
        try:
            out.append(get_path(row, key))
        except (KeyError, IndexError, TypeError):
            out.append(None)
    return out
