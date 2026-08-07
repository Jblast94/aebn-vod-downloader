# aebn-vod-downloader

A Python downloader for AEBN VOD titles with both a CLI and a local web UI. The current project setup uses `uv` for Python dependency management and Docker Compose for container deployment.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/hyper440/aebn-vod-downloader/blob/main/colab.ipynb)

## Features

- CLI command: `aebndl`
- Web UI command: `aebndl-web`
- Movie info preview before downloading
- Background download jobs with live status and logs
- Completed-download history list
- Integrated browser video player for completed output files
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
TZ=America/New_York
```

Environment variables:

| Variable | Purpose |
| --- | --- |
| `AEBNDL_WEB_PORT` | Host port mapped to the web UI container port `8787`. |
| `AEBNDL_REMOTE_DOWNLOAD_DIR` | Host path mounted into the container as `/downloads`. |
| `AEBNDL_REMOTE_WORK_DIR` | Host path mounted into the container as `/work`. |
| `TZ` | Container timezone, using a valid TZ database name such as `America/New_York`. |

Inside the container, the web UI uses `/downloads` as the default output directory and `/work` as the default temporary work directory.

## Docktail Labels

`docker-compose.yml` includes labels for Docktail service discovery/tagging:

```yaml
labels:
  - "docktail.service.enable=true"
  - "docktail.service.name=aebn"
  - "docktail.service.port=8787"
  - "docktail.service.service-port=443"
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

- The web UI history is in-memory and resets when the server restarts.
- The integrated video player can only play completed output files that still exist on disk.
- Use `uv run --extra dev ruff check .` to run lint checks.
