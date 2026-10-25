# ADR-0006: Scheduler task dependencies

Status: accepted

## Context

The scheduler ran tasks purely on time (`next_run_at`) and priority:
any due task could start even when its precondition — another task
whose output it consumes — had not finished or had failed. Operators
submitting pipelines (fetch data → digest → notify) had to encode the
ordering inside the goal text or poll manually, and a failed upstream
task left downstream tasks running against stale inputs.

## Decision

Tasks gain an optional `depends_on` list of task ids, stored as a JSON
column. `Memory.due_tasks` gates readiness: a task is due only when
*every* dependency has settled to `done`. Failed or cancelled
dependencies block the dependent indefinitely (retry the upstream task
to unblock); tasks with no dependencies behave exactly as before. The
web `POST /api/tasks` endpoint accepts `depends_on` and validates that
every referenced task exists at submit time.

## Consequences

- A one-shot dependency chain resolves in submission order; each
  completion releases the next task on the following tick.
- `due_tasks` fetches a wider window (`limit * 3`) before filtering so
  blocked tasks cannot starve ready ones in a single tick.
- A corrupt `depends_on` JSON blob degrades to "no dependencies"
  rather than blocking forever.
- There is no cycle detection across tasks — dependencies form a DAG
  only by operator discipline; a cycle simply never becomes due (a
  visible, honest failure rather than a hidden reorder).
- Failed dependencies block rather than skip: downstream work on
  incomplete upstream state is worse than waiting.

## Alternatives

- **Goal-text ordering** — rejected: invisible to the scheduler and to
  the dashboard; the status API cannot show blocked tasks.
- **Auto-skip on failed dependency** — rejected: silently skipping
  loses the work item; an operator cancels explicitly instead.
- **Full DAG engine with cycle detection** — deferred: the current use
  cases are linear chains; cycle detection can be added when a real
  workload needs it.
