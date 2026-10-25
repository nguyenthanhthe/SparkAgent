"""Topology catalog with mermaid diagrams — makes the swarm's composition
shapes inspectable from the API and docs without reading source.

Each entry pairs the topology's coordination description with a mermaid
flowchart a dashboard or markdown page can render directly.
"""

from __future__ import annotations

CATALOG: list[dict[str, str]] = [
    {
        "name": "sequential",
        "description": "Pipeline: each stage's output feeds the next "
                       "stage as context.",
        "mermaid": "flowchart LR\n"
                   "    G((goal)) --> S1[stage 1]\n"
                   "    S1 --> S2[stage 2]\n"
                   "    S2 --> S3[stage N]\n"
                   "    S3 --> O((output))",
    },
    {
        "name": "parallel",
        "description": "Fan-out: workers answer the same input, a merge "
                       "function folds the replies.",
        "mermaid": "flowchart TD\n"
                   "    G((goal)) --> W1[worker 1]\n"
                   "    G --> W2[worker 2]\n"
                   "    G --> W3[worker N]\n"
                   "    W1 --> M[merge]\n"
                   "    W2 --> M\n"
                   "    W3 --> M\n"
                   "    M --> O((output))",
    },
    {
        "name": "star",
        "description": "Hub-and-spoke: the hub routes, spokes answer, "
                       "the hub aggregates.",
        "mermaid": "flowchart TD\n"
                   "    H{{hub}} -->|route| W1[spoke 1]\n"
                   "    H -->|route| W2[spoke 2]\n"
                   "    H -->|route| W3[spoke N]\n"
                   "    W1 -->|reply| H\n"
                   "    W2 -->|reply| H\n"
                   "    W3 -->|reply| H\n"
                   "    H --> O((aggregate))",
    },
    {
        "name": "debate",
        "description": "Adversarial: alternating proponent/opponent "
                       "rounds, then a fair settlement.",
        "mermaid": "flowchart TD\n"
                   "    G((goal)) --> P[proponent]\n"
                   "    P -->|pro| O[opponent]\n"
                   "    O -->|con| P\n"
                   "    P -->|pro| O\n"
                   "    O --> J[judge]\n"
                   "    J --> R((verdict))",
    },
    {
        "name": "map_reduce",
        "description": "Mapper over each item, reducer folds mapped "
                       "outputs into one answer.",
        "mermaid": "flowchart TD\n"
                   "    G((items)) --> M1[mapper item 1]\n"
                   "    G --> M2[mapper item 2]\n"
                   "    G --> M3[mapper item N]\n"
                   "    M1 --> R[reducer]\n"
                   "    M2 --> R\n"
                   "    M3 --> R\n"
                   "    R --> O((output))",
    },
]

_BY_NAME = {entry["name"]: entry for entry in CATALOG}


def topology_catalog() -> list[dict[str, str]]:
    """Fresh copies of all topology entries (callers may mutate)."""
    return [dict(entry) for entry in CATALOG]


def topology_mermaid(name: str) -> str | None:
    """Mermaid flowchart for a topology, or None if unknown."""
    entry = _BY_NAME.get(name)
    return entry["mermaid"] if entry else None


def markdown_section() -> str:
    """The catalog as a docs section (kept in sync by a staleness test)."""
    lines = ["## Topology catalog", "",
             "Served as JSON (with these diagrams) at `GET /api/swarm`.",
             ""]
    for entry in CATALOG:
        lines.append(f"### `{entry['name']}`")
        lines.append("")
        lines.append(entry["description"])
        lines.append("")
        lines.append("```mermaid")
        lines.append(entry["mermaid"])
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
