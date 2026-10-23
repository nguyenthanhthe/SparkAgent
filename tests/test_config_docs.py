import unittest
from pathlib import Path

from ops.config_reference import NOTES, generate, _walk
from kernel.config import DEFAULTS

DOC = Path(__file__).resolve().parents[1] / "docs" / "configuration.md"


class ConfigReferenceTests(unittest.TestCase):
    def test_committed_doc_in_sync_with_defaults(self):
        self.assertTrue(DOC.exists(), "docs/configuration.md missing — "
                        "run: python -m ops.config_reference")
        committed = DOC.read_text(encoding="utf-8")
        self.assertEqual(committed, generate(),
                         "docs/configuration.md is stale — regenerate with "
                         "python -m ops.config_reference")

    def test_every_note_targets_a_real_path(self):
        rows = dict(_walk(DEFAULTS))
        for path in NOTES:
            self.assertIn(path, rows, f"note for unknown key {path}")

    def test_generated_doc_covers_all_defaults(self):
        text = generate()
        for path, _default in _walk(DEFAULTS):
            self.assertIn(path, text)

    def test_renders_sections(self):
        text = generate()
        for section in DEFAULTS:
            self.assertIn(f"## `{section}`", text)


if __name__ == "__main__":
    unittest.main()
