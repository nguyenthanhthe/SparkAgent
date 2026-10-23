import unittest

from swarm.topologies import debate, map_reduce, parallel, sequential, star


def fn(template):
    async def handler(goal, context):
        return template.format(goal=goal, context=context)
    return handler


def failing(message):
    async def handler(goal, context):
        raise RuntimeError(message)
    return handler


class SequentialTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipes_outputs(self):
        result = await sequential("goal", [
            ("draft", fn("draft({goal})")),
            ("polish", fn("polish({context})")),
        ])
        self.assertEqual(result.output, "polish(draft(goal))")
        self.assertEqual(len(result.stages), 2)

    async def test_empty_stages(self):
        result = await sequential("goal", [])
        self.assertEqual(result.output, "goal")


class ParallelTests(unittest.IsolatedAsyncioTestCase):
    async def test_fan_out_and_merge(self):
        async def merge(goal, context):
            return f"merged[{context.count('[')}]"

        result = await parallel("goal", [
            ("a", fn("alpha")),
            ("b", fn("beta")),
        ], merge=merge)
        self.assertTrue(result.output.startswith("merged[2]"))
        self.assertEqual(len(result.stages), 2)

    async def test_no_merge_concatenates(self):
        result = await parallel("g", [("a", fn("A")), ("b", fn("B"))])
        self.assertIn("[a]\nA", result.output)
        self.assertIn("[b]\nB", result.output)

    async def test_worker_failure_isolated(self):
        result = await parallel("g", [
            ("boom", failing("nope")),
            ("ok", fn("fine")),
        ])
        self.assertIn("(boom failed: nope)", result.output)
        self.assertIn("fine", result.output)


class StarTests(unittest.IsolatedAsyncioTestCase):
    async def test_hub_routes_and_aggregates(self):
        calls = []

        async def hub(goal, context):
            calls.append(context[:20])
            if context.startswith("route"):
                return "routing decision"
            return "AGGREGATED"

        result = await star("goal", hub, [
            ("s1", fn("spoke1")),
            ("s2", fn("spoke2")),
        ])
        self.assertEqual(result.output, "AGGREGATED")
        self.assertEqual(len(calls), 2)     # routing + aggregation
        self.assertEqual(len(result.stages), 3)

    async def test_spoke_failure_recorded(self):
        async def hub(goal, context):
            return "hub"
        result = await star("g", hub, [("bad", failing("x"))])
        self.assertTrue(any("error" in stage for stage in result.stages))


class DebateTests(unittest.IsolatedAsyncioTestCase):
    async def test_alternating_then_settle(self):
        result = await debate("goal", fn("say({context:.20})"), rounds=2)
        self.assertEqual(result.output, "say(Settle the debate fa)")
        self.assertEqual(len(result.stages), 2)

    async def test_single_round(self):
        result = await debate("g", fn("x"), rounds=1)
        self.assertEqual(len(result.stages), 1)


class MapReduceTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_and_reduces(self):
        async def mapper(item, context):
            return item.upper()

        async def reducer(goal, context):
            return f"reduced<{context}>"

        result = await map_reduce("g", ["a", "b"], mapper, reducer)
        self.assertEqual(result.output, "reduced<A\n\nB>")
        self.assertEqual(len(result.stages), 2)

    async def test_mapper_failure_isolated(self):
        async def reducer(goal, context):
            return "done"

        result = await map_reduce("g", ["x"], failing("map died"), reducer)
        self.assertEqual(result.output, "done")
        self.assertTrue(any("map failed" in str(stage.values())
                            for stage in result.stages))


if __name__ == "__main__":
    unittest.main()
