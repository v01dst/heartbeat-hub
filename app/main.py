"""Heartbeat Hub — dead man's switch for cron jobs and background workers.

Pure Python stdlib. Sources ping HTTP endpoints; if a source goes silent
past its grace period, it is flagged DOWN and alerts fire.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

DB_PATH = os.environ.get("DB_PATH", "./data/heartbeats.db")
PORT = int(os.environ.get("PORT", "3000"))
ALERT_WEBHOOK = os.environ.get("ALERT_WEBHOOK", "")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    period_seconds INTEGER NOT NULL,
    grace_seconds INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL REFERENCES sources(key) ON DELETE CASCADE,
    received_at TEXT NOT NULL,
    epoch REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pings_key ON pings(key);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def create_source(self, key: str, name: str, period: int, grace: int) -> dict[str, Any]:
        self.db.execute(
            "INSERT INTO sources (key, name, period_seconds, grace_seconds, created_at) VALUES (?, ?, ?, ?, ?)",
            (key, name, period, grace, utcnow_iso()),
        )
        self.db.commit()
        return {"key": key, "name": name, "period": period, "grace": grace}

    def get_source(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT key, name, period_seconds, grace_seconds FROM sources WHERE key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        return {"key": row[0], "name": row[1], "period": row[2], "grace": row[3]}

    def delete_source(self, key: str) -> bool:
        cur = self.db.execute("DELETE FROM sources WHERE key = ?", (key,))
        self.db.commit()
        return cur.rowcount > 0

    def list_sources(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT key, name, period_seconds, grace_seconds FROM sources ORDER BY key"
        ).fetchall()
        return [
            {"key": r[0], "name": r[1], "period": r[2], "grace": r[3]} for r in rows
        ]

    def record_ping(self, key: str, epoch: float) -> None:
        self.db.execute(
            "INSERT INTO pings (key, received_at, epoch) VALUES (?, ?, ?)",
            (key, utcnow_iso(), epoch),
        )
        self.db.commit()

    def last_ping_epoch(self, key: str) -> float | None:
        row = self.db.execute(
            "SELECT epoch FROM pings WHERE key = ? ORDER BY id DESC LIMIT 1",
            (key,),
        ).fetchone()
        return float(row[0]) if row else None

    def ping_count(self, key: str) -> int:
        return int(
            self.db.execute(
                "SELECT COUNT(*) FROM pings WHERE key = ?", (key,)
            ).fetchone()[0]
        )

    def prune_pings(self, key: str, keep: int = 100) -> None:
        self.db.execute(
            "DELETE FROM pings WHERE key = ? AND id NOT IN "
            "(SELECT id FROM pings WHERE key = ? ORDER BY id DESC LIMIT ?)",
            (key, key, keep),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()


def source_status(source: dict[str, Any], last_epoch: float | None, now: float) -> str:
    if last_epoch is None:
        return "new"
    age = now - last_epoch
    if age <= source["period"]:
        return "up"
    if age <= source["period"] + source["grace"]:
        return "grace"
    return "down"


def generate_key() -> str:
    import secrets

    return secrets.token_urlsafe(16)


def send_alert(message: str) -> None:
    """POST a JSON alert to ALERT_WEBHOOK if configured. Never raises."""
    if not ALERT_WEBHOOK:
        return
    try:
        from urllib.request import Request, urlopen

        req = Request(
            ALERT_WEBHOOK,
            data=json.dumps({"text": message}).encode(),
            headers={"content-type": "application/json"},
        )
        urlopen(req, timeout=5)
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = "heartbeat-hub/1.0.0"

    store: Store  # set by serve()

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter logs
        print(f"{self.address_string()} - {fmt % args}")

    def _json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length") or 0)
        if length <= 0 or length > 64 * 1024:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        now = time.time()

        if path == "/":
            self._json(
                200,
                {
                    "service": "heartbeat-hub",
                    "version": "1.0.0",
                    "author": "v01dst",
                },
            )
        elif path == "/health":
            self._json(200, {"status": "ok", "uptimeSec": int(now - STARTED_AT)})
        elif path == "/sources":
            sources = []
            for s in self.store.list_sources():
                last = self.store.last_ping_epoch(s["key"])
                entry = dict(s)
                entry["status"] = source_status(s, last, now)
                entry["lastPingSecAgo"] = int(now - last) if last else None
                entry["totalPings"] = self.store.ping_count(s["key"])
                sources.append(entry)
            self._json(200, {"sources": sources})
        elif path.startswith("/status/"):
            key = path.split("/")[2]
            src = self.store.get_source(key)
            if not src:
                self._json(404, {"error": f"unknown source '{key}'"})
                return
            last = self.store.last_ping_epoch(key)
            self._json(
                200,
                {
                    **src,
                    "status": source_status(src, last, now),
                    "lastPingSecAgo": int(now - last) if last else None,
                    "totalPings": self.store.ping_count(key),
                },
            )
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        now = time.time()

        if path == "/sources":
            body = self._read_json()
            name = body.get("name")
            if not name:
                self._json(400, {"error": "name is required"})
                return
            period = body.get("period", 3600)
            grace = body.get("grace", period // 4)
            if not isinstance(period, int) or period < 30 or period > 2_592_000:
                self._json(400, {"error": "period must be int in [30, 2592000]"})
                return
            if not isinstance(grace, int) or grace < 0 or grace > 86_400:
                self._json(400, {"error": "grace must be int in [0, 86400]"})
                return
            key = generate_key()
            src = self.store.create_source(key, str(name), period, grace)
            self._json(201, {**src, "pingUrl": f"/ping/{key}"})
        elif path.startswith("/ping/"):
            key = path.split("/")[2]
            src = self.store.get_source(key)
            if not src:
                self._json(404, {"error": f"unknown source '{key}'"})
                return
            self.store.record_ping(key, now)
            self.store.prune_pings(key)
            send_alert(f"[heartbeat-hub] UP: {src['name']} pinged")
            self._json(200, {"ok": True, "status": "up"})
        else:
            self._json(404, {"error": "not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        if path.startswith("/sources/"):
            key = path.split("/")[2]
            if self.store.delete_source(key):
                self._json(200, {"deleted": key})
            else:
                self._json(404, {"error": f"unknown source '{key}'"})
        else:
            self._json(404, {"error": "not found"})


STARTED_AT = time.time()


def serve(store: Store | None = None, port: int = PORT) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"store": store or Store()})
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    return server


def main() -> None:
    server = serve(Store(DB_PATH), PORT)
    print(f"heartbeat-hub listening on :{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
