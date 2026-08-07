# aebn-vod-downloader

A Python downloader for AEBN VOD titles with both a CLI and a local web UI. The current project setup uses `uv` for Python dependency management and Docker Compose for container deployment.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/hyper440/aebn-vod-downloader/blob/main/colab.ipynb)

## Features

- CLI command: `aebndl`
- Web UI command: `aebndl-web`
- Movie info preview before downloading
- Background download jobs with live status and logs
- Persistent completed-download history backed by SQLite
- Configurable download queue and job concurrency limit
- Job cancel/delete actions and clear-completed cleanup
- URL list upload for starting one queued job per URL
- Integrated browser video player for completed output files
- Automated `.srt` subtitle generation with a RunPod Faster-Whisper endpoint
- Docker Compose deployment with mounted download/work directories
- Docktail labels for service discovery/tagging in a Tailscale tailnet

## Requirements

- Python 3.8 or higher for local CLI usage
- `uv` for Python package management
- FFmpeg in `PATH` for local runs
- Docker and Docker Compose for container deployment

The Docker image installs FFmpeg automatically.

## Local Setup With uv

Install dependencies:

```bash
uv sync
```

Run the CLI:

```bash
uv run aebndl "https://*.aebn.com/*/movies/*" --resolution 720 --scene 2
```

Run the web UI:

```bash
uv run aebndl-web
```

Open the app at:

```text
http://127.0.0.1:8787
```

## Docker Compose

The compose deployment runs the web UI and mounts host download locations into the container.

Start the service:

```bash
docker compose up -d --build
```

Open the app at:

```text
http://localhost:8787
```

Stop the service:

```bash
docker compose down
```

## Environment

The project includes a `.env` file for Docker Compose.

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

Environment variables:

| Variable | Purpose |
| --- | --- |
| `AEBNDL_WEB_PORT` | Host port mapped to the web UI container port `8787`. |
| `AEBNDL_REMOTE_DOWNLOAD_DIR` | Host path mounted into the container as `/downloads`. |
| `AEBNDL_REMOTE_WORK_DIR` | Host path mounted into the container as `/work`. |
| `AEBNDL_DB_PATH` | SQLite job history path inside the container. Defaults to `/downloads/aebndl-jobs.db`. |
| `AEBNDL_MAX_CONCURRENT_JOBS` | Maximum number of downloads allowed to run at the same time. Defaults to `1`. |
| `AEBNDL_JOB_RETENTION_HOURS` | Auto-prunes completed/failed/cancelled jobs older than this many hours. `0` disables pruning. |
| `AEBNDL_RUNPOD_ENDPOINT_URL` | RunPod Faster-Whisper endpoint base URL. |
| `AEBNDL_RUNPOD_AUDIO_FIELD` | JSON input field used for the base64 audio payload. Defaults to `audio_base64`. |
| `AEBNDL_RUNPOD_UPLOAD_TIMEOUT` | Upload timeout, in seconds, for RunPod subtitle requests. |
| `AEBNDL_SUBTITLE_CHUNK_MINUTES` | Length of audio chunks sent to RunPod for long media files. |
| `AEBNDL_SUBTITLE_MAX_CHUNK_MB` | Maximum extracted audio chunk size before subtitle generation fails with guidance. |
| `AEBNDL_AUTO_SUBTITLES` | Enables automatic subtitle generation after downloads when `true`. |
| `AEBNDL_SUBTITLE_LANGUAGE` | Optional Whisper language hint. Leave empty for auto-detect. |
| `RUNPOD_API_KEY` | Required RunPod API key for subtitle generation. |
| `TZ` | Container timezone, using a valid TZ database name such as `America/New_York`. |

Inside the container, the web UI uses `/downloads` as the default output directory and `/work` as the default temporary work directory.

## Docktail Labels

`docker-compose.yml` includes labels for Docktail service discovery/tagging:

```yaml
labels:
  - "docktail.service.enable=true"
  - "docktail.service.name=aebn-dl"
  - "docktail.service.port=8787"
  - "docktail.service.service-protocol=http"
```

## User Guides

- [Web UI User Guide](docs/USER_GUIDE.md)
- [Deployment Guide](docs/DEPLOYMENT.md)

## CLI Arguments

| Flags | Argument | Description |
| --- | --- | --- |
| | `URL` | URL of the movie or `list.txt`. |
| `-o` | `--output_dir` | Specify the output directory. |
| `-w` | `--work_dir` | Specify the work directory for temporary downloaded segments. |
| `-i` | `--info` | Print full movie and segment info without downloading. |
| `-r` | `--resolution` | Desired video resolution by pixel height. If unavailable, the nearest lower resolution is used. Use `0` for the lowest available resolution. Defaults to highest available. |
| `-f` | `--force-resolution` | Exit with an error if the target resolution is unavailable. |
| `-n` | `--names` | Include performer names in the output filename. |
| `-nm` | `--no-metadata` | Disable title and chapter metadata embedding. |
| `-s` | `--scene` | Download a single scene by scene number. |
| | `--split-scenes` | Download and save each scene as a separate file. |
| `-ss` | `--start-segment` | Specify the start segment. |
| `-es` | `--end-segment` | Specify the end segment. |
| `-p` | `--proxy` | Proxy to use, for example `protocol://username:password@ip:port`. |
| `-pm` | `--proxy-metadata` | Use the proxy for metadata only, not downloading. |
| `-c` | `--covers` | Download front and back covers. |
| `-ow` | `--overwrite` | Overwrite existing audio and video segments. |
| `-ts` | `--target-stream` | Download only `audio` or only `video`. |
| `-ks` | `--keep-segments` | Keep audio and video segments after downloading. |
| `-kl` | `--keep-logs` | Keep logs after successful exit. |
| `-ac` | `--aggressive-cleaning` | Delete segments as soon as they are joined into streams. |
| `-t` | `--threads` | Number of download threads. Defaults to `5`. |
| `-l` | `--log-level` | Logging level. Defaults to `INFO`. |

## Notes

- Web UI history is persisted in SQLite at `AEBNDL_DB_PATH`.
- The integrated video player can only play completed output files that still exist on disk.
- Subtitle generation requires `RUNPOD_API_KEY`; leave `AEBNDL_AUTO_SUBTITLES=false` to disable automatic transcription.
- Use `uv run --extra dev ruff check .` to run lint checks.
