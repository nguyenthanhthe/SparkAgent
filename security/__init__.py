"""Security package — hardening layers beyond openshell's sandbox.

policy_engine  — declarative allow/deny rule matching over attributes
approval       — operator approval workflow for sensitive actions
promptguard    — prompt-injection heuristics for untrusted content
signatures     — HMAC signing/verification for skill files
quarantine     — hold-back store for suspicious content
"""

from security.policy_engine import Action, Decision, PolicyEngine, Rule

__all__ = ["Action", "Decision", "PolicyEngine", "Rule"]
