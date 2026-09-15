# Deployment Guide

MVP deploy is a **single Compose service on one Linux VM**. Full run steps live in the [README](../README.md). This page is a short companion.

## Files

| File | Purpose |
| --- | --- |
| `Dockerfile` | Builds the app image with `uv`, Python, and FFmpeg. |
| `docker-compose.yml` | One `aebndl-web` service. Local bind mounts. Healthcheck. |
| `.env.example` | Safe template. Copy to `.env` on the VM. |
| `.env` | Host paths and port. Do not commit secrets. There are none required for MVP. |

## Paths

| Container | VM default | Optional dedicated disk |
| --- | --- | --- |
| `/downloads` | `./downloads` | `/data/downloads` |
| `/work` | `./work` | `/data/aebndl-work` |

Set host binds with `AEBNDL_DOWNLOAD_DIR` and `AEBNDL_SEGMENT_DIR`. Homelab NFS is **not** part of this MVP.

```bash
mkdir -p downloads work
cp .env.example .env
docker compose up -d --build
curl -sf http://127.0.0.1:8787/health
```

## Environment

| Variable | Description |
| --- | --- |
| `AEBNDL_WEB_PORT` | Host port for the web UI. Default `8787`. |
| `AEBNDL_DOWNLOAD_DIR` | Host directory for completed media. Default `./downloads`. |
| `AEBNDL_SEGMENT_DIR` | Host directory for temporary segments. Default `./work`. |
| `AEBNDL_DB_PATH` | SQLite path **inside** the container. Default `/downloads/aebndl-jobs.db`. |
| `AEBNDL_MAX_CONCURRENT_JOBS` | Parallel title downloads. Default `1`. |
| `AEBNDL_JOB_RETENTION_HOURS` | Prune terminal jobs older than this. `0` disables. |
| `TZ` | Container timezone. |

No API keys are required to start or download.

## Health

`GET /health` must return `"status": "ok"`. Compose uses that endpoint as a healthcheck.

## Out of scope for MVP

- RunPod / remote subtitle workers
- Extra worker containers
- Stash or Jellyfin API integration (watch the download folder later; see README)

## Validation

```bash
docker compose config
uv run --extra dev ruff check .
uv run python -m compileall aebn_dl
```
