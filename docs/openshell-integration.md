# NVIDIA OpenShell integration

[NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) is an
Apache-2.0 sandboxed runtime for autonomous agents: kernel-confined
sandboxes, policy-governed filesystem/syscall/network access,
credential injection only at approved endpoints, and formally verified
policy changes, run through a gateway/supervisor/sandbox architecture.

SparkAgent's own `openshell/` package has always been a **policy layer**
(allowlists, denylists, path confinement) — honest guardrails, not a VM.
This integration closes that gap: when the real OpenShell runtime is
installed, admitted commands execute **inside a kernel-confined
sandbox**; when it is not, SparkAgent keeps running on its policy
executor. Same code path, two enforcement tiers.

## How it works

```
model action
    │
    ▼
SparkAgent policy layer        ← always first: allowlist, denylist,
    │                            path confinement, rate limits
    ├─ blocked → observation
    ▼
OpenShell runtime present?
    ├─ yes → openshell sandbox exec --sandbox sparkagent -- <exe> <args>
    └─ no  → host policy executor (transparent fallback)
```

Configuration (`openshell.backend`):

| Value | Behavior |
|---|---|
| `auto` *(default)* | probe the runtime once; sandbox when present, fall back otherwise |
| `openshell` | prefer the sandbox (still falls back if probing fails) |
| `policy` | never sandbox — host executor only |

Related keys: `openshell.sandbox_name` (default `sparkagent`),
`openshell.minimum_version`. Runtime detection appears live in
`GET /api/status` → `sandbox_backend` (`{"backend": "openshell"|"policy-fallback", "runtime": {...}}`).

## Installing the runtime

```
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
openshell sandbox create --name sparkagent
```

Platforms: Linux, macOS (Apple Silicon), Windows via WSL2
(experimental). On a Windows host without WSL2, `auto` simply stays on
the policy backend.

## Exporting a sandbox policy

`openshell/policy_translate.py` renders our allowlists as a draft
OpenShell sandbox policy (exec allowlist, read/write roots, secret
denies, deny-by-default network):

```
python -c "from pathlib import Path; \
from kernel.config import Config; from kernel.daemon import AgentDaemon; \
from openshell.policy_translate import export_policy_file; \
d = AgentDaemon(Config.load()); \
export_policy_file(d.policy, Path('openshell-policy.yaml'))"
```

The draft is a faithful mirror of SparkAgent's rules; apply it through
OpenShell's own policy/advisor/prover flow — SparkAgent never installs
policies silently.

## Threat-model delta

| | Policy backend (built-in) | OpenShell backend |
|---|---|---|
| Untrusted code execution | process-level guardrails | kernel confinement + syscall policy |
| Filesystem escapes | path-validation only | enforced read/write roots |
| Network egress | app-level (webfetch SSRF guard) | policy-checked connections |
| Credentials | env sanitization + vault | never in-sandbox; endpoint-bound injection |
| Bug classes contained | policy bugs → blocked or host exec | policy bugs contained by sandbox |

Defense in depth is the point: our policy layer runs **first** in both
modes, so a SparkAgent misconfiguration cannot widen what the sandbox
allows.
