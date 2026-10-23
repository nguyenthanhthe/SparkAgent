import unittest

from memory_search.summarizer import consolidate, split_sentences, summarize


class SentenceSplitTests(unittest.TestCase):
    def test_basic_splitting(self):
        text = ("First sentence is definitely here. "
                "Second one also follows here! "
                "And then a third arrives? "
                "Trailing fragment without punctuation")
        sentences = split_sentences(text)
        self.assertEqual(len(sentences), 4)

    def test_filters_extremes(self):
        self.assertEqual(split_sentences("tiny"), [])
        self.assertEqual(split_sentences(""), [])
        self.assertEqual(split_sentences("word " * 80 + "."), [])


class SummarizeTests(unittest.TestCase):
    TEXT = ("The GPU reached 95 degrees during sustained inference. "
            "Thermal throttling reduced clocks by 15 percent. "
            "The meeting agenda included quarterly planning items. "
            "Cleaning the fans resolved the temperature issue entirely. "
            "Lunch options were discussed at length by the team.")

    def test_extracts_representative_sentences(self):
        digest = summarize(self.TEXT, top=2)
        joined = digest.summary.lower()
        self.assertIn("gpu", joined)
        self.assertIn("thermal", joined)

    def test_off_topic_dropped(self):
        digest = summarize(self.TEXT, top=2)
        self.assertNotIn("Lunch", digest.summary)

    def test_query_focus(self):
        digest = summarize(self.TEXT, top=1, query="fans cleaning")
        self.assertIn("fans", digest.summary)

    def test_redundancy_suppressed(self):
        text = ("Alpha beta gamma delta variant one. "
                "Alpha beta gamma delta variant two. "
                "Alpha beta gamma delta variant three.")
        digest = summarize(text, top=2)
        self.assertLessEqual(len(digest.sentences), 1)
        self.assertGreaterEqual(digest.dropped_redundant, 2)

    def test_narrative_order_restored(self):
        text = ("Important early context about the system design. "
                "Middle details of moderate value. "
                "Strong late conclusion summarizing everything important.")
        digest = summarize(text, top=3)
        indexes = [s.index for s in digest.sentences]
        self.assertEqual(indexes, sorted(indexes))

    def test_short_text_passthrough(self):
        digest = summarize("Too short", top=2)
        self.assertEqual(digest.summary, "Too short")


class ConsolidateTests(unittest.TestCase):
    def test_consolidates_episodes(self):
        episodes = [
            {"goal": "check gpu temperature", "final_answer":
             "GPU runs at 70c idle and 95c under load"},
            {"goal": "clean the dust filters", "final_answer":
             "Filters cleaned; temperatures dropped by 8 degrees"},
        ]
        digest = consolidate(episodes)
        self.assertIn("2 episodes", digest)
        self.assertIn("gpu", digest.lower())

    def test_query_guided_consolidation(self):
        episodes = [
            {"goal": "deploy service", "final_answer": "deployment on "
             "kubernetes finished after fixing node affinity"},
            {"goal": "write docs", "final_answer": "documentation updated "
             "with examples"},
        ]
        digest = consolidate(episodes, query="kubernetes")
        self.assertIn("kubernetes", digest.lower())

    def test_skips_empty_episodes(self):
        digest = consolidate([{"goal": "", "final_answer": ""}])
        self.assertIn("1 episodes", digest)
        self.assertEqual(len(digest.splitlines()), 1)   # header only

    def test_length_capped(self):
        episodes = [{"goal": f"goal {i} " + "x" * 50,
                     "final_answer": "outcome " + "y" * 50} for i in range(200)]
        digest = consolidate(episodes)
        self.assertLessEqual(len(digest), 4000)


if __name__ == "__main__":
    unittest.main()
