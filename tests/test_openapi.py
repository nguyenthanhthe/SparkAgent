import unittest

from interface.openapi import build_spec, spec_markdown


class OpenApiTests(unittest.TestCase):
    def setUp(self):
        self.spec = build_spec()

    def test_valid_structure(self):
        self.assertEqual(self.spec["openapi"], "3.0.3")
        self.assertIn("paths", self.spec)
        self.assertIn("components", self.spec)
        self.assertIn("info", self.spec)

    def test_every_path_has_operations(self):
        for path, ops in self.spec["paths"].items():
            self.assertTrue(ops, f"{path} has no operations")
            for method, op in ops.items():
                self.assertIn(method, ("get", "post", "put", "delete"))
                self.assertIn("responses", op)
                self.assertIn("summary", op)

    def test_decision_and_action_enums(self):
        approval = self.spec["paths"]["/api/approvals/{id}/{decision}"]
        decision_param = approval["post"]["parameters"][1]["schema"]["enum"]
        self.assertEqual(decision_param, ["approve", "deny"])
        quarantine = self.spec["paths"]["/api/quarantine/{id}/{action}"]
        action_param = quarantine["post"]["parameters"][1]["schema"]["enum"]
        self.assertEqual(action_param, ["release", "delete"])

    def test_task_create_requires_goal(self):
        body = self.spec["paths"]["/api/tasks"]["post"]["requestBody"]
        schema_ref = body["content"]["application/json"]["schema"]
        task_schema = self.spec["components"]["schemas"]["TaskCreate"]
        self.assertEqual(schema_ref["$ref"], "#/components/schemas/TaskCreate")
        self.assertIn("goal", task_schema["required"])

    def test_references_resolve(self):
        import json
        text = json.dumps(self.spec)
        import re
        for ref in set(re.findall(r'"\#/components/schemas/(\w+)"', text)):
            self.assertIn(ref, self.spec["components"]["schemas"],
                          f"dangling schema ref {ref}")

    def test_markdown_covers_all_paths(self):
        markdown = spec_markdown()
        for path in self.spec["paths"]:
            self.assertIn(path, markdown)


class SpecMatchesRouterTests(unittest.TestCase):
    def test_documented_paths_exist_in_web_app(self):
        from interface.web import build_web_app

        class _StubDaemon:
            pass

        built = build_web_app(_StubDaemon())  # routes only; nothing runs
        router_paths = {route.resource.canonical
                        for route in built.router.routes()}
        for path in build_spec()["paths"]:
            self.assertIn(path, router_paths,
                          f"documented path {path} missing from router")


if __name__ == "__main__":
    unittest.main()
