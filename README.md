# aebn-vod-downloader

MVP for a **single remote Linux VM**: local downloader + web UI in one Compose stack. No second worker, no cloud GPU, no RunPod, no NFS required.

Target test box: about 32 vCPU, 100 GB RAM, ~10 Gb NIC. Use this VM to develop and build a media library **before** any homelab NFS / Stash / Jellyfin / remote-worker work.

## Run on the VM

Need Docker Engine with the Compose plugin (`docker compose version`). Git clone this branch onto the VM.

```bash
git clone https://github.com/Jblast94/aebn-vod-downloader.git
cd aebn-vod-downloader
git checkout web-ui   # or this MVP branch

cp .env.example .env
mkdir -p downloads work
docker compose up -d --build
```

Wait until healthy:

```bash
docker compose ps
curl -sf http://127.0.0.1:8787/health
```

Expected health JSON:

```json
{"status":"ok","service":"aebndl-web","output_dir":"/downloads","work_dir":"/work"}
```

Open the UI:

```text
http://<vm-ip>:8787
```

Stop:

```bash
docker compose down
```

Logs:

```bash
docker compose logs -f aebndl-web
```

## Where files land

| Role | In the container | On the VM (default) |
| --- | --- | --- |
| Completed media + SQLite job DB | `/downloads` | `./downloads` next to `docker-compose.yml` |
| Temporary segments | `/work` | `./work` |

That is the whole storage story for this MVP. Point the web form at `/downloads` and `/work` (Compose already sets those defaults).

Optional: put media on a dedicated disk instead of the repo directory.

```env
AEBNDL_DOWNLOAD_DIR=/data/downloads
AEBNDL_SEGMENT_DIR=/data/aebndl-work
```

Then:

```bash
sudo mkdir -p /data/downloads /data/aebndl-work
sudo chown "$USER:$USER" /data/downloads /data/aebndl-work
docker compose up -d
```

**Not required for MVP:** homelab NFS (`/mnt/storage/downloads`). Use that later when this stack has been tested on the VM.

## What this stack is

- One service: `aebndl-web`
- Downloads run **in that container** on this VM
- Web UI on port `8787` (override with `AEBNDL_WEB_PORT`)
- Subtitle / RunPod paths are **off**. Checking “Generate subtitles” is skipped so a download cannot depend on a remote transcriber.

On a 10 Gb NIC you can raise **Threads** in the download form (for example 16). Keep `AEBNDL_MAX_CONCURRENT_JOBS=1` unless you know the site will tolerate more than one title at a time.

## `.env`

Copy from `.env.example`. Do not put API keys or tokens in git.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AEBNDL_WEB_PORT` | `8787` | Host port for the UI |
| `AEBNDL_DOWNLOAD_DIR` | `./downloads` | VM directory bind-mounted as `/downloads` |
| `AEBNDL_SEGMENT_DIR` | `./work` | VM directory bind-mounted as `/work` |
| `AEBNDL_DB_PATH` | `/downloads/aebndl-jobs.db` | Job history inside the container |
| `AEBNDL_MAX_CONCURRENT_JOBS` | `1` | Parallel title downloads |
| `AEBNDL_JOB_RETENTION_HOURS` | `0` | `0` keeps history; otherwise prune old jobs |
| `TZ` | `UTC` | Container timezone |

## Later (not this MVP)

- **Stash / Jellyfin:** add a library watch folder on the **same path the VM writes** (`./downloads` or `/data/downloads`). Do not add `./work`. API hooks and metadata push are follow-up work.
- **Homelab NFS:** retarget `AEBNDL_DOWNLOAD_DIR` to `/mnt/storage/downloads` after VM testing.
- **Optional remote workers / RunPod subtitles:** follow-up. This MVP must run with no extra stack.

## CLI (optional, same VM)

```bash
uv sync
uv run aebndl "https://*.aebn.com/*/movies/*" --resolution 720 -o ./downloads -w ./work
```

Needs FFmpeg on the host if you skip Docker.

## More UI detail

- [Web UI User Guide](docs/USER_GUIDE.md)
- [Deployment notes](docs/DEPLOYMENT.md)

## CLI arguments

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
