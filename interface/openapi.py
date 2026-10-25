"""OpenAPI 3.0 description of the dashboard API.

One source of truth for route metadata, served at ``/api/openapi.json``
and renderable to a compact markdown reference for docs. Kept hand-written
(next to the handlers it describes) and validated by tests that cross-check
it against the actual aiohttp router table.
"""

from __future__ import annotations

from typing import Any

OPENAPI_VERSION = "3.0.3"
SPARKAGENT_VERSION = "0.2.0"


def _json_response(description: str, schema: str = "object") -> dict:
    return {"description": description, "content": {"application/json": {
        "schema": {"$ref": f"#/components/schemas/{schema}"}}}}


def build_spec() -> dict[str, Any]:
    error_response = {"description": "error",
                      "content": {"application/json": {"schema": {
                          "$ref": "#/components/schemas/Error"}}}}
    return {
        "openapi": OPENAPI_VERSION,
        "info": {"title": "SparkAgent API",
                 "version": SPARKAGENT_VERSION,
                 "description": "Control plane for the 24/7 autonomous "
                                "agent: tasks, memory, skills, approvals, "
                                "quarantine, health, and metrics."},
        "servers": [{"url": "http://127.0.0.1:8788",
                     "description": "local dashboard (default)"}],
        "components": {"schemas": {
            "Error": {"type": "object",
                      "properties": {"error": {"type": "string"}}},
            "object": {"type": "object"},
            "Status": {"type": "object", "properties": {
                "agent": {"type": "string"},
                "version": {"type": "string"},
                "uptime_s": {"type": "integer"},
                "tools": {"type": "array", "items": {"type": "string"}},
                "approvals_pending": {"type": "array", "items": {}}}},
            "Task": {"type": "object", "properties": {
                "id": {"type": "integer"},
                "goal": {"type": "string"},
                "status": {"type": "string"},
                "enabled": {"type": "integer"}}},
            "TaskCreate": {"type": "object", "required": ["goal"],
                           "properties": {"goal": {"type": "string"},
                                          "interval_seconds": {
                                              "type": "integer",
                                              "minimum": 60},
                                          "depends_on": {
                                              "type": "array",
                                              "items": {"type": "integer",
                                                        "minimum": 1},
                                              "description": "task ids that "
                                                             "must finish "
                                                             "successfully "
                                                             "before this "
                                                             "task runs"}}},
            "Approval": {"type": "object", "properties": {
                "id": {"type": "string"},
                "kind": {"type": "string"},
                "summary": {"type": "string"},
                "status": {"type": "string"}}},
        }},
        "security": [{"bearerAuth": []}],
        "paths": {
            "/api/status": {"get": {
                "summary": "Daemon status",
                "responses": {"200": _json_response("Current status",
                                                    "Status")}}},
            "/api/tasks": {
                "get": {"summary": "List tasks", "responses": {
                    "200": _json_response("Task list")}},
                "post": {"summary": "Submit a task", "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "$ref": "#/components/schemas/TaskCreate"}}}},
                    "responses": {"201": _json_response("Created task"),
                                  "400": error_response}}},
            "/api/tasks/{id}/{action}": {"post": {
                "summary": "Cancel, pause, or resume a task",
                "parameters": [
                    {"name": "id", "in": "path", "required": True,
                     "schema": {"type": "integer"}},
                    {"name": "action", "in": "path", "required": True,
                     "schema": {"type": "string",
                                "enum": ["cancel", "pause", "resume"]}}],
                "responses": {"200": _json_response("Action applied"),
                              "400": error_response}}},
            "/api/episodes": {"get": {
                "summary": "Recent episodes",
                "parameters": [{"name": "limit", "in": "query",
                                "schema": {"type": "integer",
                                           "default": 20}}],
                "responses": {"200": _json_response("Episode list")}}},
            "/api/memories": {"get": {
                "summary": "Semantic memory recall",
                "parameters": [{"name": "q", "in": "query", "required": True,
                                "schema": {"type": "string"}}],
                "responses": {"200": _json_response("Ranked hits"),
                              "400": error_response}}},
            "/api/skills": {
                "get": {"summary": "List skills", "responses": {
                    "200": _json_response("Skills")}},
                "post": {"summary": "Create a skill (operator)", "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["name", "description", "code"],
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "parameters": {"type": "object"},
                            "code": {"type": "string"}}}}}},
                    "responses": {"201": _json_response("Skill created"),
                                  "400": error_response}}},
            "/api/skills/{name}/approve": {"post": {
                "summary": "Approve a pending skill (operator)",
                "parameters": [{"name": "name", "in": "path",
                                "required": True,
                                "schema": {"type": "string"}}],
                "responses": {"200": _json_response("Approved"),
                              "400": error_response}}},
            "/api/approvals": {"get": {
                "summary": "Approval queue", "responses": {
                    "200": _json_response("Pending + recent approvals",
                                          "Approval")}}},
            "/api/approvals/{id}/{decision}": {"post": {
                "summary": "Approve or deny a request (operator)",
                "parameters": [
                    {"name": "id", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                    {"name": "decision", "in": "path", "required": True,
                     "schema": {"type": "string", "enum": ["approve",
                                                           "deny"]}}],
                "responses": {"200": _json_response("Decision recorded"),
                              "400": error_response,
                              "404": error_response}}},
            "/api/quarantine": {"get": {
                "summary": "Quarantined content", "responses": {
                    "200": _json_response("Quarantine items")}}},
            "/api/quarantine/{id}/{action}": {"post": {
                "summary": "Release or delete quarantined content",
                "parameters": [
                    {"name": "id", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                    {"name": "action", "in": "path", "required": True,
                     "schema": {"type": "string",
                                "enum": ["release", "delete"]}}],
                "responses": {"200": _json_response("Action done"),
                              "404": error_response}}},
            "/api/health": {"get": {
                "summary": "Subsystem health checks", "responses": {
                    "200": _json_response("Health report")}}},
            "/api/audit": {"get": {
                "summary": "Audit trail (redacted)",
                "parameters": [{"name": "offset", "in": "query",
                                "schema": {"type": "integer"}},
                               {"name": "limit", "in": "query",
                                "schema": {"type": "integer"}}],
                "responses": {"200": _json_response("Audit rows")}}},
            "/api/version": {"get": {
                "summary": "Build/version info", "responses": {
                    "200": _json_response("Version payload")}}},
            "/api/brain": {"get": {
                "summary": "Brain observability — tier health, call stats, "
                           "cost ledger, daily budget",
                "responses": {"200": _json_response("Brain report")}}},
            "/metrics": {"get": {
                "summary": "Prometheus metrics", "responses": {
                    "200": {"description": "text/plain exposition"}}}},
            "/api/metrics": {"get": {
                "summary": "Metrics snapshot as JSON (counters, gauges, "
                           "histograms)",
                "responses": {"200": _json_response("Metrics snapshot")}}},
        },
    }


def spec_markdown() -> str:
    """Compact markdown table of all endpoints (for docs)."""
    spec = build_spec()
    lines = ["| Method | Path | Summary |", "|---|---|---|"]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            lines.append(f"| {method.upper()} | `{path}` | "
                         f"{op.get('summary', '')} |")
    return "\n".join(lines)
