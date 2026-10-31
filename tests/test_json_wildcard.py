"""json_query wildcard dot-paths — a.b.c traversal with ``*`` spreading."""

import unittest

from tools.json_tool import get_path

DATA = {
    "items": [
        {"name": "alpha", "tags": ["x", "y"]},
        {"name": "beta", "tags": ["z"]},
    ],
    "meta": {"owner": "ops"},
}


class GetPathWildcardTests(unittest.TestCase):
    def test_plain_path_unchanged(self):
        self.assertEqual(get_path(DATA, "items.0.name"), "alpha")
        self.assertEqual(get_path(DATA, "meta.owner"), "ops")
        self.assertEqual(get_path(DATA, "items.1.tags.0"), "z")

    def test_wildcard_over_list(self):
        self.assertEqual(get_path(DATA, "items.*.name"), ["alpha", "beta"])

    def test_wildcard_over_dict(self):
        doc = {"a": {"v": 1}, "b": {"v": 2}}
        self.assertEqual(get_path(doc, "*.v"), [1, 2])

    def test_nested_wildcards(self):
        self.assertEqual(get_path(DATA, "items.*.tags.*"),
                         ["x", "y", "z"])

    def test_wildcard_tail_returns_children(self):
        self.assertEqual(get_path(DATA, "items.*"),
                         [{"name": "alpha", "tags": ["x", "y"]},
                          {"name": "beta", "tags": ["z"]}])

    def test_wildcard_on_scalar_raises(self):
        with self.assertRaises(TypeError):
            get_path(DATA, "meta.owner.*")

    def test_missing_key_and_bad_index_still_raise(self):
        with self.assertRaises(KeyError):
            get_path(DATA, "items.0.nope")
        with self.assertRaises(IndexError):
            get_path(DATA, "items.9.name")
        with self.assertRaises(KeyError):
            get_path(DATA, "items.first.name")

    def test_empty_segments_tolerated(self):
        self.assertEqual(get_path(DATA, ".items..0.name"), "alpha")

    def test_slice_range(self):
        data = {"items": [{"name": "alpha"}, {"name": "beta"},
                          {"name": "gamma"}]}
        self.assertEqual(get_path(data, "items.0:2.name"),
                         ["alpha", "beta"])
        self.assertEqual(get_path(data, "items.1:.name"), ["beta", "gamma"])
        self.assertEqual(get_path(data, "items.:.name"),
                         ["alpha", "beta", "gamma"])

    def test_slice_with_wildcard_tail(self):
        data = {"rows": [{"tags": ["a", "b"]}, {"tags": ["c"]}]}
        self.assertEqual(get_path(data, "rows.:1.tags"), ["a", "b"])

    def test_slice_needs_a_list(self):
        with self.assertRaises(TypeError):
            get_path({"a": 1}, "a.0:1")

    def test_slice_as_final_segment(self):
        # the slice may be the last hop: it returns the raw window
        self.assertEqual(get_path({"n": [1, 2, 3, 4, 5]}, "n.1:3"),
                         [2, 3])
        self.assertEqual(get_path({"n": [1, 2, 3]}, "n.:"), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
