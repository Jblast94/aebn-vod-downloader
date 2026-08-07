from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db as _db
from .downloader import Downloader
from .subtitles import SubtitleError, generate_subtitle_file, subtitle_path_for

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

DEFAULT_OUTPUT_DIR = os.getenv("AEBNDL_OUTPUT_DIR", "")
DEFAULT_WORK_DIR = os.getenv("AEBNDL_WORK_DIR", "")
DEFAULT_AUTO_SUBTITLES = os.getenv("AEBNDL_AUTO_SUBTITLES", "true").lower() in {"1", "true", "yes", "on"}
MAX_CONCURRENT_JOBS = int(os.getenv("AEBNDL_MAX_CONCURRENT_JOBS", "1"))
JOB_RETENTION_HOURS = float(os.getenv("AEBNDL_JOB_RETENTION_HOURS", "0"))


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
    generate_subtitles: bool = DEFAULT_AUTO_SUBTITLES


@dataclass
class DownloadJob:
    id: str
    options: DownloadOptions
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = "queued"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=500))
    output_paths: list[str] = field(default_factory=list)
    subtitle_status: dict[int, dict[str, str]] = field(default_factory=dict)
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)


class JobLogHandler(logging.Handler):
    def __init__(self, job_id: str):
        super().__init__()
        self.job_id = job_id
        self.setFormatter(logging.Formatter("%(asctime)s|%(levelname)s|%(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        append_job_log(self.job_id, self.format(record))


jobs: dict[str, DownloadJob] = {}
jobs_lock = threading.Lock()

_queue_semaphore = threading.Semaphore(MAX_CONCURRENT_JOBS)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    load_persisted_jobs()
    if JOB_RETENTION_HOURS:
        threading.Thread(target=_pruner_loop, daemon=True).start()
    yield


app = FastAPI(title="AEBN Downloader Web UI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
URL_LIST_FILE = File(None)


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
            persist_job(job)


def update_job(job_id: str, **updates: Any) -> None:
    with jobs_lock:
        job = jobs[job_id]
        for key, value in updates.items():
            setattr(job, key, value)
        job.updated_at = datetime.now()
        persist_job(job)


def options_to_dict(options: DownloadOptions) -> dict[str, Any]:
    return {
        "url": options.url,
        "output_dir": options.output_dir,
        "work_dir": options.work_dir,
        "resolution": options.resolution,
        "force_resolution": options.force_resolution,
        "include_performer_names": options.include_performer_names,
        "no_metadata": options.no_metadata,
        "scene": options.scene,
        "start_segment": options.start_segment,
        "end_segment": options.end_segment,
        "proxy": options.proxy,
        "proxy_metadata_only": options.proxy_metadata_only,
        "download_covers": options.download_covers,
        "overwrite_existing_files": options.overwrite_existing_files,
        "target_stream": options.target_stream,
        "keep_segments_after_download": options.keep_segments_after_download,
        "keep_logs": options.keep_logs,
        "aggressive_segment_cleaning": options.aggressive_segment_cleaning,
        "threads": options.threads,
        "log_level": options.log_level,
        "split_scenes": options.split_scenes,
        "generate_subtitles": options.generate_subtitles,
    }


def options_from_dict(data: dict[str, Any]) -> DownloadOptions:
    return DownloadOptions(**data)


def persist_job(job: DownloadJob) -> None:
    _db.save_job(
        {
            "id": job.id,
            "url": job.options.url,
            "status": job.status,
            "created_at": job.created_at.isoformat(timespec="seconds"),
            "updated_at": job.updated_at.isoformat(timespec="seconds"),
            "output_paths": job.output_paths,
            "subtitle_status_raw": job.subtitle_status,
            "error": job.error,
            "options": options_to_dict(job.options),
        }
    )


def load_persisted_jobs() -> None:
    for record in _db.load_all_jobs():
        try:
            job = DownloadJob(
                id=record["id"],
                options=options_from_dict(record["options"]),
                status=record["status"],
                created_at=datetime.fromisoformat(record["created_at"]),
                updated_at=datetime.fromisoformat(record["updated_at"]),
                output_paths=record["output_paths"],
                subtitle_status={int(key): value for key, value in record["subtitle_status_raw"].items()},
                error=record["error"],
            )
        except Exception:
            continue
        with jobs_lock:
            jobs[job.id] = job


def serialize_job(job: DownloadJob) -> dict[str, Any]:
    outputs = []
    for index, output_path in enumerate(job.output_paths):
        path = Path(output_path)
        subtitle_path = subtitle_path_for(path)
        subtitle = job.subtitle_status.get(index, {})
        subtitle_path_value = subtitle.get("path") or (str(subtitle_path) if subtitle_path.is_file() else "")
        subtitle_exists = bool(subtitle_path_value and Path(subtitle_path_value).is_file())
        outputs.append(
            {
                "index": index,
                "name": path.name,
                "path": output_path,
                "exists": path.is_file(),
                "media_url": f"/media/{job.id}/{index}" if job.status == "completed" and path.is_file() else None,
                "subtitle_status": subtitle.get("status", "completed" if subtitle_exists else "idle"),
                "subtitle_path": subtitle_path_value,
                "subtitle_error": subtitle.get("error", ""),
                "subtitle_url": f"/subtitle-files/{job.id}/{index}" if subtitle_exists else None,
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
        "cancellable": job.status in {"queued", "running"},
    }


def list_serialized_jobs() -> list[dict[str, Any]]:
    with jobs_lock:
        return [serialize_job(job) for job in sorted(jobs.values(), key=lambda item: item.created_at, reverse=True)]


def get_serialized_job(job_id: str) -> dict[str, Any] | None:
    with jobs_lock:
        job = jobs.get(job_id)
        return serialize_job(job) if job else None


def _prune_old_jobs() -> None:
    if not JOB_RETENTION_HOURS:
        return
    cutoff = datetime.now() - timedelta(hours=JOB_RETENTION_HOURS)
    with jobs_lock:
        to_delete = [
            job_id
            for job_id, job in jobs.items()
            if job.status in {"completed", "failed", "cancelled"} and job.updated_at < cutoff
        ]
        for job_id in to_delete:
            del jobs[job_id]
            _db.delete_job_record(job_id)


def _pruner_loop() -> None:
    while True:
        time.sleep(3600)
        _prune_old_jobs()


def run_download_job(job_id: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return
        cancel_event = job.cancel_event
        options = job.options

    append_job_log(job_id, "Waiting for download slot...")
    _queue_semaphore.acquire()
    try:
        with jobs_lock:
            current_job = jobs.get(job_id)
            should_cancel = current_job is not None and (current_job.cancel_event.is_set() or current_job.status == "cancelled")
        if current_job is None:
            return
        if should_cancel:
            update_job(job_id, status="cancelled")
            append_job_log(job_id, "Job cancelled before starting")
            return

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
            cancel_event=cancel_event,
        )
        web_handler = JobLogHandler(job_id)
        downloader.logger.addHandler(web_handler)
        try:
            if cancel_event.is_set():
                update_job(job_id, status="cancelled")
                append_job_log(job_id, "Job cancelled")
                return
            result = downloader.run()
            output_paths = [str(path) for path in result] if isinstance(result, list) else [str(result)]
            update_job(job_id, status="completed", output_paths=output_paths)
            append_job_log(job_id, "Download completed")
            if options.generate_subtitles and not cancel_event.is_set():
                for output_index in range(len(output_paths)):
                    generate_subtitles_for_output(job_id, output_index)
        except Exception as exc:
            with jobs_lock:
                current_status = jobs[job_id].status if job_id in jobs else "failed"
            if current_status == "cancelled" or cancel_event.is_set():
                update_job(job_id, status="cancelled")
                append_job_log(job_id, "Download cancelled")
                return
            update_job(job_id, status="failed", error=str(exc))
            append_job_log(job_id, f"Download failed: {exc}")
        finally:
            downloader.logger.removeHandler(web_handler)
    finally:
        _queue_semaphore.release()


def start_job(options: DownloadOptions) -> DownloadJob:
    job = DownloadJob(id=uuid.uuid4().hex[:12], options=options)
    with jobs_lock:
        jobs[job.id] = job
        persist_job(job)
    thread = threading.Thread(target=run_download_job, args=(job.id,), daemon=True)
    thread.start()
    return job


def cancel_job(job_id: str) -> bool:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return False
        if job.status not in {"queued", "running"}:
            return False
        job.cancel_event.set()
        if job.status == "queued":
            job.status = "cancelled"
            job.updated_at = datetime.now()
            persist_job(job)
    append_job_log(job_id, "Cancellation requested")
    return True


def delete_job(job_id: str, delete_files: bool = False) -> bool:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return False
        if job.status in {"queued", "running"}:
            return False
        output_paths = list(job.output_paths)
        del jobs[job_id]
        _db.delete_job_record(job_id)

    if delete_files:
        for output_path in output_paths:
            path = Path(output_path)
            if path.is_file():
                path.unlink(missing_ok=True)
            srt = subtitle_path_for(path)
            if srt.is_file():
                srt.unlink(missing_ok=True)

    return True


def update_subtitle_status(job_id: str, output_index: int, **updates: str) -> None:
    with jobs_lock:
        job = jobs[job_id]
        current = dict(job.subtitle_status.get(output_index, {}))
        current.update(updates)
        job.subtitle_status[output_index] = current
        job.updated_at = datetime.now()
        persist_job(job)


def generate_subtitles_for_output(job_id: str, output_index: int) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return
        if job.status != "completed":
            raise SubtitleError("Subtitles can only be generated for completed jobs")
        if output_index < 0 or output_index >= len(job.output_paths):
            raise SubtitleError("Output not found")
        output_path = Path(job.output_paths[output_index])

    update_subtitle_status(job_id, output_index, status="running", error="")
    append_job_log(job_id, f"Subtitle generation started for {output_path.name}")
    try:
        subtitle_path = generate_subtitle_file(output_path)
        update_subtitle_status(job_id, output_index, status="completed", path=str(subtitle_path), error="")
        append_job_log(job_id, f"Subtitle generation completed: {subtitle_path}")
    except Exception as exc:
        update_subtitle_status(job_id, output_index, status="failed", error=str(exc))
        append_job_log(job_id, f"Subtitle generation failed for {output_path.name}: {exc}")


def start_subtitle_job(job_id: str, output_index: int) -> None:
    thread = threading.Thread(target=generate_subtitles_for_output, args=(job_id, output_index), daemon=True)
    thread.start()


def _parse_url_list(text: str) -> list[str]:
    urls = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


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
    generate_subtitles: bool,
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
        generate_subtitles=generate_subtitles,
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
            "default_auto_subtitles": DEFAULT_AUTO_SUBTITLES,
            "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
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


@app.delete("/jobs/{job_id}", response_class=JSONResponse)
async def remove_job(job_id: str, delete_files: bool = False) -> JSONResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="Cancel the job before deleting it.")
    ok = delete_job(job_id, delete_files=delete_files)
    if not ok:
        raise HTTPException(status_code=409, detail="Job could not be deleted.")
    return JSONResponse({"deleted": True})


@app.post("/jobs/{job_id}/cancel", response_class=JSONResponse)
async def cancel_job_endpoint(job_id: str) -> JSONResponse:
    ok = cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Job is not cancellable.")
    return JSONResponse({"cancelled": True})


@app.delete("/jobs", response_class=JSONResponse)
async def clear_completed_jobs(delete_files: bool = False) -> JSONResponse:
    with jobs_lock:
        terminal = [job_id for job_id, job in jobs.items() if job.status in {"completed", "failed", "cancelled"}]
    count = 0
    for job_id in terminal:
        if delete_job(job_id, delete_files=delete_files):
            count += 1
    return JSONResponse({"deleted": count})


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


@app.get("/subtitle-files/{job_id}/{output_index}")
async def get_subtitle_file(job_id: str, output_index: int) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if output_index < 0 or output_index >= len(job.output_paths):
            raise HTTPException(status_code=404, detail="Output not found")
        output_path = Path(job.output_paths[output_index])
        configured_path = job.subtitle_status.get(output_index, {}).get("path", "")
        subtitle_path = Path(configured_path) if configured_path else subtitle_path_for(output_path)

    if not subtitle_path.is_file():
        raise HTTPException(status_code=404, detail="Subtitle file not found")

    return FileResponse(subtitle_path, media_type="application/x-subrip", filename=subtitle_path.name)


@app.post("/subtitles/{job_id}/{output_index}", response_class=JSONResponse)
async def create_subtitles(job_id: str, output_index: int) -> JSONResponse:
    job = get_serialized_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail="Job output is not ready")
    start_subtitle_job(job_id, output_index)
    return JSONResponse({"status": "queued"})


@app.post("/downloads", response_class=JSONResponse)
async def create_download(
    url: str = Form(""),
    url_list_file: UploadFile | None = URL_LIST_FILE,
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
    generate_subtitles: bool = Form(False),
) -> JSONResponse:
    urls_to_start: list[str] = []

    if url_list_file and url_list_file.filename:
        content = (await url_list_file.read()).decode("utf-8", errors="replace")
        parsed = _parse_url_list(content)
        if not parsed:
            raise HTTPException(status_code=400, detail="The uploaded list file contained no valid URLs.")
        urls_to_start.extend(parsed)

    clean_single = blank_to_none(url)
    if clean_single:
        urls_to_start.append(clean_single)

    if not urls_to_start:
        raise HTTPException(status_code=400, detail="A movie URL or list file is required.")

    started_jobs = []
    for single_url in urls_to_start:
        options = build_options(
            single_url,
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
            generate_subtitles,
        )
        job = start_job(options)
        started_jobs.append({"job_id": job.id, "url": single_url})

    if len(started_jobs) == 1:
        return JSONResponse({"job_id": started_jobs[0]["job_id"], "job": get_serialized_job(started_jobs[0]["job_id"]), "jobs": started_jobs})

    return JSONResponse({"jobs": started_jobs})


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

    def _fetch_info() -> str:
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
        return output.getvalue()

    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _fetch_info)
    return PlainTextResponse(text)


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
            if job["status"] in {"completed", "failed", "cancelled"}:
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
