import unittest

from interface.cli import CliUrlError, SparkCli, safe_path_token


class UrlGuardTests(unittest.TestCase):
    def test_loopback_accepted(self):
        from interface.cli import validate_base_url
        self.assertEqual(validate_base_url("http://127.0.0.1:8788"),
                         "http://127.0.0.1:8788")
        self.assertEqual(validate_base_url("http://localhost:8788"),
                         "http://localhost:8788")

    def test_non_http_scheme_rejected(self):
        from interface.cli import validate_base_url
        for bad in ("ftp://x", "file:///etc/passwd", "gopher://x"):
            with self.assertRaises(CliUrlError):
                validate_base_url(bad)

    def test_remote_host_requires_opt_in(self):
        import os
        from interface.cli import validate_base_url
        os.environ.pop("SPARKAGENT_CLI_ALLOW_REMOTE", None)
        with self.assertRaises(CliUrlError) as ctx:
            validate_base_url("http://example.com:8788")
        self.assertIn("SPARKAGENT_CLI_ALLOW_REMOTE", str(ctx.exception))

    def test_remote_host_allowed_with_env(self):
        import os
        from interface.cli import validate_base_url
        old = os.environ.get("SPARKAGENT_CLI_ALLOW_REMOTE")
        os.environ["SPARKAGENT_CLI_ALLOW_REMOTE"] = "1"
        try:
            self.assertEqual(validate_base_url("http://example.com"),
                             "http://example.com")
        finally:
            if old is None:
                os.environ.pop("SPARKAGENT_CLI_ALLOW_REMOTE", None)
            else:
                os.environ["SPARKAGENT_CLI_ALLOW_REMOTE"] = old

    def test_path_token_validation(self):
        self.assertEqual(safe_path_token("abc123", "id"), "abc123")
        for bad in ("../etc", "a/b", "a b", "", "x" * 100, "a?b=1"):
            with self.assertRaises(CliUrlError):
                safe_path_token(bad, "id")


class FakeTransport:
    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, url: str, method: str, body):
        self.calls.append((url, method, body))
        path_only = url.split("?", 1)[0]
        for suffix, response in self.routes.items():
            if path_only.endswith(suffix):
                return response
        raise AssertionError(f"unexpected call {method} {url}")


def make_cli(routes: dict):
    lines = []
    transport = FakeTransport(routes)
    cli = SparkCli(transport=transport, out=lines.append)
    return cli, transport, lines


class CliCommandTests(unittest.TestCase):
    def test_status(self):
        cli, _, lines = make_cli({"/api/status": {
            "agent": "sparkagent", "version": "0.2.0", "uptime_s": 120,
            "tools": ["a", "b"],
            "brain": {"local": {"ok": True, "model": "nemotron"},
                      "remote": {"ok": False, "model": "glm",
                                 "detail": "no key"}},
            "approvals_pending": [{"id": "x"}]}})
        cli.execute("status")
        text = "\n".join(lines)
        self.assertIn("sparkagent v0.2.0", text)
        self.assertIn("up 2m", text)
        self.assertIn("nemotron — up", text)
        self.assertIn("no key", text)
        self.assertIn("approvals: 1 pending", text)

    def test_tasks_listing(self):
        cli, _, lines = make_cli({"/api/tasks": [
            {"id": 1, "status": "done", "goal": "check gpu", "enabled": 1},
            {"id": 2, "status": "cancelled", "goal": "old", "enabled": 0}]})
        cli.execute("tasks")
        text = "\n".join(lines)
        self.assertIn("#1", text)
        self.assertIn("check gpu", text)
        self.assertIn("[off]", text)

    def test_submit(self):
        cli, transport, lines = make_cli({"/api/tasks": {"id": 42}})
        cli.execute("submit analyze the logs please")
        self.assertIn("submitted task #42", "\n".join(lines))
        url, method, body = transport.calls[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(body, {"goal": "analyze the logs please"})

    def test_submit_requires_goal(self):
        cli, _, lines = make_cli({})
        cli.execute("submit")
        self.assertIn("usage:", "\n".join(lines))

    def test_mem_query(self):
        cli, _, lines = make_cli({"/api/memories": [
            {"kind": "episode", "score": 0.8, "text": "gpu ran hot"}]})
        cli.execute("mem gpu temp")
        text = "\n".join(lines)
        self.assertIn("gpu ran hot", text)

    def test_sqlite_lists_rows(self):
        cli, transport, lines = make_cli({"/api/db/tasks": {
            "rows": [{"id": 1, "goal": "check gpu"}],
            "count": 1, "table": "tasks"}})
        cli.execute("sqlite tasks limit=5")
        text = "\n".join(lines)
        self.assertIn("check gpu", text)
        url, method, _body = transport.calls[-1]
        self.assertIn("/api/db/tasks", url)
        self.assertIn("limit=5", url)
        self.assertEqual(method, "GET")

    def test_sqlite_where_encoding(self):
        cli, transport, _ = make_cli({"/api/db/tasks": {"rows": [],
                                                        "count": 0}})
        cli.execute("sqlite tasks goal=water the plants descending")
        url = transport.calls[-1][0]
        self.assertIn("where=goal%3Dwater", url)
        self.assertIn("descending=1", url)

    def test_sqlite_requires_table(self):
        cli, _, lines = make_cli({})
        cli.execute("sqlite")
        self.assertIn("usage:", "\n".join(lines))

    def test_approve_routes_decision(self):
        cli, transport, lines = make_cli(
            {"/api/approvals/abc/approve": {"id": "abc",
                                            "status": "approved"}})
        cli.execute("approve abc")
        self.assertIn("approved", "\n".join(lines))
        url, method, _body = transport.calls[-1]
        self.assertTrue(url.endswith("/api/approvals/abc/approve"))
        self.assertEqual(method, "POST")

    def test_deny_routes_decision(self):
        cli, transport, _ = make_cli(
            {"/api/approvals/zz/deny": {"id": "zz", "status": "denied"}})
        cli.execute("deny zz")
        url, _, _ = transport.calls[-1]
        self.assertTrue(url.endswith("/deny"))

    def test_approvals_listing(self):
        cli, _, lines = make_cli({"/api/approvals": {
            "pending": [{"id": "p1", "kind": "skill",
                         "summary": "word counter"}],
            "recent": []}})
        cli.execute("approvals")
        self.assertIn("p1", "\n".join(lines))
        self.assertIn("word counter", "\n".join(lines))

    def test_skills_and_quarantine(self):
        cli, _, lines = make_cli({
            "/api/skills": [{"name": "word_count", "status": "active"}],
            "/api/quarantine": {"items": [
                {"id": "q1", "reason": "injection", "size_bytes": 100}]}})
        cli.execute("skills")
        self.assertIn("word_count", "\n".join(lines))
        cli.execute("quarantine")
        self.assertIn("injection", "\n".join(lines))

    def test_empty_quarantine_message(self):
        cli, _, lines = make_cli({"/api/quarantine": {"items": []}})
        cli.execute("quarantine")
        self.assertIn("empty", "\n".join(lines))

    def test_unknown_command_and_help(self):
        cli, _, lines = make_cli({})
        cli.execute("frobnicate")
        self.assertIn("unknown command", "\n".join(lines))
        cli.execute("help")
        self.assertIn("submit <goal>", "\n".join(lines))

    def test_quit_returns_false(self):
        cli, _, _ = make_cli({})
        self.assertFalse(cli.execute("quit"))
        self.assertFalse(cli.execute("exit"))
        self.assertTrue(cli.execute(""))          # blank line continues


if __name__ == "__main__":
    unittest.main()
