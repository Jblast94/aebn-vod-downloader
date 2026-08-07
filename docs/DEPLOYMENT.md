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
AEBNDL_DB_PATH=/downloads/aebndl-jobs.db
AEBNDL_MAX_CONCURRENT_JOBS=1
AEBNDL_JOB_RETENTION_HOURS=0
AEBNDL_RUNPOD_ENDPOINT_URL=https://api.runpod.ai/v2/bfarkaz0uwuhcn
AEBNDL_RUNPOD_AUDIO_FIELD=audio_base64
AEBNDL_RUNPOD_UPLOAD_TIMEOUT=600
AEBNDL_SUBTITLE_CHUNK_MINUTES=10
AEBNDL_SUBTITLE_MAX_CHUNK_MB=50
AEBNDL_AUTO_SUBTITLES=true
AEBNDL_SUBTITLE_LANGUAGE=
RUNPOD_API_KEY=
TZ=America/New_York
```

Variables:

| Variable | Description |
| --- | --- |
| `AEBNDL_WEB_PORT` | Host port exposed for the web UI. |
| `AEBNDL_REMOTE_DOWNLOAD_DIR` | Host directory for completed downloads and cover files. |
| `AEBNDL_REMOTE_WORK_DIR` | Host directory for temporary segments and work files. |
| `AEBNDL_DB_PATH` | SQLite job history path inside the container. Defaults to `/downloads/aebndl-jobs.db`. |
| `AEBNDL_MAX_CONCURRENT_JOBS` | Maximum number of downloads allowed to run at the same time. Defaults to `1`. |
| `AEBNDL_JOB_RETENTION_HOURS` | Auto-prunes terminal jobs older than this many hours. `0` disables pruning. |
| `AEBNDL_RUNPOD_ENDPOINT_URL` | RunPod Faster-Whisper endpoint base URL. |
| `AEBNDL_RUNPOD_AUDIO_FIELD` | JSON input field used for the base64 audio payload. Defaults to `audio_base64`. |
| `AEBNDL_RUNPOD_UPLOAD_TIMEOUT` | Upload timeout, in seconds, for RunPod subtitle requests. |
| `AEBNDL_SUBTITLE_CHUNK_MINUTES` | Length of audio chunks sent to RunPod for long media files. |
| `AEBNDL_SUBTITLE_MAX_CHUNK_MB` | Maximum extracted audio chunk size before subtitle generation fails with guidance. |
| `AEBNDL_AUTO_SUBTITLES` | Enables automatic subtitle generation after downloads when `true`. |
| `AEBNDL_SUBTITLE_LANGUAGE` | Optional Whisper language hint. Leave empty for auto-detect. |
| `RUNPOD_API_KEY` | Required RunPod API key for subtitle generation. |
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
  - "docktail.service.name=aebn-dl"
  - "docktail.service.port=8787"
  - "docktail.service.service-protocol=http"
```

These identify the service as `aebn-dl` and point Docktail at the app's internal HTTP port `8787`.

## Storage Layout

Inside the container:

| Container path | Purpose |
| --- | --- |
| `/downloads` | Final output files and cover images. |
| `/work` | Temporary segments and intermediate files. |

Subtitle files are written beside completed media files in `/downloads` with the `.srt` extension. Job history is stored in SQLite at `AEBNDL_DB_PATH`.

## RunPod Subtitle Generation

The app calls RunPod Serverless using the configured endpoint:

```text
https://api.runpod.ai/v2/bfarkaz0uwuhcn
```

Set your API key before deploying:

```bash
RUNPOD_API_KEY=your_runpod_api_key docker compose up -d --build
```

Or place it in `.env`:

```env
RUNPOD_API_KEY=your_runpod_api_key
```

The key is passed into the container as an environment variable and is not displayed in the UI.

To disable automatic subtitles while keeping manual generation available:

```env
AEBNDL_AUTO_SUBTITLES=false
```

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
- The web UI history is persisted in SQLite. Restarting the container preserves completed job history when `AEBNDL_DB_PATH` is on a mounted volume.
- The player streams files for completed jobs loaded from SQLite when the output file still exists on disk.
