# Swarm — multi-agent coordination

One brain, many roles. The swarm package composes agent functions
(`async (goal, context) -> str`) into coordination patterns; every
intermediate artifact lands on the mailbox/blackboard for observability.

## Roles

- **planner** — decomposes the goal into 2–4 concrete steps (JSON array)
- **worker** — executes an assigned step in parallel with its siblings
- **critic** — reviews results against the goal; gaps and the top fix
- **synthesizer** — merges plan + results + critique into the answer

The heuristic critic (`swarm/critic.py`) also runs standalone: goal-term
coverage, substance, give-up/template phrases, injection risk → score,
findings, revision instructions.

## Patterns (`swarm/topologies.py`)

| Pattern | Shape |
|---|---|
| `sequential` | pipeline: each stage's output feeds the next context |
| `parallel` | fan-out on one goal; optional merge |
| `star` | hub routes, spokes answer, hub aggregates |
| `debate` | alternating pro/con rounds, then settlement |
| `map_reduce` | mapper per item, reducer folds |

Failures are isolated: a dead worker's slot becomes `(worker failed: …)`
in the report; the pipeline continues.

## Message plane

`AgentMessage` (kind, sender, payload, trace id, in-reply-to) over a
bounded `Mailbox` (drop-oldest overflow, wake-on-delivery). The
`Blackboard` is a versioned section store (findings/decisions/review)
with provenance and a delta protocol — the orchestrator writes every
stage's artifacts there.

## Consensus

`vote(answers, weights, quorum)` normalizes answers and elects a winner
by weight; `disagreement_score` reports fragmentation. The `consensus`
tool asks the model N times and reports majority or an explicit
divergence note.

## Tools exposed to the agent

- `swarm_delegate(goal, workers=2)` — full pipeline
- `debate(question, rounds=2)` — adversarial refinement
- `consensus(question, voters=3)` — reliability voting

All role calls go through the normal brain router — tier fallback, cache,
and cost accounting apply to every role invocation.
