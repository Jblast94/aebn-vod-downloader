from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .downloader import Downloader

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
DEFAULT_OUTPUT_DIR = os.getenv("AEBNDL_OUTPUT_DIR", "")
DEFAULT_WORK_DIR = os.getenv("AEBNDL_WORK_DIR", "")


@dataclass
class DownloadOptions:
    url: str
    output_dir: str = ""
    work_dir: str = ""
    resolution: int | None = None
    force_resolution: bool = False
    include_performer_names: bool = False
    no_metadata: bool = False
    scene: int | None = None
    start_segment: int = 0
    end_segment: int | None = None
    proxy: str = ""
    proxy_metadata_only: bool = False
    download_covers: bool = False
    overwrite_existing_files: bool = False
    target_stream: Literal["audio", "video"] | None = None
    keep_segments_after_download: bool = False
    keep_logs: bool = False
    aggressive_segment_cleaning: bool = False
    threads: int = 5
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    split_scenes: bool = False


@dataclass
class DownloadJob:
    id: str
    options: DownloadOptions
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=500))
    output_paths: list[str] = field(default_factory=list)
    error: str = ""


class JobLogHandler(logging.Handler):
    def __init__(self, job_id: str):
        super().__init__()
        self.job_id = job_id
        self.setFormatter(logging.Formatter("%(asctime)s|%(levelname)s|%(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        append_job_log(self.job_id, self.format(record))


jobs: dict[str, DownloadJob] = {}
jobs_lock = threading.Lock()

app = FastAPI(title="AEBN Downloader Web UI")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def optional_int(value: str | None) -> int | None:
    value = blank_to_none(value)
    if value is None:
        return None
    return int(value)


def append_job_log(job_id: str, message: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            job.logs.append(message)
            job.updated_at = datetime.now()


def update_job(job_id: str, **updates: Any) -> None:
    with jobs_lock:
        job = jobs[job_id]
        for key, value in updates.items():
            setattr(job, key, value)
        job.updated_at = datetime.now()


def serialize_job(job: DownloadJob) -> dict[str, Any]:
    outputs = []
    for index, output_path in enumerate(job.output_paths):
        path = Path(output_path)
        outputs.append(
            {
                "index": index,
                "name": path.name,
                "path": output_path,
                "exists": path.is_file(),
                "media_url": f"/media/{job.id}/{index}" if job.status == "completed" and path.is_file() else None,
            }
        )

    return {
        "id": job.id,
        "status": job.status,
        "url": job.options.url,
        "created_at": job.created_at.isoformat(timespec="seconds"),
        "updated_at": job.updated_at.isoformat(timespec="seconds"),
        "logs": list(job.logs),
        "output_paths": job.output_paths,
        "outputs": outputs,
        "error": job.error,
        "resolution": job.options.resolution,
        "target_stream": job.options.target_stream or "both",
    }


def list_serialized_jobs() -> list[dict[str, Any]]:
    with jobs_lock:
        return [serialize_job(job) for job in sorted(jobs.values(), key=lambda item: item.created_at, reverse=True)]


def get_serialized_job(job_id: str) -> dict[str, Any] | None:
    with jobs_lock:
        job = jobs.get(job_id)
        return serialize_job(job) if job else None


def run_download_job(job_id: str) -> None:
    serialized = get_serialized_job(job_id)
    if not serialized:
        return

    with jobs_lock:
        options = jobs[job_id].options

    update_job(job_id, status="running")
    append_job_log(job_id, "Download started")
    downloader = Downloader(
        url=options.url,
        output_dir=options.output_dir,
        work_dir=options.work_dir,
        target_height=options.resolution,
        force_resolution=options.force_resolution,
        include_performer_names=options.include_performer_names,
        no_metadata=options.no_metadata,
        scene_n=options.scene,
        start_segment=options.start_segment,
        end_segment=options.end_segment,
        download_covers=options.download_covers,
        overwrite_existing_files=options.overwrite_existing_files,
        target_stream=options.target_stream,
        keep_segments_after_download=options.keep_segments_after_download,
        aggressive_segment_cleaning=options.aggressive_segment_cleaning,
        log_level=options.log_level,
        keep_logs=options.keep_logs,
        proxy=options.proxy,
        threads=options.threads,
        proxy_metadata_only=options.proxy_metadata_only,
        split_scenes=options.split_scenes,
        show_progress=False,
    )
    web_handler = JobLogHandler(job_id)
    downloader.logger.addHandler(web_handler)
    try:
        result = downloader.run()
        output_paths = [str(path) for path in result] if isinstance(result, list) else [str(result)]
        update_job(job_id, status="completed", output_paths=output_paths)
        append_job_log(job_id, "Download completed")
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc))
        append_job_log(job_id, f"Download failed: {exc}")
    finally:
        downloader.logger.removeHandler(web_handler)


def start_job(options: DownloadOptions) -> DownloadJob:
    job = DownloadJob(id=uuid.uuid4().hex[:12], options=options)
    with jobs_lock:
        jobs[job.id] = job
    thread = threading.Thread(target=run_download_job, args=(job.id,), daemon=True)
    thread.start()
    return job


def build_options(
    url: str,
    output_dir: str,
    work_dir: str,
    resolution: str,
    force_resolution: bool,
    include_performer_names: bool,
    no_metadata: bool,
    scene: str,
    start_segment: str,
    end_segment: str,
    proxy: str,
    proxy_metadata_only: bool,
    download_covers: bool,
    overwrite_existing_files: bool,
    target_stream: str,
    keep_segments_after_download: bool,
    keep_logs: bool,
    aggressive_segment_cleaning: bool,
    threads: int,
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    split_scenes: bool,
) -> DownloadOptions:
    if split_scenes and scene:
        raise HTTPException(status_code=400, detail="Split scenes cannot be combined with a single scene.")
    if split_scenes and (start_segment or end_segment):
        raise HTTPException(status_code=400, detail="Split scenes cannot be combined with segment ranges.")

    clean_url = blank_to_none(url)
    if clean_url is None:
        raise HTTPException(status_code=400, detail="A movie URL or list.txt path is required.")

    return DownloadOptions(
        url=clean_url,
        output_dir=output_dir.strip() or DEFAULT_OUTPUT_DIR,
        work_dir=work_dir.strip() or DEFAULT_WORK_DIR,
        resolution=optional_int(resolution),
        force_resolution=force_resolution,
        include_performer_names=include_performer_names,
        no_metadata=no_metadata,
        scene=optional_int(scene),
        start_segment=optional_int(start_segment) or 0,
        end_segment=optional_int(end_segment),
        proxy=proxy.strip(),
        proxy_metadata_only=proxy_metadata_only,
        download_covers=download_covers,
        overwrite_existing_files=overwrite_existing_files,
        target_stream=blank_to_none(target_stream),
        keep_segments_after_download=keep_segments_after_download,
        keep_logs=keep_logs,
        aggressive_segment_cleaning=aggressive_segment_cleaning,
        threads=threads,
        log_level=log_level,
        split_scenes=split_scenes,
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "jobs": list_serialized_jobs(),
            "default_output_dir": DEFAULT_OUTPUT_DIR,
            "default_work_dir": DEFAULT_WORK_DIR,
        },
    )


