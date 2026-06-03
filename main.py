from __future__ import annotations

import gc
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cloudinary_storage
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
JOBS_DIR = DATA_DIR / "jobs"
STATIC_DIR = BASE_DIR / "web"
IMAGES_DIR = BASE_DIR / "Images"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB
_SCENE_TIME_RE = re.compile(r"pts_time:([0-9.]+)")

for p in (UPLOADS_DIR, JOBS_DIR, STATIC_DIR, IMAGES_DIR):
    p.mkdir(parents=True, exist_ok=True)


class CloudinaryJobStart(BaseModel):
    source_public_id: str
    original_name: str | None = None


@dataclass
class JobState:
    id: str
    status: str = "queued"
    progress: int = 0
    stage: str = "Queued"
    error: str | None = None
    input_video: Path | None = None
    output_dir: Path | None = None
    expected_scenes: int = 0
    logs: list[str] = field(default_factory=list)
    scenes: list[dict[str, Any]] = field(default_factory=list)
    source_cloudinary_id: str | None = None
    cloudinary_resource_ids: list[str] = field(default_factory=list)
    download_all_unmuted_external: str | None = None
    download_all_muted_external: str | None = None

    def to_dict(self) -> dict[str, Any]:
        local_ready = self.status in {"processing", "done"}
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "error": self.error,
            "expected_scenes": self.expected_scenes,
            "total_scenes": len(self.scenes),
            "scenes": self.scenes,
            "logs": self.logs[-80:],
            "download_all_unmuted_url": self.download_all_unmuted_external
            or (f"/api/jobs/{self.id}/download-all?muted=0" if local_ready else None),
            "download_all_muted_url": self.download_all_muted_external
            or (f"/api/jobs/{self.id}/download-all?muted=1" if local_ready else None),
        }


jobs: dict[str, JobState] = {}
jobs_lock = threading.Lock()
_jobs_slot_lock = threading.Lock()
_active_processing_jobs = 0
_nvenc_checked = False
_nvenc_available = False


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _low_memory_enabled() -> bool:
    # Dockerfile sets FRAMCUT_LOW_MEMORY=1 on Render; default off for local dev.
    return _env_flag("FRAMECUT_LOW_MEMORY", default=False)


def _max_concurrent_jobs() -> int:
    raw = os.getenv("FRAMECUT_MAX_CONCURRENT_JOBS")
    if raw is not None and raw.strip().isdigit():
        return max(1, int(raw.strip()))
    return 1 if _low_memory_enabled() else 2


