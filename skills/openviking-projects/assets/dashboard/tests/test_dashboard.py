"""Regression checks for credential boundaries and truthful freshness reporting."""
import asyncio
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class DashboardBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "state"
        self.workspace = self.base / "workspace"
        self.root = self.home / "projects/demo"
        for path in [self.home / "configs", self.root / "configs", self.root / "evidence", self.root / "curated", self.workspace]:
            path.mkdir(parents=True)
        self.patch = patch.object(server, "HOME", self.home)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.key = 'local-key-with-a-quote-"-and-newline\nprivate'
        self.write(self.home / "configs/provider-keys.json", {"OVK_SUMMARY_KEY": self.key})
        (self.home / "configs/root.key").write_text("local-root-secret-with-no-provider-access")
        self.write(self.home / "configs/projects.json", {"projects": {"demo": {"data_root": str(self.root), "workspace_roots": [str(self.workspace)], "scope": "viking://resources/projects/demo/current", "account": "project-demo"}}})
        self.source = self.workspace / "README.md"
        self.source.write_text("# Fixture\n\nCurrent source.\n")
        self.policy = {"project": str(self.workspace), "source_policy_text": "Fixture evidence", "sources": [{"path": "README.md", "file": "01-README.md", "role": "current-status", "selector": {"mode": "full"}}]}
        self.write(self.root / "configs/pilot-policy.json", self.policy)
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        rule_hash = hashlib.sha256(b"Fixture evidence").hexdigest()
        (self.root / "curated/01-README.md").write_bytes(self.source.read_bytes())
        (self.root / "curated/00-source-policy.md").write_text("Fixture evidence")
        self.write(self.root / "evidence/source-manifest.json", {"snapshot_id": "fixture-snapshot", "curated_directory": str(self.root / "curated"), "sources": [{"source_id": "01-README", "source_path": str(self.source), "source_sha256": source_hash, "curated_file": "01-README.md", "selector": {"mode": "full"}}]})
        self.write(self.root / "evidence/import-receipt.json", {"snapshot_id": "fixture-snapshot", "fingerprints": {"01-README.md": source_hash, "00-source-policy.md": rule_hash}})
        self.write(self.root / "evidence/mcp-check.json", {"passed": True, "snapshot_id": "fixture-snapshot"})
        self.client = TestClient(server.app, base_url="http://127.0.0.1")
        self.addCleanup(self.client.close)

    def write(self, path, value):
        path.write_text(json.dumps(value))

    def test_changed_source_invalidates_displayed_verification(self):
        self.assertEqual(server.source_state("demo")["name"], "demo")
        self.assertTrue(server.source_state("demo")["mcp_verified"])
        self.source.write_text("# Fixture\n\nA meaningful source change.\n")
        state = server.source_state("demo")
        self.assertEqual(state["changed_count"], 1)
        self.assertFalse(state["mcp_verified"])

    def test_rule_change_invalidates_freshness_without_source_change(self):
        self.policy["source_policy_text"] = "Updated evidence boundary"
        self.write(self.root / "configs/pilot-policy.json", self.policy)
        state = server.source_state("demo")
        self.assertEqual(state["changed_count"], 0)
        self.assertTrue(state["configuration_changed"])
        self.assertFalse(state["mcp_verified"])

    def test_tampered_curated_text_is_flagged(self):
        (self.root / "curated/01-README.md").write_text("External modification")
        state = server.source_state("demo")
        self.assertIsNotNone(state["index_error"])
        self.assertFalse(state["mcp_verified"])

    def test_source_preview_is_whitelisted_and_redacts_credentials(self):
        self.source.write_text("# Fixture\n" + self.key)
        with patch.dict(sys.modules, {"source_selection": type("Selection", (), {"select_text": staticmethod(lambda text, selector: (text, [[1, 3]]))})}):
            response = self.client.get("/api/projects/demo/source/01-README")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.key, response.json()["content"])
        self.assertIn("[已隐藏]", response.json()["content"])
        self.assertEqual(self.client.get("/api/projects/demo/source/not-registered").status_code, 404)
        self.assertEqual(self.client.get("/api/projects/unknown/source/01-README").status_code, 404)

    def test_cross_site_requests_and_rebinding_host_are_blocked(self):
        response = self.client.post("/api/search", headers={"Origin": "https://example.com"}, json={"project_code": "demo", "query": "anything"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/events", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.get("/health", headers={"Host": "attacker.example"}).status_code, 400)

    def test_declared_source_cannot_escape_its_workspace(self):
        (self.base / "outside.txt").write_text("Outside project scope")
        self.policy["sources"][0]["path"] = "../outside.txt"
        self.write(self.root / "configs/pilot-policy.json", self.policy)
        state = server.source_state("demo")
        self.assertEqual(state["sources"][0]["status"], "blocked")
        self.assertEqual(self.client.get("/api/projects/demo/source/01-README.md").status_code, 409)

    def test_native_connection_failure_is_not_reported_as_zero(self):
        async def run():
            transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"detail": "denied"}))
            with patch.object(server, "service_url", return_value="http://127.0.0.1:1933"):
                async with httpx.AsyncClient(transport=transport) as client:
                    return await server.native(client, "/health")
        result = asyncio.run(run())
        self.assertFalse(result["available"])
        self.assertNotIn("data", result)
        self.assertIn("401", result["error"])

    def test_no_write_or_generic_proxy_endpoint(self):
        self.assertEqual(self.client.post("/api/projects/demo/sync").status_code, 404)
        self.assertEqual(self.client.get("/api/proxy?url=http://example.com").status_code, 404)
        self.assertEqual(self.client.delete("/api/projects/demo/source/01-README").status_code, 405)

    def test_corrupt_project_policy_is_not_reported_as_zero_sources(self):
        (self.root / "configs/pilot-policy.json").write_text("{broken")
        with self.assertRaises(ValueError):
            server.source_state("demo")
        self.assertEqual(self.client.get("/api/projects/demo/source/01-README").status_code, 409)

    def test_corrupt_registry_is_not_reported_as_an_empty_registry(self):
        (self.home / "configs/projects.json").write_text("[]")
        with self.assertRaises(server.HTTPException) as error:
            server.entries()
        self.assertEqual(error.exception.status_code, 503)

    def test_invalid_source_selector_returns_actionable_conflict(self):
        def reject(text, selector):
            raise ValueError("Missing section")
        with patch.dict(sys.modules, {"source_selection": type("Selection", (), {"select_text": staticmethod(reject)})}):
            response = self.client.get("/api/projects/demo/source/01-README")
        self.assertEqual(response.status_code, 409)
        self.assertIn("选区已变化", response.json()["detail"])

    def test_blank_search_is_rejected_before_starting_a_worker(self):
        response = self.client.post("/api/search", json={"project_code": "demo", "query": " \n\t "})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(server.SearchInput(project_code="demo", query="  useful query  ").query, "useful query")

    def test_bad_project_path_does_not_escape_native_error_handling(self):
        self.write(self.home / "configs/projects.json", {"projects": {"demo": {"data_root": str(self.base / "outside")}}})
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
                return await server.native(client, "/health", "demo")
        self.assertFalse(asyncio.run(run())["available"])

    def test_validation_usage_is_included_only_when_requested(self):
        registry = server.entries()
        self.write(self.home / "configs/projects.json", {"projects": {**registry, "setup-check": registry["demo"]}})
        async def native(client, path, code=None):
            return {"available": True, "data": {"items": [{"date": "2026-11-07", "vlm_input": 10, "vlm_output": 2, "embedding_input": 1}]}}
        with patch.object(server, "native", native):
            business = self.client.get("/api/tokens").json()
            all_projects = self.client.get("/api/tokens?include_validation=true").json()
        self.assertEqual(business["items"][0]["vlm_input"], 10)
        self.assertEqual(all_projects["items"][0]["vlm_input"], 20)


if __name__ == "__main__":
    unittest.main()
