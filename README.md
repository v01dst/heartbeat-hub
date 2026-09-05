<div align="center">

# 💓 heartbeat-hub

**Dead man's switch for your cron jobs. When silence means failure, get told.**

[![CI](https://github.com/v01dst/heartbeat-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/v01dst/heartbeat-hub/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-MIT-8A2BE2)
![Python](https://img.shields.io/badge/python-3.14-3776AB?logo=python&logoColor=white)
![Deps](https://img.shields.io/badge/dependencies-stdlib%20only-00c853)
![Tests](https://img.shields.io/badge/tests-7%20passing-brightgreen)

`cron monitoring` · `backup watchdog` · `worker liveness` · `zero dependencies`
</div>

---

## ✨ Features

- **📴 Silence detection** — every source has a period + grace window; go quiet → flagged `DOWN`
- **🎚️ 4 states** — `new`, `up`, `grace`, `down` per source
- **🔔 Webhook alerts** — configure `ALERT_WEBHOOK` to receive JSON alerts
- **🗄️ Persistent history** — SQLite, auto-pruned to the last 100 pings per source
- **🪶 Pure stdlib** — zero pip dependencies, runs on any Python ≥ 3.10
- **🐳 One-command deploy** — Docker with persistent volume

## 🚀 Quick Start

```bash
git clone https://github.com/v01dst/heartbeat-hub
cd heartbeat-hub
python3 -m app.main
```

Or with Docker:

```bash
docker compose up -d
```

## 📡 API

| Method   | Route          | Description                    |
|----------|----------------|--------------------------------|
| `POST`   | `/sources`     | Register a monitored source    |
| `GET`    | `/sources`     | List all with live status      |
| `GET`    | `/status/:key` | One source's status            |
| `POST`   | `/ping/:key`   | Record a heartbeat             |
| `DELETE` | `/sources/:key`| Remove a source                |
| `GET`    | `/health`      | Liveness                       |

### Register a source

```bash
curl -X POST http://localhost:3000/sources \
  -H 'content-type: application/json' \
  -d '{"name": "nightly-backup", "period": 86400, "grace": 3600}'
```

```json
{
  "key": "DAYDB6jgu-v24rtyrdFIxQ",
  "name": "nightly-backup",
  "period": 86400,
  "grace": 3600,
  "pingUrl": "/ping/DAYDB6jgu-v24rtyrdFIxQ"
}
```

### Ping it (from cron)

```bash
# crontab: 0 2 * * *  /run/backup.sh && curl -fsS http://hub:3000/ping/DAYDB6jgu-v24rtyrdFIxQ
curl -X POST http://localhost:3000/ping/DAYDB6jgu-v24rtyrdFIxQ
```

```json
{ "ok": true, "status": "up" }
```

### Check status

```bash
curl http://localhost:3000/status/DAYDB6jgu-v24rtyrdFIxQ
```

```json
{
  "key": "DAYDB6jgu-v24rtyrdFIxQ",
  "name": "nightly-backup",
  "period": 86400,
  "grace": 3600,
  "status": "up",
  "lastPingSecAgo": 941,
  "totalPings": 2
}
```

## ⚙️ Configuration

| Variable        | Default                | Description                       |
|-----------------|------------------------|-----------------------------------|
| `PORT`          | `3000`                 | Listen port                       |
| `DB_PATH`       | `./data/heartbeats.db` | SQLite file                       |
| `ALERT_WEBHOOK` | *(empty)*              | URL to POST JSON alerts to        |

## 🧱 Tech Stack

| Layer     | Tech                       |
|-----------|----------------------------|
| Runtime   | Python ≥ 3.10 (stdlib only)|
| Server    | http.server (threaded)     |
| Storage   | SQLite (WAL)               |
| Testing   | unittest                   |
| Packaging | Docker + compose           |
| CI        | GitHub Actions             |

---

<div align="center">

Built with ⚡ by **v01dst**

[![GitHub](https://img.shields.io/badge/github-v01dst-181717?logo=github)](https://github.com/v01dst)
[![Discord](https://img.shields.io/badge/discord-9p.1-5865F2?logo=discord&logoColor=white)](https://discord.com/users/9p.1)

</div>
