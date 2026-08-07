# Deployment Guide

This guide covers Docker Compose deployment for the AEBN downloader web UI.

## Files

| File | Purpose |
| --- | --- |
| `Dockerfile` | Builds the app image with `uv`, Python, and FFmpeg. |
| `docker-compose.yml` | Runs the web UI service and mounts output/work directories. |
| `.env` | Sets host paths, host port, and timezone for Compose. |
| `.env.example` | Safe template for new environments. |

## Environment Configuration

Default `.env`:

```env
AEBNDL_WEB_PORT=8787
AEBNDL_REMOTE_DOWNLOAD_DIR=/mnt/storage/downloads
AEBNDL_REMOTE_WORK_DIR=/mnt/storage/downloads/aebndl-work
TZ=America/New_York
```

Variables:

| Variable | Description |
| --- | --- |
| `AEBNDL_WEB_PORT` | Host port exposed for the web UI. |
| `AEBNDL_REMOTE_DOWNLOAD_DIR` | Host directory for completed downloads and cover files. |
| `AEBNDL_REMOTE_WORK_DIR` | Host directory for temporary segments and work files. |
| `TZ` | Container timezone. Use a valid TZ name such as `America/New_York`. |

Create the host directories if they do not exist:

```bash
mkdir -p /mnt/storage/downloads /mnt/storage/downloads/aebndl-work
```

## Deploy

Build and start:

```bash
docker compose up -d --build
```

Check status:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs -f aebndl-web
```

Stop:

```bash
docker compose down
```

## Network Access

The container listens on `0.0.0.0:8787` internally. Compose maps that to the host port from `AEBNDL_WEB_PORT`.

Default URL:

```text
http://localhost:8787
```

For Tailnet access, use the hostname or service address provided by your Tailscale/Docktail setup.

## Docktail Service Labels

The compose file includes these labels:

```yaml
labels:
  - "docktail.service.enable=true"
  - "docktail.service.name=aebn"
  - "docktail.service.port=8787"
  - "docktail.service.service-port=443"
```

These identify the service as `aebn`, point Docktail at the app's internal port `8787`, and publish it through service port `443` when supported by your Docktail setup.

## Storage Layout

Inside the container:

| Container path | Purpose |
| --- | --- |
| `/downloads` | Final output files and cover images. |
| `/work` | Temporary segments and intermediate files. |

On the host, these come from `.env`:

| Host variable | Default path |
| --- | --- |
| `AEBNDL_REMOTE_DOWNLOAD_DIR` | `/mnt/storage/downloads` |
| `AEBNDL_REMOTE_WORK_DIR` | `/mnt/storage/downloads/aebndl-work` |

## Validation

Validate Compose syntax:

```bash
docker compose config
```

Validate Python code locally:

```bash
uv run --extra dev ruff check .
uv run python -m compileall aebn_dl
```

## Operational Notes

- Keep `/work` on storage with enough free space for temporary audio/video segments.
- If a remote mount is slow, consider keeping `/work` on fast local storage and `/downloads` on remote storage.
- The web UI history is in-memory. Restarting the container clears the visible history, but downloaded files remain in `/downloads`.
- The player streams files only if they were produced by completed jobs still tracked by the running app process.
