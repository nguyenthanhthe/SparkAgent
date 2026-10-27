"""Snippet extraction with matched-term highlighting.

Recall results arrive as long texts; a short excerpt with the query
terms marked gives the reader (human or agent) an at-a-glance reason
for the hit. Deterministic, no LLM: pick the window with the most
distinct query-term matches, wrap matches in ``**`` (markdown bold).
"""

from __future__ import annotations

from memory_search.bm25 import tokenize

MARK = "**"
_WINDOW = 220


def _lower_terms(query: str) -> set[str]:
    return {t.lower() for t in tokenize(query)}


def _mark_terms(text: str, terms: set[str]) -> str:
    if not terms:
        return text
    out: list[str] = []
    for word in text.split():
        bare = word.strip(".,;:!?()[]{}\"'").lower()
        if bare in terms:
            out.append(MARK + word + MARK)
        else:
            out.append(word)
    return " ".join(out)


def highlight_snippet(text: str, query: str, width: int = _WINDOW) -> str:
    """Shortest interesting window of ``text`` around the densest match
    of ``query`` terms, with matches wrapped in ``**``. Falls back to
    the head of the text when nothing matches."""
    text = " ".join(text.split())
    terms = _lower_terms(query)
    if not text:
        return ""
    words = text.split()
    if not terms:
        window = words
        start = 0
    else:
        best_start, best_hits = 0, -1
        window_size = max(12, width // 7)   # ~words per window
        for start in range(0, max(1, len(words) - window_size + 1)):
            chunk = words[start:start + window_size]
            hits = len({w.strip(".,;:!?()[]{}\"'").lower()
                        for w in chunk} & terms)
            if hits > best_hits:
                best_start, best_hits = start, hits
        start = best_start
        window = words[start:start + window_size]
    snippet = _mark_terms(" ".join(window), terms)
    more = start + len(window) < len(words)
    snippet = ("…" if start > 0 else "") + snippet[:width + 16]
    if more:
        snippet += "…"
    return snippet
