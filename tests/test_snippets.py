"""Snippet highlighting — matched query terms marked in recall results."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.memory import Memory
from memory_search.snippets import highlight_snippet


class SnippetUnitTests(unittest.TestCase):
    def test_marks_matched_terms(self):
        snippet = highlight_snippet(
            "The scheduler gates tasks on dependencies and nothing else.",
            "scheduler dependencies")
        self.assertIn("**scheduler**", snippet)
        self.assertIn("**dependencies**", snippet)
        self.assertNotIn("**tasks**", snippet)

    def test_window_centers_on_densest_match(self):
        filler = "unrelated words about gardening " * 30
        text = filler + "cache responses live in the brain cache layer. " \
            + filler
        snippet = highlight_snippet(text, "brain cache", width=120)
        self.assertIn("**cache**", snippet)
        self.assertIn("**brain**", snippet)

    def test_no_match_falls_back_to_head(self):
        text = "completely unrelated prose " * 40
        snippet = highlight_snippet(text, "quantum", width=60)
        self.assertTrue(snippet.startswith("completely"))
        self.assertTrue(snippet.endswith("…"))

    def test_empty_text(self):
        self.assertEqual(highlight_snippet("", "anything"), "")

    def test_case_insensitive_match(self):
        snippet = highlight_snippet("Backup VERIFIED before restore.",
                                    "verified")
        self.assertIn("**VERIFIED**", snippet)

    def test_length_contract_excludes_markers(self):
        # the underlying text obeys the width budget; the ** markers are
        # overhead on top, never part of it
        text = ("filler " * 60) + "cache responses live in the brain " \
            + ("filler " * 60)
        snippet = highlight_snippet(text, "brain cache", width=120)
        self.assertLessEqual(len(snippet.replace("**", "")), 136)


class RecallSnippetTests(unittest.IsolatedAsyncioTestCase):
    async def test_recall_hits_carry_snippet(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            await memory.remember(
                "the backup verify-all command checks the retention "
                "window digests", kind="fact")
            hits = await memory.recall("backup verify", k=3)
            self.assertTrue(hits)
            hit = hits[0]
            self.assertIsNotNone(hit.snippet)
            self.assertIn("**", hit.snippet)
            self.assertLessEqual(len(hit.snippet), 240)
        finally:
            await memory.close()


if __name__ == "__main__":
    unittest.main()
