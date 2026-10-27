# ADR-0008: Conditional fetch and cache semantics for web tools

Status: accepted

## Context

`web_fetch` is the agent's only door to the public web, and repeated
fetches of the same page are common (docs lookups, monitoring a status
page, re-reading a source after a build). Re-downloading unchanged
pages wastes bandwidth and time, and pulls the content through the
prompt-injection guard over and over. HTTP already has the right
mechanism — validators (`ETag`) and conditional requests
(`If-None-Match` → `304 Not Modified`) — so the question is how to use
them inside an SSRF-guarded, size-capped fetcher without creating a
stale-content hazard.

## Decision

`WebFetcher` keeps a small in-memory validator cache keyed by the
**final URL after redirects** (128 entries, LRU-evicted). On a
successful 200 response carrying an `ETag`, the processed result is
stored alongside the validator. The next fetch of that URL sends
`If-None-Match`; a `304` short-circuits — no body is read, no
re-conversion, no re-scan — and the cached result is returned with
`not_modified: true` so callers can tell a revalidation from a fresh
download. Semantics:

- Only `ETag` is honored; `Last-Modified`/`If-Modified-Since` are
  deliberately out (weaker validator, two header families to reason
  about, no benefit for this use case).
- A `304` with no matching cache entry (cache evicted, restart) is
  treated as a normal response and read like any other — never an
  error.
- The cache is process-local and in-memory only. Nothing persists to
  disk, so a restart revalidates from scratch: staleness is bounded by
  the server's own validator semantics, not by our retention.
- The guard pipeline (prompt-injection scan, redaction) runs on fresh
  downloads exactly as before; 304 replays serve the *already-guarded*
  text, which is safe by construction and cheaper.

## Consequences

- Unchanged pages cost one round-trip with an empty body instead of a
  full download plus guard processing; the fetcher's `cache_hits`
  counter and the `not_modified` flag make the saving visible.
- Redirects are re-followed on every fetch (by design — the SSRF guard
  re-validates every hop), so the cache must key on the final URL;
  keying on the requested URL would cross-check validators between
  different origin servers.
- Servers that ignore `If-None-Match` or rotate ETags per response
  simply never hit the cache — the mechanism degrades to plain
  fetching, no correctness risk.
- A hostile server could serve different content under a stable ETag;
  that is indistinguishable from the server's own caching semantics
  and out of scope — the prompt guard still scans every fresh body.

## Alternatives

- **Time-based TTL cache (ignore validators, serve stale N minutes)** —
  rejected: returns stale content by construction and duplicates what
  HTTP caching headers already express.
- **Full HTTP cache (Cache-Control, Vary, max-stale)** — rejected as
  overkill for a fetch-to-text tool; we do not render or proxy, we
  extract readable text, and the validator pair covers the reuse
  pattern.
- **Persist the cache to disk** — rejected: the win is small on a
  personal agent (a few MB), and persisted web content becomes a
  stale-data liability that outlives the process.