@app.get("/jobs", response_class=JSONResponse)
async def get_jobs() -> JSONResponse:
    return JSONResponse({"jobs": list_serialized_jobs()})


@app.get("/jobs/{job_id}", response_class=JSONResponse)
async def get_job(job_id: str) -> JSONResponse:
    job = get_serialized_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job)


@app.get("/media/{job_id}/{output_index}")
async def stream_output(job_id: str, output_index: int) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status != "completed":
            raise HTTPException(status_code=409, detail="Job output is not ready")
        if output_index < 0 or output_index >= len(job.output_paths):
            raise HTTPException(status_code=404, detail="Output not found")
        output_path = Path(job.output_paths[output_index])

    if not output_path.is_file():
        raise HTTPException(status_code=404, detail="Output file no longer exists")

    return FileResponse(output_path, media_type="video/mp4", filename=output_path.name)


@app.post("/downloads", response_class=JSONResponse)
async def create_download(
    url: str = Form(""),
    output_dir: str = Form(""),
    work_dir: str = Form(""),
    resolution: str = Form(""),
    force_resolution: bool = Form(False),
    include_performer_names: bool = Form(False),
    no_metadata: bool = Form(False),
    scene: str = Form(""),
    start_segment: str = Form(""),
    end_segment: str = Form(""),
    proxy: str = Form(""),
    proxy_metadata_only: bool = Form(False),
    download_covers: bool = Form(False),
    overwrite_existing_files: bool = Form(False),
    target_stream: str = Form(""),
    keep_segments_after_download: bool = Form(False),
    keep_logs: bool = Form(False),
    aggressive_segment_cleaning: bool = Form(False),
    threads: int = Form(5),
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Form("INFO"),
    split_scenes: bool = Form(False),
) -> JSONResponse:
    options = build_options(
        url,
        output_dir,
        work_dir,
        resolution,
        force_resolution,
        include_performer_names,
        no_metadata,
        scene,
        start_segment,
        end_segment,
        proxy,
        proxy_metadata_only,
        download_covers,
        overwrite_existing_files,
        target_stream,
        keep_segments_after_download,
        keep_logs,
        aggressive_segment_cleaning,
        threads,
        log_level,
        split_scenes,
    )
    job = start_job(options)
    return JSONResponse({"job_id": job.id, "job": serialize_job(job)})


@app.post("/info", response_class=PlainTextResponse)
async def movie_info(
    url: str = Form(""),
    resolution: str = Form(""),
    proxy: str = Form(""),
    proxy_metadata_only: bool = Form(False),
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Form("INFO"),
) -> PlainTextResponse:
    clean_url = blank_to_none(url)
    if clean_url is None:
        raise HTTPException(status_code=400, detail="A movie URL is required before fetching info.")

    downloader = Downloader(
        url=clean_url,
        target_height=optional_int(resolution),
        proxy=proxy.strip(),
        proxy_metadata_only=proxy_metadata_only,
        log_level=log_level,
        show_progress=False,
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        downloader.print_info()
    return PlainTextResponse(output.getvalue())


@app.websocket("/ws/jobs/{job_id}")
async def job_updates(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    try:
        while True:
            job = get_serialized_job(job_id)
            if job is None:
                await websocket.send_json({"error": "Job not found"})
                return
            await websocket.send_json(job)
            if job["status"] in {"completed", "failed"}:
                return
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


def main() -> None:
    import uvicorn

    host = os.getenv("AEBNDL_HOST", "127.0.0.1")
    port = int(os.getenv("AEBNDL_PORT", "8787"))
    uvicorn.run("aebn_dl.web:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
