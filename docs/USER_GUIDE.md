# Web UI User Guide

This guide explains how to use the local web UI for AEBN downloads.

## Start the Web UI

Local development:

```bash
uv run aebndl-web
```

Docker Compose:

```bash
docker compose up -d --build
```

Open the UI:

```text
http://127.0.0.1:8787
```

If using Docker Compose on another host, replace `127.0.0.1` with the host name or Tailnet address.

## Download Setup

The `New job` form maps to the existing CLI options.

Common fields:

| Field | Meaning |
| --- | --- |
| `Movie URL` | A single movie URL. |
| `URL list file` | A `.txt` file with one URL per line. Blank lines and `#` comments are ignored. |
| `Output directory` | Final file location. In Docker this defaults to `/downloads`. |
| `Work directory` | Temporary segment location. In Docker this defaults to `/work`. |
| `Resolution` | Desired height such as `720`, `1080`, or `2160`. Empty means highest available. `0` means lowest available. |
| `Scene` | Download only one scene by scene number. |
| `Start segment` / `End segment` | Download a segment range instead of the full title. |
| `Target stream` | Choose audio plus video, audio only, or video only. |
| `Proxy` | Optional proxy URL. |
| `Threads` | Number of download threads. |

Useful toggles:

| Toggle | Meaning |
| --- | --- |
| `Force resolution` | Fail if the selected resolution is not available. |
| `Include performer names` | Adds performer names to output file names. |
| `Skip metadata` | Disables title/chapter metadata embedding. |
| `Download covers` | Downloads front/back cover images. |
| `Overwrite segments` | Re-downloads existing segment files. |
| `Keep segments` | Leaves temporary segment files after completion. |
| `Keep logs` | Keeps downloader log files after successful completion. |
| `Aggressive cleaning` | Removes segment files earlier to save disk space. |
| `Proxy metadata only` | Uses the proxy for metadata requests only. |
| `Split scenes` | Saves each scene as a separate output file. |
| `Generate subtitles` | Sends completed outputs to the configured RunPod Faster-Whisper endpoint and writes `.srt` files beside the media files. |

## Fetch Info

Click `Fetch info` after entering a URL to preview metadata and scene segment boundaries without starting a download.

This is useful for choosing:

- A scene number
- A segment range
- A resolution
- Whether to split scenes

## Jobs

The `Jobs` panel shows download activity:

- Current status: `queued`, `running`, `completed`, `failed`, or `cancelled`
- Recent logs
- Output paths
- `Play` buttons for completed playable outputs
- `Cancel` buttons for queued/running jobs
- `Delete` buttons for terminal jobs
- `Clear completed` to remove completed/failed/cancelled jobs from the visible list

Updates are delivered through WebSockets with a polling fallback.

The server runs at most `AEBNDL_MAX_CONCURRENT_JOBS` downloads at once. Additional jobs stay queued until a slot is available.

## History and Video Player

Completed downloads appear in the `History` panel when their output files still exist.

To play a file:

1. Complete a download.
2. Click the item in `History`, or click `Play` beside an output path in `Jobs`.
3. The file loads into the embedded browser video player.

Limitations:

- History is persisted in SQLite at `AEBNDL_DB_PATH`.
- Files moved or deleted outside the app remain in history but are not playable until restored.
- The player uses the browser's native MP4 support.

## Subtitles

The app can generate `.srt` subtitles using a RunPod Faster-Whisper endpoint.

Automatic subtitles:

1. Set `RUNPOD_API_KEY` in `.env` or the runtime environment.
2. Keep `AEBNDL_AUTO_SUBTITLES=true`.
3. Leave `Generate subtitles` checked in the download form.
4. Start a download.

Manual subtitles:

1. Wait for a job to complete.
2. Click `Generate subtitles` beside an output in the `Jobs` panel.
3. Wait for the subtitle status to become `completed`.
4. Use the `Subtitle` link to download the `.srt`, or play the video to load subtitles in the player.

Configuration:

| Variable | Meaning |
| --- | --- |
| `RUNPOD_API_KEY` | Required RunPod API key. |
| `AEBNDL_RUNPOD_ENDPOINT_URL` | Endpoint base URL, default `https://api.runpod.ai/v2/bfarkaz0uwuhcn`. |
| `AEBNDL_RUNPOD_AUDIO_FIELD` | JSON input field used for the base64 audio payload. Defaults to `audio_base64`. |
| `AEBNDL_RUNPOD_UPLOAD_TIMEOUT` | Upload timeout, in seconds, for RunPod subtitle requests. |
| `AEBNDL_SUBTITLE_CHUNK_MINUTES` | Length of audio chunks sent to RunPod for long media files. |
| `AEBNDL_SUBTITLE_MAX_CHUNK_MB` | Maximum extracted audio chunk size before the app stops with guidance. |
| `AEBNDL_AUTO_SUBTITLES` | Enables or disables automatic subtitle generation. |
| `AEBNDL_SUBTITLE_LANGUAGE` | Optional language hint. Empty means auto-detect. |

Generated subtitle files are written next to their media files using the same base filename and `.srt` extension.

## Recommended Docker Paths

When using Docker Compose, keep these defaults in the web form:

| Form field | Container path | Host path from `.env` |
| --- | --- | --- |
| `Output directory` | `/downloads` | `AEBNDL_REMOTE_DOWNLOAD_DIR` |
| `Work directory` | `/work` | `AEBNDL_REMOTE_WORK_DIR` |

The default `.env` maps outputs to `/mnt/storage/downloads` on the host.
