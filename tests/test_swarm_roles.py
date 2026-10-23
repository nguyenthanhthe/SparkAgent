import asyncio
import unittest
from unittest import mock

from swarm.consensus import (consensus_summary, disagreement_score,
                             normalize_answer, vote)
from swarm.critic import critique, critique_feedback
from swarm.orchestrator import Orchestrator, _parse_plan
from swarm.mailbox import Mailbox


class ParsePlanTests(unittest.TestCase):
    def test_json_array_preferred(self):
        raw = 'Plan:\n["step one", "step two", "step three"]'
        self.assertEqual(_parse_plan(raw),
                         ["step one", "step two", "step three"])

    def test_numbered_lines_fallback(self):
        raw = "1. First meaningful step here\n2. Second step also here"
        self.assertEqual(_parse_plan(raw),
                         ["First meaningful step here", "Second step also here"])

    def test_max_steps_enforced(self):
        raw = '["a step that is long enough", "b", "c", "d", "e", "f", "g", "h"]'
        self.assertEqual(len(_parse_plan(raw, max_steps=3)), 3)

    def test_garbage_returns_empty(self):
        self.assertEqual(_parse_plan(""), [])
        self.assertEqual(_parse_plan("no steps here"), [])


def make_orchestrator(plan_json=None, worker_reply=None, critique_text=None,
                      synth_reply="FINAL ANSWER: all good"):
    async def planner(goal, context):
        return plan_json or '["analyze data", "write summary"]'

    async def worker(step, context):
        if worker_reply:
            return worker_reply(step)
        return f"did: {step}"

    async def critic(goal, context):
        return critique_text or "looks reasonable, minor gaps"

    async def synthesizer(goal, context):
        return synth_reply

    return Orchestrator(planner, worker, critic, synthesizer,
                        worker_count=2, mailbox=Mailbox())


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_pipeline_success(self):
        orch = make_orchestrator()
        report = await orch.run("summarize the system")
        self.assertTrue(report.success)
        self.assertEqual(len(report.plan), 2)
        self.assertEqual(len(report.worker_results), 2)
        self.assertTrue(report.critique)
        self.assertIn("FINAL", report.answer)
        self.assertEqual(report.steps, 4)

    async def test_blackboard_populated(self):
        orch = make_orchestrator()
        await orch.run("goal here")
        digest = orch.blackboard.digest()
        sections = orch.blackboard.sections()
        self.assertIn("plan", sections)
        self.assertIn("results", sections)
        self.assertIn("review", sections)
        self.assertGreaterEqual(digest["total_entries"], 4)

    async def test_empty_plan_fails_gracefully(self):
        orch = make_orchestrator(plan_json="no steps at all")
        report = await orch.run("goal")
        self.assertFalse(report.success)
        self.assertIn("no actionable steps", report.answer)
        self.assertEqual(report.steps, 1)

    async def test_worker_failure_isolated(self):
        def worker_reply(step):
            if "analyze" in step:
                raise RuntimeError("worker exploded")
            return "partial result"

        async def worker(step, context):
            return worker_reply(step)

        async def planner(goal, context):
            return '["analyze data", "write summary"]'

        async def critic(goal, context):
            return "ok"

        async def synthesizer(goal, context):
            return "recovered despite a worker failure"

        orch = Orchestrator(planner, worker, critic, synthesizer,
                            worker_count=2)
        report = await orch.run("goal")
        self.assertTrue(report.success)
        failed = [text for text in report.worker_results.values()
                  if "worker failed" in text]
        self.assertEqual(len(failed), 1)

    async def test_trace_id_present(self):
        orch = make_orchestrator()
        report = await orch.run("goal")
        self.assertTrue(report.trace_id)

    async def test_report_serializable(self):
        import json
        orch = make_orchestrator()
        payload = (await orch.run("goal")).to_dict()
        json.dumps(payload)  # must not raise


class SwarmBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_budget_enforced_gracefully(self):
        calls = {"count": 0}

        async def counting(goal, context):
            calls["count"] += 1
            return '["a step that is long enough", "another step here"]'

        async def worker(goal, context):
            return "did work"

        async def synth(goal, context):
            return "final"

        from swarm.orchestrator import Orchestrator
        orch = Orchestrator(counting, worker, counting, synth,
                            worker_count=4, max_role_calls=4)
        report = await orch.run("goal")
        self.assertTrue(report.budget_exceeded)
        self.assertFalse(report.success)
        self.assertIn("stopped early", report.answer)
        # total invocations never exceeded the budget
        self.assertLessEqual(calls["count"], 4)
        self.assertEqual(report.role_calls, 4)

    async def test_default_budget_allows_normal_run(self):
        orch = make_orchestrator()
        report = await orch.run("normal goal")
        self.assertFalse(report.budget_exceeded)
        self.assertTrue(report.success)
        self.assertEqual(report.role_calls, 5)  # 1+2+1+1


class ConsensusTests(unittest.TestCase):
    def test_majority_wins(self):
        result = vote([("YES", 1), ("yes.", 1), ("no", 1)], quorum=0.5)
        self.assertTrue(result.decided)
        self.assertEqual(normalize_answer(result.winner), "yes")
        self.assertEqual(result.tally["yes"], 2.0)

    def test_no_quorum_returns_none(self):
        result = vote([("a", 1), ("b", 1), ("c", 1)], quorum=0.5)
        self.assertFalse(result.decided)

    def test_weighted_votes(self):
        result = vote([("maybe", 1), ("definitely", 3)], quorum=0.7)
        self.assertTrue(result.decided)
        self.assertEqual(normalize_answer(result.winner), "definitely")

    def test_empty_input(self):
        result = vote([], quorum=0.5)
        self.assertFalse(result.decided)
        self.assertEqual(result.total_weight, 0)

    def test_normalization(self):
        self.assertEqual(normalize_answer("  Hello, World!! "), "hello, world")
        self.assertEqual(normalize_answer("OK."), "ok")

    def test_disagreement_score(self):
        unanimous = vote([("same", 1), ("same", 1)])
        split = vote([("a", 1), ("b", 1)])
        self.assertEqual(disagreement_score(unanimous), 0.0)
        self.assertEqual(disagreement_score(split), 0.5)

    def test_summary_shape(self):
        result = vote([("x", 1), ("x", 1)])
        summary = consensus_summary(result)
        self.assertTrue(summary["decided"])
        self.assertEqual(summary["winner"], "x")


class CriticTests(unittest.TestCase):
    def test_good_answer_passes(self):
        goal = "explain the gpu thermal throttling behavior"
        answer = ("GPU thermal throttling reduces clock speeds when the "
                  "card exceeds its thermal limit, protecting silicon and "
                  "sustaining stability during sustained workloads.")
        result = critique(goal, answer)
        self.assertTrue(result.passed, result.findings)
        self.assertGreater(result.score, 0.6)

    def test_short_answer_flagged(self):
        result = critique("do complex analysis", "ok")
        self.assertFalse(result.passed)
        self.assertTrue(any("too short" in f for f in result.findings))

    def test_missing_goal_terms_flagged(self):
        result = critique("deploy kubernetes cluster", "the weather is "
                          "lovely today and sunshine makes everything "
          "better for a walk in the park")
        self.assertFalse(result.passed)
        self.assertTrue(any("missing" in f for f in result.findings))

    def test_give_up_phrase_penalized(self):
        result = critique("hard question", "I don't know the answer to "
                          "that question about the system")
        self.assertFalse(result.passed)
        self.assertTrue(any("give-up" in f for f in result.findings))

    def test_empty_answer_zero(self):
        result = critique("goal", "   ")
        self.assertEqual(result.score, 0.0)

    def test_feedback_rendering(self):
        failed = critique("goal", "ok")
        feedback = critique_feedback(failed)
        self.assertIn("revision", feedback)


if __name__ == "__main__":
    unittest.main()
