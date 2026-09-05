import json
import time
import unittest
from unittest.mock import patch

from app.main import Handler, Store, generate_key, serve, source_status
from http.client import HTTPConnection
from threading import Thread


def make_key(prefix: str) -> str:
    return f"{prefix}{generate_key()[:8]}"


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:")
        self.server = serve(self.store, port=0)
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.store.close()

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        headers = {"content-type": "application/json"} if body is not None else {}
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, json.loads(data) if data else {}

    def test_root_and_health(self) -> None:
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body["service"], "heartbeat-hub")
        status, body = self.request("GET", "/health")
        self.assertEqual(body["status"], "ok")

    def test_create_source_and_ping_cycle(self) -> None:
        status, body = self.request(
            "POST", "/sources", {"name": "nightly-backup", "period": 60, "grace": 30}
        )
        self.assertEqual(status, 201)
        key = body["key"]
        self.assertTrue(body["pingUrl"].startswith("/ping/"))

        status, body = self.request("GET", f"/ping/{key}" [1:] if False else f"/ping/{key}")
        # GET on ping should 404 (pings are POST)
        self.assertEqual(status, 404)

        status, body = self.request("POST", f"/ping/{key}")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "up")

        status, body = self.request("GET", f"/status/{key}")
        self.assertEqual(body["status"], "up")
        self.assertEqual(body["totalPings"], 1)
        self.assertEqual(body["lastPingSecAgo"], 0)

    def test_unknown_ping_404(self) -> None:
        status, body = self.request("POST", "/ping/does-not-exist")
        self.assertEqual(status, 404)

    def test_status_states(self) -> None:
        key = make_key("k")
        self.store.create_source(key, "job", period=60, grace=10)

        self.assertEqual(source_status({"period": 60, "grace": 10}, None, time.time()), "new")

        now = time.time()
        self.assertEqual(source_status({"period": 60, "grace": 10}, now - 10, now), "up")
        self.assertEqual(source_status({"period": 60, "grace": 10}, now - 65, now), "grace")
        self.assertEqual(source_status({"period": 60, "grace": 10}, now - 100, now), "down")

    def test_validation(self) -> None:
        status, body = self.request("POST", "/sources", {})
        self.assertEqual(status, 400)
        self.assertIn("name", body["error"])

        status, _ = self.request("POST", "/sources", {"name": "x", "period": 5})
        self.assertEqual(status, 400)

        status, _ = self.request("POST", "/sources", {"name": "x", "grace": -1})
        self.assertEqual(status, 400)

    def test_list_and_delete(self) -> None:
        _, body = self.request("POST", "/sources", {"name": "a"})
        key = body["key"]

        status, body = self.request("GET", "/sources")
        self.assertEqual(status, 200)
        self.assertTrue(any(s["key"] == key for s in body["sources"]))

        status, body = self.request("DELETE", f"/sources/{key}")
        self.assertEqual(status, 200)

        status, _ = self.request("DELETE", f"/sources/{key}")
        self.assertEqual(status, 404)

    def test_prune_keeps_recent_pings(self) -> None:
        key = make_key("p")
        self.store.create_source(key, "chatty", 30, 5)
        for i in range(150):
            self.store.record_ping(key, time.time() + i * 0.001)
        self.store.prune_pings(key, keep=100)
        self.assertEqual(self.store.ping_count(key), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)

class PatchSourceTests(ApiTestCase):

    def test_patch_period_and_grace(self):
        _, created = self.request("POST", "/sources", {"name": "job", "period": 60, "grace": 10})
        key = created["key"]
        status, body = self.request("PATCH", f"/sources/{key}", {"period": 120, "grace": 30})
        self.assertEqual(status, 200)
        self.assertEqual(body["period"], 120)
        self.assertEqual(body["grace"], 30)
        self.assertEqual(body["name"], "job")

    def test_patch_name(self):
        _, created = self.request("POST", "/sources", {"name": "job"})
        key = created["key"]
        status, body = self.request("PATCH", f"/sources/{key}", {"name": "renamed"})
        self.assertEqual(status, 200)
        self.assertEqual(body["name"], "renamed")

    def test_patch_unknown_404(self):
        status, _ = self.request("PATCH", "/sources/nope", {"name": "x"})
        self.assertEqual(status, 404)

    def test_patch_validation(self):
        _, created = self.request("POST", "/sources", {"name": "v"})
        key = created["key"]
        status, _ = self.request("PATCH", f"/sources/{key}", {"period": 5})
        self.assertEqual(status, 400)
        status, _ = self.request("PATCH", f"/sources/{key}", {"grace": -2})
        self.assertEqual(status, 400)
        status, _ = self.request("PATCH", f"/sources/{key}", {"name": "  "})
        self.assertEqual(status, 400)

class HistoryTests(ApiTestCase):
    def test_history_endpoint(self):
        _, created = self.request("POST", "/sources", {"name": "hist"})
        key = created["key"]
        for _ in range(3):
            self.request("POST", f"/ping/{key}")
        status, body = self.request("GET", f"/sources/{key}/history")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["history"]), 3)
        self.assertTrue(all("receivedAt" in h and "secAgo" in h for h in body["history"]))

    def test_history_limit(self):
        _, created = self.request("POST", "/sources", {"name": "hist2"})
        key = created["key"]
        for _ in range(5):
            self.request("POST", f"/ping/{key}")
        status, body = self.request("GET", f"/sources/{key}/history?limit=2")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["history"]), 2)

    def test_history_unknown_source_404(self):
        status, _ = self.request("GET", "/sources/nope/history")
        self.assertEqual(status, 404)
