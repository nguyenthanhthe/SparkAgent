## Topology catalog

Served as JSON (with these diagrams) at `GET /api/swarm`.

### `sequential`

Pipeline: each stage's output feeds the next stage as context.

```mermaid
flowchart LR
    G((goal)) --> S1[stage 1]
    S1 --> S2[stage 2]
    S2 --> S3[stage N]
    S3 --> O((output))
```

### `parallel`

Fan-out: workers answer the same input, a merge function folds the replies.

```mermaid
flowchart TD
    G((goal)) --> W1[worker 1]
    G --> W2[worker 2]
    G --> W3[worker N]
    W1 --> M[merge]
    W2 --> M
    W3 --> M
    M --> O((output))
```

### `star`

Hub-and-spoke: the hub routes, spokes answer, the hub aggregates.

```mermaid
flowchart TD
    H{{hub}} -->|route| W1[spoke 1]
    H -->|route| W2[spoke 2]
    H -->|route| W3[spoke N]
    W1 -->|reply| H
    W2 -->|reply| H
    W3 -->|reply| H
    H --> O((aggregate))
```

### `debate`

Adversarial: alternating proponent/opponent rounds, then a fair settlement.

```mermaid
flowchart TD
    G((goal)) --> P[proponent]
    P -->|pro| O[opponent]
    O -->|con| P
    P -->|pro| O
    O --> J[judge]
    J --> R((verdict))
```

### `map_reduce`

Mapper over each item, reducer folds mapped outputs into one answer.

```mermaid
flowchart TD
    G((items)) --> M1[mapper item 1]
    G --> M2[mapper item 2]
    G --> M3[mapper item N]
    M1 --> R[reducer]
    M2 --> R
    M3 --> R
    R --> O((output))
```
