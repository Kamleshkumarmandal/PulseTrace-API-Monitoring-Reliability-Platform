import unittest

from fastapi.testclient import TestClient

from pulsetrace.api import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_probe_rejects_non_https_targets(self):
        response = self.client.post("/api/v1/probe", json={"target": "http://example.com"})
        self.assertEqual(response.status_code, 422)

    def test_probe_rejects_credentials_in_url(self):
        response = self.client.post("/api/v1/probe", json={"target": "https://user:pass@example.com"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