def _max_export_workers() -> int:
    raw = os.getenv("FRAMECUT_MAX_EXPORT_WORKERS")
    if raw is not None and raw.strip().isdigit():
        return max(1, int(raw.strip()))
    if _low_memory_enabled():
        return 1
    cpu_count = os.cpu_count() or 4
    return max(1, min(3, cpu_count // 2))


def _scene_detection_method() -> str:
    method = (os.getenv("FRAMECUT_SCENE_METHOD") or "").strip().lower()
    if method in {"ffmpeg", "pyscenedetect"}:
        return method
    return "ffmpeg" if _low_memory_enabled() else "pyscenedetect"


def _reserve_job_slot() -> bool:
    global _active_processing_jobs
    with _jobs_slot_lock:
        if _active_processing_jobs >= _max_concurrent_jobs():
            return False
        _active_processing_jobs += 1
        return True


def _release_job_slot() -> None:
    global _active_processing_jobs
    with _jobs_slot_lock:
        _active_processing_jobs = max(0, _active_processing_jobs - 1)


def _ensure_job_capacity() -> None:
    if not _reserve_job_slot():
        raise HTTPException(
            status_code=503,
            detail="Server is processing another video. Please wait and try again shortly.",
        )

app = FastAPI(title="Scene Splitter Clips")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _set_job(job_id: str, **kwargs: Any) -> None:
    with jobs_lock:
        job = jobs[job_id]
        for k, v in kwargs.items():
            setattr(job, k, v)


def _append_log(job_id: str, line: str) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job.logs.append(line)
        if len(job.logs) > 400:
            job.logs = job.logs[-200:]


def _fmt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    h = millis // 3_600_000
    millis %= 3_600_000
    m = millis // 60_000
    millis %= 60_000
    s = millis // 1000
    ms = millis % 1000
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        out = (result.stderr or result.stdout or "Command failed").strip()
        # Keep frontend errors concise and actionable instead of huge FFmpeg banners.
        tail = "\n".join(out.splitlines()[-12:])
        raise RuntimeError(tail)


def _has_ffmpeg_encoder(encoder: str) -> bool:
    result = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    return encoder in result.stdout


def _nvenc_runtime_available() -> bool:
    global _nvenc_checked, _nvenc_available
    if _nvenc_checked:
        return _nvenc_available

    _nvenc_checked = True
    if not _has_ffmpeg_encoder("h264_nvenc"):
        _nvenc_available = False
        return _nvenc_available

    probe = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=1",
            "-frames:v",
            "1",
            "-c:v",
            "h264_nvenc",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    _nvenc_available = probe.returncode == 0
    return _nvenc_available


def _ffprobe_value(video_path: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", *args, str(video_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _video_fps(video_path: Path) -> float:
    rate = _ffprobe_value(
        video_path,
        [
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
        ],
    )
    if not rate:
        return 30.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        den_f = float(den or 1)
        if den_f <= 0:
            return 30.0
        fps = float(num) / den_f
    else:
        fps = float(rate)
    return fps if fps > 0 else 30.0


def _video_duration(video_path: Path) -> float:
    raw = _ffprobe_value(
        video_path,
        ["-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1"],
    )
    try:
        duration = float(raw)
    except ValueError:
        return 0.0
    return duration if duration > 0 else 0.0


def _detect_scenes_ffmpeg(
    video_path: Path,
    threshold: float = 0.35,
    min_scene_sec: float = 0.5,
) -> list[tuple[float, float]]:
    """Stream-based scene detection via FFmpeg (low RAM, suitable for small containers)."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(video_path),
            "-filter:v",
            f"select='gt(scene,{threshold})',showinfo",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    cut_times = [0.0]
    for line in proc.stderr.splitlines():
        match = _SCENE_TIME_RE.search(line)
        if match:
            cut_times.append(float(match.group(1)))

    duration = _video_duration(video_path)
    if duration <= 0:
        return [(0.0, 0.0)]

    cut_times.append(duration)
    cut_times = sorted(set(cut_times))

    segments: list[tuple[float, float]] = []
    for start, end in zip(cut_times, cut_times[1:]):
        if end > start and (end - start) >= min_scene_sec:
            segments.append((start, end))

    if not segments:
        segments = [(0.0, duration)]
    return segments


def _detect_scenes_pyscenedetect(video_path: Path, job_id: str) -> list[tuple[float, float]]:
    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.auto_downscale = True

    if _low_memory_enabled():
        scene_manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=15))
        frame_skip = 1 if _video_duration(video_path) > 300 else 0
    else:
        from scenedetect import AdaptiveDetector

        scene_manager.add_detector(AdaptiveDetector(adaptive_threshold=3.0, min_scene_len=12))
        scene_manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=12))
        frame_skip = 0

    _append_log(job_id, "Analyzing visual cuts and transitions.")
    scene_manager.detect_scenes(video=video, show_progress=False, frame_skip=frame_skip)
    scene_list = scene_manager.get_scene_list()

    fps = _video_fps(video_path)
    segments: list[tuple[float, float]] = []
    if not scene_list:
        duration = _video_duration(video_path)
        if duration > 0:
            segments = [(0.0, duration)]
    else:
        for start_tc, end_tc in scene_list:
            start_sec = start_tc.get_frames() / fps
            end_sec = end_tc.get_frames() / fps
            if end_sec > start_sec:
                segments.append((start_sec, end_sec))

    del video
    del scene_manager
    gc.collect()
    return segments


def _scene_api_payload(job_id: str, scene: dict[str, Any]) -> dict[str, Any]:
    clip_name = scene["clip_name"]
    muted_clip_name = scene["muted_clip_name"]
    thumb_name = scene["thumbnail_name"]
    return {
        "scene_number": scene["scene_number"],
        "start_seconds": scene["start_seconds"],
        "end_seconds": scene["end_seconds"],
        "duration_seconds": scene["duration_seconds"],
        "start_timestamp": scene["start_timestamp"],
        "end_timestamp": scene["end_timestamp"],
        "duration_timestamp": scene["duration_timestamp"],
        "thumbnail_url": f"/api/jobs/{job_id}/thumb/{thumb_name}",
        "clip_url": f"/api/jobs/{job_id}/clip/{clip_name}",
        "muted_clip_url": f"/api/jobs/{job_id}/clip/{muted_clip_name}",
        "download_unmuted_url": f"/api/jobs/{job_id}/clip/{clip_name}?download=1",
        "download_muted_url": f"/api/jobs/{job_id}/clip/{muted_clip_name}?download=1",
        "thumbnail_name": thumb_name,
        "clip_name": clip_name,
        "muted_clip_name": muted_clip_name,
    }


def _encode_params() -> list[str]:
    # Fast default profile focused on throughput while preserving visual quality.
    # NVIDIA is preferred when available to make large scene batches much faster.
    if _nvenc_runtime_available():
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p4",
            "-cq",
            "21",
            "-rc",
            "vbr_hq",
            "-b:v",
            "0",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
        ]
    return [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
    ]


def _extract_scene(
    idx: int,
    start_sec: float,
    end_sec: float,
    input_video: Path,
    clips_dir: Path,
    thumbs_dir: Path,
    encode_params: list[str],
) -> dict[str, Any]:
    duration = end_sec - start_sec
    clip_name = f"scene_{idx:04d}.mp4"
    muted_clip_name = f"scene_{idx:04d}_muted.mp4"
    thumb_name = f"scene_{idx:04d}.jpg"
    clip_path = clips_dir / clip_name
    muted_clip_path = clips_dir / muted_clip_name
    thumb_path = thumbs_dir / thumb_name

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_sec:.6f}",
        "-to",
        f"{end_sec:.6f}",
        "-i",
        str(input_video),
        "-threads",
        "1",
        *encode_params,
        str(clip_path),
    ]
    try:
        _run(ffmpeg_cmd)
    except RuntimeError as exc:
        # If GPU init fails unexpectedly, retry this scene with CPU settings.
        if "nvcuda.dll" in str(exc).lower() or "h264_nvenc" in str(exc).lower():
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{start_sec:.6f}",
                    "-to",
                    f"{end_sec:.6f}",
                    "-i",
                    str(input_video),
                    "-threads",
                    "1",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-movflags",
                    "+faststart",
                    str(clip_path),
                ]
            )
        else:
            raise

    # Thumbnail from the produced clip avoids decoding source video again.
    _run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            "00:00:00.150",
            "-i",
            str(clip_path),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(thumb_path),
        ]
    )

    # Fast muted version generated from exported scene clip.
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(clip_path),
            "-c:v",
            "copy",
            "-an",
            str(muted_clip_path),
        ]
    )

    return {
        "scene_number": idx,
        "start_seconds": round(start_sec, 3),
        "end_seconds": round(end_sec, 3),
        "duration_seconds": round(duration, 3),
        "start_timestamp": _fmt_time(start_sec),
        "end_timestamp": _fmt_time(end_sec),
        "duration_timestamp": _fmt_time(duration),
        "thumbnail_name": thumb_name,
        "clip_name": clip_name,
        "muted_clip_name": muted_clip_name,
    }


def _detect_and_split(job_id: str) -> None:
    job = jobs[job_id]
    assert job.input_video is not None
    assert job.output_dir is not None

    try:
        method = _scene_detection_method()
        _set_job(job_id, status="processing", progress=2, stage="Initializing detector")
        _append_log(job_id, f"Initializing scene detector ({method}).")

        _set_job(job_id, progress=8, stage="Analyzing video for scene boundaries")
        if method == "ffmpeg":
            _append_log(job_id, "Analyzing cuts with FFmpeg (low-memory mode).")
            time_segments = _detect_scenes_ffmpeg(job.input_video)
        else:
            time_segments = _detect_scenes_pyscenedetect(job.input_video, job_id)

        gc.collect()
        _set_job(job_id, progress=62, stage="Preparing clips")
        _append_log(job_id, "Scene analysis complete. Preparing clip export.")

        output_clips_dir = job.output_dir / "clips"
        thumbs_dir = job.output_dir / "thumbs"
        output_clips_dir.mkdir(parents=True, exist_ok=True)
        thumbs_dir.mkdir(parents=True, exist_ok=True)

        segments: list[tuple[int, float, float]] = []
        for idx, (start_sec, end_sec) in enumerate(time_segments, start=1):
            segments.append((idx, start_sec, end_sec))

        total = len(segments)
        encode_params = _encode_params()
        _set_job(job_id, expected_scenes=total, scenes=[])
        _append_log(job_id, f"Detected {total} scenes.")
        max_workers = _max_export_workers()
        _set_job(
            job_id,
            stage=f"Exporting clips ({max_workers} worker{'s' if max_workers != 1 else ''})",
            progress=64,
        )
        _append_log(job_id, f"Export started with {max_workers} parallel worker(s).")

        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    _extract_scene,
                    idx,
                    start_sec,
                    end_sec,
                    job.input_video,
                    output_clips_dir,
                    thumbs_dir,
                    encode_params,
                ): idx
                for idx, start_sec, end_sec in segments
            }
            for future in as_completed(futures):
                completed += 1
                item = future.result()
                payload_item = _scene_api_payload(job_id, item)
                with jobs_lock:
                    job_ref = jobs[job_id]
                    job_ref.scenes = sorted(
                        [s for s in job_ref.scenes if s["scene_number"] != item["scene_number"]]
                        + [payload_item],
                        key=lambda s: s["scene_number"],
                    )
                step = 64 + int((completed / max(total, 1)) * 31)
                _set_job(
                    job_id,
                    progress=min(step, 96),
                    stage=f"Exporting clips ({completed}/{total})",
                )
                _append_log(job_id, f"Clip {item['scene_number']} ready ({completed}/{total}).")

        gc.collect()
        with jobs_lock:
            scenes_payload = list(jobs[job_id].scenes)

        manifest_path = job.output_dir / "manifest.json"
        manifest_path.write_text(json.dumps({"scenes": scenes_payload}, indent=2), encoding="utf-8")

        unmuted_zip = job.output_dir / "all_scenes_unmuted.zip"
        muted_zip = job.output_dir / "all_scenes_muted.zip"
        if unmuted_zip.exists():
            unmuted_zip.unlink()
        if muted_zip.exists():
            muted_zip.unlink()
        _append_log(job_id, "Building ZIP archive (unmuted).")
        with zipfile.ZipFile(unmuted_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for scene in scenes_payload:
                clip_file = output_clips_dir / scene["clip_name"]
                zf.write(clip_file, arcname=scene["clip_name"])
        _append_log(job_id, "Building ZIP archive (muted).")
        with zipfile.ZipFile(muted_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for scene in scenes_payload:
                clip_file = output_clips_dir / scene["muted_clip_name"]
                zf.write(clip_file, arcname=scene["muted_clip_name"])

        if cloudinary_storage.is_enabled() and job.output_dir:
            _append_log(job_id, "Publishing outputs to Cloudinary.")
            _set_job(job_id, progress=97, stage="Publishing outputs to Cloudinary")
            scenes_payload, unmuted_zip_url, muted_zip_url = cloudinary_storage.publish_job_outputs(
                job_id, job.output_dir, scenes_payload
            )
            _set_job(
                job_id,
                scenes=scenes_payload,
                download_all_unmuted_external=unmuted_zip_url,
                download_all_muted_external=muted_zip_url,
            )
            if job.input_video and job.input_video.exists():
                job.input_video.unlink(missing_ok=True)
            shutil.rmtree(job.output_dir, ignore_errors=True)
            job.output_dir = None
            job.input_video = None

        _set_job(job_id, progress=100, status="done", stage="Completed")
        _append_log(job_id, "Processing complete.")
    except Exception as exc:  # noqa: BLE001
        _set_job(job_id, status="failed", stage="Failed", error=str(exc), progress=100)
        _append_log(job_id, f"Failed: {exc}")
    finally:
        _release_job_slot()
        gc.collect()


def _start_job(job_id: str, video_path: Path, source_cloudinary_id: str | None = None) -> None:
    _ensure_job_capacity()
    output_dir = JOBS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    with jobs_lock:
        jobs[job_id] = JobState(
            id=job_id,
            input_video=video_path,
            output_dir=output_dir,
            source_cloudinary_id=source_cloudinary_id,
        )
    worker = threading.Thread(target=_detect_and_split, args=(job_id,), daemon=True)
    worker.start()


def _cleanup_job(job_id: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return

    extra_ids = [job.source_cloudinary_id] if job.source_cloudinary_id else None
    if cloudinary_storage.is_enabled():
        cloudinary_storage.delete_job_assets(job_id, extra_ids)

    if job.output_dir and job.output_dir.exists():
        shutil.rmtree(job.output_dir, ignore_errors=True)
    if job.input_video and job.input_video.exists():
        job.input_video.unlink(missing_ok=True)

    with jobs_lock:
        jobs.pop(job_id, None)


@app.get("/api/config")
def get_config() -> JSONResponse:
    return JSONResponse(
        {
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "cloudinary": cloudinary_storage.public_config(),
            "storage_mode": "cloudinary" if cloudinary_storage.is_enabled() else "local",
            "low_memory_mode": _low_memory_enabled(),
            "scene_detection": _scene_detection_method(),
            "max_concurrent_jobs": _max_concurrent_jobs(),
        }
    )


@app.post("/api/jobs/start")
async def start_job_from_cloudinary(body: CloudinaryJobStart) -> JSONResponse:
    if not cloudinary_storage.is_enabled():
        raise HTTPException(status_code=400, detail="Cloudinary is not configured on the server.")

    ext = Path(body.original_name or "video.mp4").suffix.lower()
    if ext not in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}:
        ext = ".mp4"

    job_id = uuid.uuid4().hex[:12]
    video_path = UPLOADS_DIR / f"{job_id}{ext}"
    try:
        cloudinary_storage.download_source_video(body.source_public_id, video_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not fetch Cloudinary video: {exc}") from exc

    if video_path.stat().st_size > MAX_UPLOAD_BYTES:
        video_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max upload size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    _start_job(job_id, video_path, source_cloudinary_id=body.source_public_id)
    return JSONResponse({"job_id": job_id})


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing file name.")

    ext = Path(file.filename).suffix.lower()
    if ext not in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}:
        raise HTTPException(status_code=400, detail="Unsupported video format.")

    job_id = uuid.uuid4().hex[:12]
    video_path = UPLOADS_DIR / f"{job_id}{ext}"
    output_dir = JOBS_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    bytes_read = 0
    with video_path.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            bytes_read += len(chunk)
            if bytes_read > MAX_UPLOAD_BYTES:
                try:
                    video_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Max upload size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                )
            f.write(chunk)

    _start_job(job_id, video_path)
    return JSONResponse({"job_id": job_id})


@app.api_route("/api/jobs/{job_id}/cleanup", methods=["DELETE", "POST"])
def cleanup_job(job_id: str) -> JSONResponse:
    _cleanup_job(job_id)
    return JSONResponse({"ok": True})


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str) -> JSONResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return JSONResponse(job.to_dict())


@app.get("/api/jobs/{job_id}/clip/{clip_name}")
def get_clip(job_id: str, clip_name: str, download: int = 0) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or not job.output_dir:
        raise HTTPException(status_code=404, detail="Job not found.")

    clip_path = job.output_dir / "clips" / clip_name
    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found.")
    return FileResponse(
        clip_path,
        media_type="video/mp4",
        filename=clip_name if download else None,
    )


@app.get("/api/jobs/{job_id}/thumb/{thumb_name}")
def get_thumbnail(job_id: str, thumb_name: str) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or not job.output_dir:
        raise HTTPException(status_code=404, detail="Job not found.")

    thumb_path = job.output_dir / "thumbs" / thumb_name
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found.")
    return FileResponse(thumb_path, media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/download-all")
def download_all_v2(job_id: str, muted: int = 0) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or not job.output_dir:
        raise HTTPException(status_code=404, detail="Job not found.")
    zip_path = job.output_dir / ("all_scenes_muted.zip" if muted else "all_scenes_unmuted.zip")
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Archive not ready.")
    suffix = "muted" if muted else "unmuted"
    return FileResponse(zip_path, media_type="application/zip", filename=f"{job_id}_scenes_{suffix}.zip")


app.mount("/Images", StaticFiles(directory=IMAGES_DIR), name="images")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web")
