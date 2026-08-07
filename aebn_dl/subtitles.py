from __future__ import annotations

import base64
import json
import math
import os
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RUNPOD_ENDPOINT_URL = os.getenv("AEBNDL_RUNPOD_ENDPOINT_URL", "https://api.runpod.ai/v2/bfarkaz0uwuhcn")
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")
RUNPOD_AUDIO_FIELD = os.getenv("AEBNDL_RUNPOD_AUDIO_FIELD", "audio_base64")
RUNPOD_LANGUAGE = os.getenv("AEBNDL_SUBTITLE_LANGUAGE", "")
RUNPOD_TIMEOUT_SECONDS = int(os.getenv("AEBNDL_RUNPOD_TIMEOUT_SECONDS", "1800"))
RUNPOD_POLL_SECONDS = float(os.getenv("AEBNDL_RUNPOD_POLL_SECONDS", "3"))
RUNPOD_UPLOAD_TIMEOUT = int(os.getenv("AEBNDL_RUNPOD_UPLOAD_TIMEOUT", "600"))
CHUNK_MINUTES = int(os.getenv("AEBNDL_SUBTITLE_CHUNK_MINUTES", "10"))
MAX_CHUNK_MB = float(os.getenv("AEBNDL_SUBTITLE_MAX_CHUNK_MB", "50"))


class SubtitleError(RuntimeError):
    pass


def subtitle_path_for(media_path: str | Path) -> Path:
    return Path(media_path).with_suffix(".srt")


def generate_subtitle_file(media_path: str | Path) -> Path:
    media_path = Path(media_path)
    if not media_path.is_file():
        raise SubtitleError(f"Media file not found: {media_path}")
    if not RUNPOD_API_KEY:
        raise SubtitleError("RUNPOD_API_KEY is required for subtitle generation")

    with TemporaryDirectory(prefix="aebndl-subtitles-") as temp_dir:
        temp_path = Path(temp_dir)
        full_audio = temp_path / f"{media_path.stem}_full.mp3"
        extract_audio(media_path, full_audio)

        duration = probe_duration(full_audio)
        chunk_seconds = CHUNK_MINUTES * 60

        if duration <= chunk_seconds:
            _check_size(full_audio)
            srt_content = transcribe_audio(full_audio, offset_seconds=0)
        else:
            srt_content = _transcribe_chunked(full_audio, duration, chunk_seconds, temp_path)

    output_path = subtitle_path_for(media_path)
    output_path.write_text(srt_content.strip() + "\n", encoding="utf-8")
    return output_path


def _check_size(audio_path: Path) -> None:
    size_mb = audio_path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_CHUNK_MB:
        raise SubtitleError(
            f"Audio chunk is {size_mb:.1f} MB which exceeds the {MAX_CHUNK_MB} MB limit. "
            f"Lower AEBNDL_SUBTITLE_CHUNK_MINUTES (currently {CHUNK_MINUTES}) to reduce chunk size."
        )


def _transcribe_chunked(full_audio: Path, duration: float, chunk_seconds: int, temp_dir: Path) -> str:
    n_chunks = math.ceil(duration / chunk_seconds)
    all_blocks: list[str] = []
    global_index = 1

    for chunk_idx in range(n_chunks):
        start_sec = chunk_idx * chunk_seconds
        chunk_path = temp_dir / f"chunk_{chunk_idx:04d}.mp3"
        _extract_audio_segment(full_audio, chunk_path, start_sec=start_sec, duration_sec=chunk_seconds)
        _check_size(chunk_path)
        chunk_srt = transcribe_audio(chunk_path, offset_seconds=start_sec)
        blocks = _parse_srt_blocks(chunk_srt)
        for _seq, start_ts, end_ts, text in blocks:
            all_blocks.append(f"{global_index}\n{start_ts} --> {end_ts}\n{text}")
            global_index += 1

    if not all_blocks:
        raise SubtitleError("No subtitle blocks produced from chunked transcription")

    return "\n\n".join(all_blocks)


