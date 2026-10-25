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


if __name__ == "__main__":
    unittest.main()
