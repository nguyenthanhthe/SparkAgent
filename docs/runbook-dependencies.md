# Runbook: task dependency chains

How `depends_on` chains behave — what "blocked" means, how to release a
chain by hand, and what happens when a link in the chain fails. See
ADR-0006 for the design rationale.

## Semantics at a glance

- A task may carry `depends_on`: a list of task ids. Submit it via
  `POST /api/tasks` / `submit_task(..., depends_on=[id, ...])` — see
  `examples/dependency_chain_demo.py` for an offline walkthrough.
- The scheduler only picks a task when **all** of these hold:
  1. `enabled = 1` and `status = 'pending'`
  2. `next_run_at` is due
  3. every `depends_on` task has status `done`
- "Done" means settled successfully. A dependency that is `failed`,
  `running`, `paused` (disabled), or cancelled does **not** satisfy the
  gate — the dependent stays blocked. There is no partial credit and no
  timeout: blocked means blocked until the dependency reaches `done`.
- Recurring tasks can be dependencies too, but the gate only looks at
  their *current* status — a recurring task is `done` between runs and
  `pending` while scheduled, so chains on recurring tasks are racy by
  nature; prefer one-shot dependencies.

## Reading the state

| Signal | Where | Meaning |
|---|---|---|
| `blocked_by: [7]` in `GET /api/tasks/{id}` | task detail + dashboard drawer | task #7 is not `done` yet |
| `blocked tasks` counter | dashboard scheduler panel, `GET /api/status → scheduler.blocked_tasks` | how many enabled pending tasks are currently gated |
| `task_blocked` / `task_released` events | `GET /api/stream` (SSE), `/ws`, Live log | transitions as dependencies settle |
| `/api/db/tasks?where=status=failed` (or telegram `/db tasks`) | read-only lookup | find the dependency that never finished |

## Failure semantics

- A dependent task never runs "because its dependency failed" — there is
  no cascade of failure. The chain simply stalls, and the blocked count
  in the scheduler panel tells you how many tasks are parked.
- A *transient* dependency failure (all LLM tiers down) is requeued with
  exponential backoff (30s doubling, capped at 300s) and stays
  `pending`, so the chain resumes automatically when it finally succeeds.
- A *permanent* failure (episode ends `failed`) leaves the dependency at
  status `failed` — the chain stalls until a human intervenes.

## Manual release options

Given task #12 blocked by #7:

1. **Fix the dependency (preferred).** Re-run task #7 to success —
   resubmit its goal from the dashboard, or re-arm a one-shot with the
   retry endpoint. Once #7 is `done`, the next scheduler tick emits
   `task_released` for #12 and runs it.
2. **Cut the dependency.** Cancel #12 (`POST /api/tasks/12/cancel` via
   the dashboard task row or curl), then resubmit the same goal
   *without* `depends_on`. Use when the upstream outcome no longer
   matters.
3. **Do not** hand-edit the database while the daemon runs — the
   scheduler's in-memory blocked-set reconciles on each tick, but the
   audit trail and events are only correct if changes go through the API.

## Verification after intervention

1. `GET /api/tasks/12 → blocked_by` — should be `[]`.
2. Scheduler panel blocked count decrements; a `task_released` event for
   #12 appears on the stream within one poll interval.
3. `GET /api/tasks/12 → status` walks `pending → running → done`
   (or the episode shows the failure that stopped it).
