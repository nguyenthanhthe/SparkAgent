# Testing guide

The suite is deliberately **offline and deterministic**: no network, no
LLM, no GPU, no sleeping (clocks are injected everywhere). That is why
567+ tests run in seconds and why they can gate every commit.

## Running

```
python -m unittest discover -s tests -t .          # everything
python -m unittest tests.test_security_wave -v     # one module
coverage run -m unittest discover -s tests -t .    # with coverage
coverage report --sort=cover
```

## Conventions

- **Plain `unittest`** — no pytest dependency; `IsolatedAsyncioTestCase`
  for async behavior.
- **Fakes over mocks** — `FakeBrain`, `FakeLocal/FakeRemote`,
  `FakePoster`, `FakeSession`, `RoleAwareBrain` implement the real
  interface with scripted replies; `mock.patch` is rare.
- **Injectable clocks** — token buckets, TTL caches, approval expiry,
  circuit cooldowns all use `FakeClock.advance`, never `sleep`.
- **Temp directories** — every store test builds its own
  `tempfile.TemporaryDirectory`; nothing touches `data/`.
- **Failure paths required** — a test suite that only checks happy
  paths proves nothing; nearly every module has explicit
  tamper/blocked/rejected cases (the git history is full of real bugs
  these caught).

## Testing a new component

1. Happy path(s).
2. Every validation/error branch — assert the *message content*, not
   just the exception type (messages become model observations).
3. Boundary behavior (empty input, overflow, expired, unauthorized).
4. If the component is async: cancellation and timeout behavior via
   `IsolatedAsyncioTestCase`.

## Speed discipline

The full suite should stay well under ~90 seconds on a laptop. If a test
needs real waiting, it is testing the wrong thing — inject a clock. The
one CPU-bound area (skill smoke timeouts) uses short, terminating loops
by design.

## Self-check

`python main.py --check` runs an offline smoke of the composed system
(config, policy, SSRF guard, vault crypto, memory recall, ReAct parsing)
— a fast post-install sanity probe, separate from the unit suite.
