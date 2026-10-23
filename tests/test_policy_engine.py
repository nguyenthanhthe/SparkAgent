import unittest

from security.policy_engine import (Action, Decision, PolicyDecisionError,
                                    PolicyEngine, Rule, policy_from_config)


def make_engine(**kw) -> PolicyEngine:
    defaults = dict(default=Decision.DENY, rules=[
        Rule("allow-read-tools", Decision.ALLOW, verb="call_tool",
             where={"tool": "system_status"}, priority=50),
        Rule("deny-dangerous", Decision.DENY, verb="call_tool",
             where={"tool": "skill_*", "dangerous": "True"}, priority=90),
        Rule("allow-operators", Decision.ALLOW, verb="*",
             where={"source": "operator"}, priority=10),
    ])
    defaults.update(kw)
    return PolicyEngine(default=defaults["default"], rules=defaults["rules"])


class RuleMatchingTests(unittest.TestCase):
    def test_exact_match(self):
        rule = Rule("r", Decision.ALLOW, verb="call_tool", where={"tool": "x"})
        self.assertTrue(rule.matches(Action("call_tool", {"tool": "x"})))
        self.assertFalse(rule.matches(Action("call_tool", {"tool": "y"})))

    def test_wildcard_match(self):
        rule = Rule("r", Decision.DENY, verb="call_tool",
                    where={"tool": "skill_*"})
        self.assertTrue(rule.matches(Action("call_tool", {"tool": "skill_x"})))
        self.assertFalse(rule.matches(Action("call_tool", {"tool": "web"})))

    def test_missing_attribute_never_matches(self):
        rule = Rule("r", Decision.ALLOW, verb="call_tool", where={"env": "prod"})
        self.assertFalse(rule.matches(Action("call_tool", {})))

    def test_verb_none_matches_all(self):
        rule = Rule("r", Decision.ALLOW)  # no verb
        self.assertTrue(rule.matches(Action("anything", {})))


class EngineTests(unittest.TestCase):
    def test_priority_order_respected(self):
        engine = make_engine()
        # deny-dangerous (90) beats allow-read-tools (50)
        decision, rule = engine.decide(Action("call_tool",
                                              {"tool": "skill_create",
                                               "dangerous": "True"}))
        self.assertEqual(decision, Decision.DENY)
        self.assertEqual(rule.name, "deny-dangerous")

    def test_first_match_within_same_priority(self):
        engine = PolicyEngine(default=Decision.DENY, rules=[
            Rule("a", Decision.ALLOW, verb="x"),
            Rule("b", Decision.DENY, verb="x"),
        ])
        decision, _ = engine.decide(Action("x"))
        self.assertEqual(decision, Decision.ALLOW)

    def test_default_deny_when_no_rule_matches(self):
        engine = make_engine()
        decision, rule = engine.decide(Action("call_tool",
                                              {"tool": "web_fetch"}))
        self.assertEqual(decision, Decision.DENY)
        self.assertIsNone(rule)

    def test_wildcard_verb_rule(self):
        engine = make_engine()
        decision, rule = engine.decide(Action("format_disk",
                                              {"source": "operator"}))
        self.assertEqual(decision, Decision.ALLOW)
        self.assertEqual(rule.name, "allow-operators")

    def test_check_raises_with_context(self):
        engine = make_engine()
        with self.assertRaises(PolicyDecisionError) as ctx:
            engine.check(Action("call_tool", {"tool": "web_fetch"}))
        self.assertIn("denied", str(ctx.exception))
        self.assertEqual(ctx.exception.action.verb, "call_tool")

    def test_check_allows_silently(self):
        engine = make_engine()
        engine.check(Action("call_tool", {"tool": "system_status"}))  # no raise

    def test_rules_summary_shape(self):
        summary = make_engine().rules_summary()
        self.assertEqual(len(summary), 3)
        self.assertEqual(summary[0]["name"], "deny-dangerous")  # priority 90


class ConfigLoaderTests(unittest.TestCase):
    def test_build_from_config_entries(self):
        engine = policy_from_config([
            {"name": "allow-web", "decision": "allow", "verb": "call_tool",
             "where": {"tool": "web_fetch"}},
            {"name": "block-all-else", "decision": "deny", "priority": 1},
        ], default="deny")
        decision, _ = engine.decide(Action("call_tool", {"tool": "web_fetch"}))
        self.assertEqual(decision, Decision.ALLOW)
        decision, _ = engine.decide(Action("call_tool", {"tool": "other"}))
        self.assertEqual(decision, Decision.DENY)


if __name__ == "__main__":
    unittest.main()
