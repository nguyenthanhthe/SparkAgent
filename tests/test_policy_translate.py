import tempfile
import unittest
from pathlib import Path

import yaml

from openshell import SecurityPolicy
from openshell.policy_translate import (SCHEMA_VERSION, export_policy_file,
                                        render_yaml, translate)


def make_policy(sandbox: Path, **kw):
    defaults = dict(allowed_programs=["python", "git"],
                    allowed_roots=[sandbox, sandbox.parent],
                    sandbox_root=sandbox)
    defaults.update(kw)
    return SecurityPolicy(**defaults)


class TranslateTests(unittest.TestCase):
    def test_document_shape(self):
        policy = make_policy(Path(tempfile.mkdtemp()))
        document = translate(policy, sandbox_name="lab")
        self.assertEqual(document["apiVersion"], SCHEMA_VERSION)
        self.assertEqual(document["kind"], "SandboxPolicy")
        self.assertEqual(document["metadata"]["name"], "lab")
        spec = document["spec"]
        for section in ("process", "filesystem", "network", "credentials"):
            self.assertIn(section, spec)

    def test_exec_allowlist_mirrors_ours(self):
        policy = make_policy(Path(tempfile.mkdtemp()))
        document = translate(policy)
        self.assertEqual(document["spec"]["process"]["execAllowlist"],
                         ["git", "python"])
        self.assertFalse(document["spec"]["process"]["shellAllowed"])

    def test_filesystem_roots_and_denies(self):
        sandbox = Path(tempfile.mkdtemp())
        policy = make_policy(sandbox)
        document = translate(policy)
        fs = document["spec"]["filesystem"]
        self.assertEqual(len(fs["readOnly"]), 2)
        self.assertEqual(fs["readWrite"], [fs["readOnly"][0]])
        self.assertIn("**/vault.bin", fs["deny"])

    def test_network_deny_by_default(self):
        document = translate(make_policy(Path(tempfile.mkdtemp())))
        net = document["spec"]["network"]
        self.assertEqual(net["default"], "deny")
        self.assertEqual(net["allow"], [])

    def test_credentials_never_exposed(self):
        document = translate(make_policy(Path(tempfile.mkdtemp())))
        self.assertEqual(document["spec"]["credentials"]["expose"], [])


class RenderTests(unittest.TestCase):
    def test_yaml_roundtrip(self):
        document = translate(make_policy(Path(tempfile.mkdtemp())))
        rendered = render_yaml(document)
        parsed = yaml.safe_load(rendered)
        self.assertEqual(parsed, document)

    def test_empty_collections_render(self):
        document = {"spec": {"network": {"allow": []},
                             "meta": {}}}
        rendered = render_yaml(document)
        parsed = yaml.safe_load(rendered)
        self.assertEqual(parsed, document)

    def test_quoting_escapes(self):
        document = {"metadata": {"description": 'has "quotes" inside'}}
        parsed = yaml.safe_load(render_yaml(document))
        self.assertEqual(parsed["metadata"]["description"],
                         'has "quotes" inside')


class ExportTests(unittest.TestCase):
    def test_export_writes_parseable_file(self):
        sandbox = Path(tempfile.mkdtemp())
        policy = make_policy(sandbox)
        target = sandbox / "openshell-policy.yaml"
        document = export_policy_file(policy, target, sandbox_name="exp")
        self.assertTrue(target.exists())
        parsed = yaml.safe_load(target.read_text(encoding="utf-8"))
        self.assertEqual(parsed, document)
        self.assertEqual(parsed["metadata"]["name"], "exp")


if __name__ == "__main__":
    unittest.main()
