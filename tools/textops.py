"""Text operations for the agent: slugs, frequencies, pattern extraction."""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9']+")
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ISO_DATE_RE = re.compile(
    r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?\b")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def slugify(text: str, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length].rstrip("-") or "item"


def word_frequencies(text: str, top: int = 20,
                     stopwords: set[str] | None = None) -> list[tuple[str, int]]:
    stop = stopwords if stopwords is not None else DEFAULT_STOPWORDS
    words = [w.lower() for w in _WORD_RE.findall(text)]
    meaningful = [w for w in words if w not in stop and len(w) > 2]
    return Counter(meaningful).most_common(top)


DEFAULT_STOPWORDS: set[str] = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "her",
    "was", "one", "our", "out", "his", "has", "have", "this", "that",
    "with", "from", "they", "will", "would", "there", "their", "what",
    "about", "which", "when", "your", "into", "than", "then", "them",
    "these", "some", "could", "other", "over", "just", "also", "after",
    "very", "much", "being", "made", "more", "most", "such", "each",
}


def extract_urls(text: str) -> list[str]:
    return _URL_RE.findall(text)


def extract_emails(text: str) -> list[str]:
    return _EMAIL_RE.findall(text)


def extract_numbers(text: str) -> list[float]:
    return [float(match) for match in _NUMBER_RE.findall(text)]


def extract_dates(text: str) -> list[str]:
    return [match.group(0) for match in _ISO_DATE_RE.finditer(text)]


def domains_of(urls: list[str]) -> list[str]:
    domains = []
    for url in urls:
        try:
            domain = urlparse(url).netloc
            if domain:
                domains.append(domain)
        except ValueError:
            continue
    return domains


def truncate_middle(text: str, limit: int, marker: str = "…") -> str:
    if len(text) <= limit:
        return text
    keep = limit - len(marker)
    head, tail = keep // 2, keep - keep // 2
    return text[:head] + marker + text[len(text) - tail:]


def line_summary(text: str) -> dict:
    lines = text.splitlines() or [""]
    non_empty = [line for line in lines if line.strip()]
    return {"lines": len(lines), "non_empty_lines": len(non_empty),
            "chars": len(text), "words": len(text.split()),
            "longest_line": max((len(line) for line in lines), default=0)}


def dedupe_preserve_order(items: list) -> list:
    seen = set()
    result = []
    for item in items:
        marker = item if isinstance(item, (int, float, bool, str,
                                           tuple)) else str(item)
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result