def probe_duration(audio_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SubtitleError(result.stderr.strip() or "ffprobe failed while probing audio duration")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise SubtitleError(f"ffprobe returned non-numeric duration: {result.stdout!r}") from exc


def extract_audio(media_path: Path, audio_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(media_path),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
        str(audio_path),
        "-loglevel", "warning",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SubtitleError(result.stderr.strip() or "FFmpeg failed while extracting audio")


def _extract_audio_segment(source: Path, dest: Path, start_sec: float, duration_sec: int) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", str(source),
        "-c", "copy",
        str(dest),
        "-loglevel", "warning",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SubtitleError(result.stderr.strip() or "FFmpeg failed while extracting audio segment")


def transcribe_audio(audio_path: Path, offset_seconds: float = 0) -> str:
    audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
    input_payload: dict[str, Any] = {
        RUNPOD_AUDIO_FIELD: audio_b64,
        "filename": audio_path.name,
        "task": "transcribe",
        "response_format": "srt",
        "output_format": "srt",
    }
    if RUNPOD_LANGUAGE:
        input_payload["language"] = RUNPOD_LANGUAGE

    job = runpod_request("run", {"input": input_payload})
    job_id = job.get("id")
    if not job_id:
        raw = extract_srt(job)
        return _shift_srt(raw, offset_seconds) if offset_seconds else raw

    deadline = time.monotonic() + RUNPOD_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status_payload = runpod_request(f"status/{job_id}", None)
        status = str(status_payload.get("status", "")).upper()
        if status == "COMPLETED":
            raw = extract_srt(status_payload.get("output", status_payload))
            return _shift_srt(raw, offset_seconds) if offset_seconds else raw
        if status in {"FAILED", "CANCELLED", "TIMED_OUT"}:
            error = status_payload.get("error") or status_payload.get("output") or status_payload
            raise SubtitleError(f"RunPod transcription failed: {error}")
        time.sleep(RUNPOD_POLL_SECONDS)

    raise SubtitleError(f"RunPod transcription timed out after {RUNPOD_TIMEOUT_SECONDS} seconds")


def runpod_request(path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    url = f"{RUNPOD_ENDPOINT_URL.rstrip('/')}/{path.lstrip('/')}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {RUNPOD_API_KEY}",
            "Content-Type": "application/json",
        },
        method="GET" if payload is None else "POST",
    )
    timeout = RUNPOD_UPLOAD_TIMEOUT if data else 120
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SubtitleError(f"RunPod HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise SubtitleError(f"RunPod request failed: {exc}") from exc


def extract_srt(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("srt", "subtitle", "subtitles", "transcription", "text"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value
        segments = output.get("segments")
        if isinstance(segments, list):
            return segments_to_srt(segments)
    raise SubtitleError(f"RunPod response did not contain SRT text: {output}")


def segments_to_srt(segments: list[Any]) -> str:
    blocks = []
    for index, segment in enumerate(segments, 1):
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = float(segment.get("start", 0))
        end = float(segment.get("end", start + 1))
        blocks.append(f"{index}\n{format_timestamp(start)} --> {format_timestamp(end)}\n{text}")
    if not blocks:
        raise SubtitleError("RunPod response contained no subtitle segments")
    return "\n\n".join(blocks)


def format_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _parse_srt_blocks(srt: str) -> list[tuple[str, str, str, str]]:
    blocks: list[tuple[str, str, str, str]] = []
    for raw_block in srt.strip().split("\n\n"):
        lines = raw_block.strip().splitlines()
        if len(lines) < 3:
            continue
        seq = lines[0].strip()
        timing = lines[1].strip()
        text = "\n".join(lines[2:])
        if " --> " not in timing:
            continue
        start_ts, end_ts = timing.split(" --> ", 1)
        blocks.append((seq, start_ts.strip(), end_ts.strip(), text))
    return blocks


def _shift_srt(srt: str, offset_seconds: float) -> str:
    if offset_seconds == 0:
        return srt
    blocks = _parse_srt_blocks(srt)
    shifted: list[str] = []
    for idx, (_seq, start_ts, end_ts, text) in enumerate(blocks, 1):
        new_start = format_timestamp(_ts_to_seconds(start_ts) + offset_seconds)
        new_end = format_timestamp(_ts_to_seconds(end_ts) + offset_seconds)
        shifted.append(f"{idx}\n{new_start} --> {new_end}\n{text}")
    return "\n\n".join(shifted)


def _ts_to_seconds(ts: str) -> float:
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    hours = float(parts[0])
    minutes = float(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds
