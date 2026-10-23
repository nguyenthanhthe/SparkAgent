"""SparkAgent CLI — control a running daemon from the terminal.

``python -m interface.cli [--url http://127.0.0.1:8788]`` opens an interactive prompt;
``python -m interface.cli status`` runs a single command and exits.
Transport is injectable (``http_json``) so tests run without a server.

Safety: the transport only speaks http(s), only to loopback targets by
default (remote requires ``SPARKAGENT_CLI_ALLOW_REMOTE=1``), and every
user-supplied path segment is validated as a simple token before it
enters a URL — no traversal, no query-string smuggling.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import socket
import sys
import urllib.request
from typing import Any, Callable
from urllib.parse import quote, urlparse

Transport = Callable[[str, str, dict | None], Any]

HELP = """commands:
  status                 daemon status summary
  tasks                  list tasks
  submit <goal>          submit a one-shot task
  mem <query>            semantic memory recall
  approvals              pending operator approvals
  approve <id> / deny <id>
  skills                 list skills
  quarantine             quarantined items
  help | quit"""

_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


class CliUrlError(ValueError):
    pass


def safe_path_token(token: str, what: str) -> str:
    """Path segments must be simple tokens; reject anything that could
    alter the URL structure (traversal, slashes, query syntax)."""
    if not _TOKEN_RE.fullmatch(token or ""):
        raise CliUrlError(f"invalid {what}: {token!r}")
    return token


def validate_base_url(base_url: str) -> str:
    """Accept http(s) loopback targets; remote hosts need explicit opt-in."""
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise CliUrlError(f"unsupported scheme {parsed.scheme!r} "
                          "(only http/https)")
    host = parsed.hostname
    if not host:
        raise CliUrlError("URL has no hostname")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise CliUrlError(f"cannot resolve {host!r}: {exc}") from exc
    addresses = {info[4][0] for info in infos}
    loopback_only = all(ipaddress.ip_address(address).is_loopback
                        for address in addresses)
    if not loopback_only and not os.environ.get("SPARKAGENT_CLI_ALLOW_REMOTE"):
        raise CliUrlError(
            f"refusing non-loopback target {host!r} — set "
            f"SPARKAGENT_CLI_ALLOW_REMOTE=1 to allow it deliberately")
    return base_url


def http_json(base_url: str, method: str, body: dict | None) -> Any:
    url = validate_base_url(base_url).rstrip("/")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


class SparkCli:
    def __init__(self, transport: Transport = http_json,
                 base_url: str = "http://127.0.0.1:8788", out=print):
        self._transport = transport
        self._base = base_url
        self._out = out

    def _call(self, path: str, method: str = "GET",
              body: dict | None = None) -> Any:
        return self._transport(self._base + path, method, body)

    # ---------------------------------------------------------------- command
    def execute(self, line: str) -> bool:
        """Run one command line; False means 'quit'."""
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        if not parts:
            return True
        command, args = parts[0].lower(), parts[1:]

        if command in ("quit", "exit"):
            return False
        if command == "help":
            self._out(HELP)
        elif command == "status":
            self._cmd_status()
        elif command == "tasks":
            self._cmd_tasks()
        elif command == "submit":
            self._cmd_submit(" ".join(args))
        elif command == "mem":
            self._cmd_mem(" ".join(args))
        elif command in ("approve", "deny"):
            self._cmd_decide(command, args[0] if args else "")
        elif command == "approvals":
            self._cmd_approvals()
        elif command == "skills":
            self._cmd_skills()
        elif command == "quarantine":
            self._cmd_quarantine()
        else:
            self._out(f"unknown command {command!r} — try 'help'")
        return True

    # --------------------------------------------------------------- handlers
    def _cmd_status(self) -> None:
        status = self._call("/api/status")
        brain = status.get("brain", {})
        self._out(f"agent    : {status.get('agent')} "
                  f"v{status.get('version')} "
                  f"(up {status.get('uptime_s', 0) // 60}m)")
        for tier in ("local", "remote"):
            info = brain.get(tier) or {}
            mark = "up" if info.get("ok") else (info.get("detail") or "down")
            self._out(f"brain {tier:<6}: {info.get('model')} — {mark}")
        self._out(f"tools    : {len(status.get('tools', []))} registered")
        self._out(f"approvals: {len(status.get('approvals_pending', []))} "
                  f"pending")

    def _cmd_tasks(self) -> None:
        payload = self._call("/api/tasks")
        tasks = payload.get("items", payload) if isinstance(payload, dict) \
            else payload
        if not tasks:
            self._out("(no tasks)")
            return
        for task in tasks[:20]:
            flag = "" if task.get("enabled") else " [off]"
            self._out(f"#{task['id']:<4} {task.get('status', '?'):<8} "
                      f"{task.get('goal', '')[:60]}{flag}")

    def _cmd_submit(self, goal: str) -> None:
        if not goal.strip():
            self._out("usage: submit <goal>")
            return
        result = self._call("/api/tasks", "POST", {"goal": goal})
        self._out(f"submitted task #{result.get('id')}")

    def _cmd_mem(self, query: str) -> None:
        if not query.strip():
            self._out("usage: mem <query>")
            return
        encoded = quote(query.strip())
        hits = self._call("/api/memories?q=" + encoded)
        if not hits:
            self._out("(no memories)")
            return
        for hit in hits:
            self._out(f"[{hit.get('kind')} {hit.get('score', 0):.2f}] "
                      f"{hit.get('text', '')[:100]}")

    def _cmd_approvals(self) -> None:
        approvals = self._call("/api/approvals")
        pending = approvals.get("pending", [])
        if not pending:
            self._out("(no pending approvals)")
            return
        for request in pending:
            self._out(f"{request['id']}  [{request['kind']}] "
                      f"{request['summary'][:80]}")

    def _cmd_decide(self, decision: str, approval_id: str) -> None:
        if not approval_id:
            self._out(f"usage: {decision} <approval-id>")
            return
        decision = safe_path_token(decision, "decision")
        approval_id = safe_path_token(approval_id, "approval id")
        path = "/api/approvals/" + approval_id + "/" + decision
        result = self._call(path, "POST")
        self._out(f"approval {result.get('id')}: {result.get('status')}")

    def _cmd_skills(self) -> None:
        skills = self._call("/api/skills")
        for skill in skills:
            self._out(f"{skill['name']:<24} {skill['status']}")

    def _cmd_quarantine(self) -> None:
        items = self._call("/api/quarantine").get("items", [])
        if not items:
            self._out("(quarantine empty)")
            return
        for item in items:
            self._out(f"{item['id']}  {item.get('reason', '')[:60]} "
                      f"({item.get('size_bytes', 0)}B)")

    # ------------------------------------------------------------------- repl
    def repl(self) -> None:
        self._out(f"SparkAgent CLI — {self._base} (help for commands)")
        while True:
            try:
                line = input("spark> ")
            except (EOFError, KeyboardInterrupt):
                self._out("")
                break
            if not self.execute(line):
                break


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    url = "http://127.0.0.1:8788"
    if "--url" in argv:
        index = argv.index("--url")
        url = argv[index + 1]
        del argv[index:index + 2]

    cli = SparkCli(base_url=url)
    if argv:
        cli.execute_args(argv)
        return 0
    cli.repl()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
