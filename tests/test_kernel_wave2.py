import unittest

from kernel.clock import FakeClock
from kernel.expiring import ExpiringCache
from kernel.pagination import (InvalidPageError, paginate,
                               parse_paging_params)
from kernel.serialization import compact_repr, safe_json, safe_parse


class SerializationTests(unittest.TestCase):
    def test_roundtrip_plain(self):
        self.assertEqual(safe_parse(safe_json({"a": [1, 2]})), {"a": [1, 2]})

    def test_never_raises_on_hostile_objects(self):
        class Hostile:
            def __repr__(self):
                raise RuntimeError("no repr for you")

        payload = {"obj": Hostile(), "set": {1, 2}, "deep": _nest(20)}
        text = safe_json(payload)
        self.assertIn("set", text)

    def test_circular_reference_cut(self):
        loop = {"name": "loop"}
        loop["self"] = loop
        text = safe_json(loop)
        self.assertIn("circular", text)

    def test_redactor_applied_to_strings(self):
        text = safe_json({"token": "sk-SECRETSECRET12"},
                         redactor=lambda s: s.replace("SECRET", "***"))
        self.assertNotIn("SECRET", text)

    def test_depth_cap(self):
        text = safe_json(_nest(30))
        self.assertIn("depth cap", text)

    def test_huge_string_truncated(self):
        text = safe_json({"blob": "x" * 50_000})
        self.assertLess(len(text), 20_000)

    def test_safe_parse_error_context(self):
        with self.assertRaises(ValueError) as ctx:
            safe_parse("{broken")
        self.assertIn("invalid JSON", str(ctx.exception))
        with self.assertRaises(ValueError):
            safe_parse(42)     # type guard

    def test_compact_repr(self):
        self.assertEqual(compact_repr("short"), "'short'")
        long_text = "y" * 1000
        self.assertLessEqual(len(compact_repr(long_text)), 300)

        class Hostile:
            def __repr__(self):
                raise RuntimeError()

        self.assertEqual(compact_repr(Hostile()), "<unrepr-able>")


def _nest(depth: int):
    node = {"leaf": True}
    for _ in range(depth):
        node = {"child": node}
    return node


class PaginationTests(unittest.TestCase):
    def test_first_page(self):
        page = paginate(list(range(100)), offset=0, limit=10)
        self.assertEqual(page.items, list(range(10)))
        self.assertTrue(page.has_more)
        self.assertEqual(page.next_offset, 10)

    def test_last_page(self):
        page = paginate([1, 2, 3], offset=0, limit=5)
        self.assertFalse(page.has_more)
        self.assertIsNone(page.next_offset)
        self.assertEqual(page.total, 3)

    def test_offset_past_end(self):
        page = paginate([1, 2, 3], offset=10, limit=5)
        self.assertEqual(page.items, [])
        self.assertFalse(page.has_more)

    def test_limit_capped(self):
        page = paginate(list(range(1000)), limit=99999)
        self.assertEqual(len(page.items), 200)   # MAX_LIMIT
        self.assertEqual(page.limit, 200)

    def test_invalid_args(self):
        for bad in (-1,):
            with self.assertRaises(InvalidPageError):
                paginate([], offset=bad)
        with self.assertRaises(InvalidPageError):
            paginate([], limit=0)

    def test_envelope_shape(self):
        envelope = paginate([1, 2, 3, 4], offset=1, limit=2).envelope()
        self.assertEqual(envelope["items"], [2, 3])
        self.assertTrue(envelope["has_more"])
        self.assertEqual(envelope["next_offset"], 3)
        self.assertEqual(envelope["total"], 4)

    def test_parse_params(self):
        self.assertEqual(parse_paging_params({}), (0, 50))
        self.assertEqual(parse_paging_params({"offset": "10",
                                              "limit": "5"}), (10, 5))
        with self.assertRaises(InvalidPageError):
            parse_paging_params({"offset": "abc"})


class ExpiringCacheTests(unittest.TestCase):
    def test_put_get_expiry(self):
        clock = FakeClock()
        cache = ExpiringCache(ttl_seconds=10, clock=clock)
        cache.put("k", "v")
        self.assertEqual(cache.get("k"), "v")
        clock.advance(11)
        self.assertIsNone(cache.get("k"))
        self.assertEqual(cache.stats["expirations"], 1)

    def test_get_or_compute_caches(self):
        clock = FakeClock()
        cache = ExpiringCache(clock=clock)
        calls = []
        cache.get_or_compute("k", lambda: calls.append(1) or "computed")
        value = cache.get_or_compute("k", lambda: "other")
        self.assertEqual(value, "computed")
        self.assertEqual(len(calls), 1)

    def test_eviction_bound(self):
        cache = ExpiringCache(max_entries=3)
        for i in range(5):
            cache.put(f"k{i}", i)
        self.assertEqual(len(cache), 3)
        self.assertEqual(cache.stats["evictions"], 2)

    def test_invalidate_and_clear(self):
        cache = ExpiringCache()
        cache.put("a", 1)
        self.assertTrue(cache.invalidate("a"))
        self.assertFalse(cache.invalidate("a"))
        cache.put("b", 2)
        self.assertEqual(cache.clear(), 1)

    def test_invalid_ttl_rejected(self):
        with self.assertRaises(ValueError):
            ExpiringCache(ttl_seconds=0)

    def test_snapshot(self):
        cache = ExpiringCache()
        cache.put("x", 1)
        snapshot = cache.snapshot()
        self.assertEqual(snapshot["size"], 1)
        self.assertIn("hits", snapshot)


if __name__ == "__main__":
    unittest.main()
