"""json_query mode=shape — caller-controlled recursion depth."""

import unittest

from tools.json_tool import shape

DEEP = {"a": {"b": {"c": {"d": {"e": 1}}}}}


class ShapeMaxDepthTests(unittest.TestCase):
    def test_default_depth_is_four(self):
        result = shape(DEEP)
        self.assertEqual(result["a"]["b"]["c"]["d"], "…")

    def test_caller_max_depth_extends_reach(self):
        result = shape(DEEP, max_depth=6)
        self.assertEqual(result["a"]["b"]["c"]["d"]["e"], "int")

    def test_max_depth_one_collapses_to_placeholder(self):
        self.assertEqual(shape(DEEP, max_depth=1), {"a": "…"})

    def test_list_first_honors_depth(self):
        data = {"rows": [{"inner": {"deep": [1]}}]}
        result = shape(data, max_depth=3)
        self.assertEqual(result["rows"]["__len__"], 1)
        self.assertEqual(result["rows"]["first"]["inner"], "…")
        deep = shape(data, max_depth=6)
        self.assertEqual(deep["rows"]["first"]["inner"]["deep"],
                         {"__len__": 1, "first": "int"})


if __name__ == "__main__":
    unittest.main()
