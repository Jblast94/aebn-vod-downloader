from datetime import datetime

import pytest
from fastapi import HTTPException

from aebn_dl.web import (
    DownloadJob,
    DownloadOptions,
    build_options,
    generate_subtitles_for_output,
    jobs,
    jobs_lock,
    options_from_dict,
    options_to_dict,
    runtime_status,
    serialize_job,
)


def test_build_options_rejects_split_scene_conflict():
    with pytest.raises(HTTPException) as exc:
        build_options(
            url="https://example.test/movie",
            output_dir="",
            work_dir="",
            resolution="",
            force_resolution=False,
            include_performer_names=False,
            no_metadata=False,
            scene="1",
            start_segment="",
            end_segment="",
            proxy="",
            proxy_metadata_only=False,
            download_covers=False,
            overwrite_existing_files=False,
            target_stream="",
            keep_segments_after_download=False,
            keep_logs=False,
            aggressive_segment_cleaning=False,
            threads=5,
            log_level="INFO",
            split_scenes=True,
            generate_subtitles=False,
        )
    assert exc.value.status_code == 400


def test_options_round_trip():
    options = DownloadOptions(url="https://example.test/movie", output_dir="/downloads", resolution=720, generate_subtitles=True)
    assert options_from_dict(options_to_dict(options)) == options


def test_serialize_job_marks_completed_outputs_playable(tmp_path):
    media = tmp_path / "movie.mp4"
    media.write_bytes(b"fake")
    subtitle = tmp_path / "movie.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nText\n", encoding="utf-8")
    job = DownloadJob(
        id="abc123",
        options=DownloadOptions(url="https://example.test/movie"),
        status="completed",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        output_paths=[str(media)],
    )
    serialized = serialize_job(job)
    assert serialized["outputs"][0]["media_url"] == "/media/abc123/0"
    assert serialized["outputs"][0]["subtitle_url"] == "/subtitle-files/abc123/0"
    assert serialized["outputs"][0]["subtitle_status"] == "completed"


def test_runtime_status_reports_ok():
    status = runtime_status()
    assert status["status"] == "ok"
    assert status["service"] == "aebndl-web"


def test_subtitle_generation_is_skipped_without_remote_backend(monkeypatch, tmp_path):
    monkeypatch.setattr("aebn_dl.web.persist_job", lambda job: None)
    media = tmp_path / "movie.mp4"
    media.write_bytes(b"fake")
    job = DownloadJob(
        id="mvp-skip-subs",
        options=DownloadOptions(url="https://example.test/movie", generate_subtitles=True),
        status="completed",
        output_paths=[str(media)],
    )
    with jobs_lock:
        jobs[job.id] = job
    try:
        generate_subtitles_for_output(job.id, 0)
        assert job.status == "completed"
        assert job.subtitle_status[0]["status"] == "skipped"
    finally:
        with jobs_lock:
            jobs.pop(job.id, None)
