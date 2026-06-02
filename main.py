from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from scenedetect import AdaptiveDetector, ContentDetector, SceneManager, open_video

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
JOBS_DIR = DATA_DIR / "jobs"
STATIC_DIR = BASE_DIR / "web"
IMAGES_DIR = BASE_DIR / "Images"

for p in (UPLOADS_DIR, JOBS_DIR, STATIC_DIR, IMAGES_DIR):
    p.mkdir(parents=True, exist_ok=True)


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

    def to_dict(self) -> dict[str, Any]:
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
            "download_all_unmuted_url": (
                f"/api/jobs/{self.id}/download-all?muted=0" if self.status in {"processing", "done"} else None
            ),
            "download_all_muted_url": (
                f"/api/jobs/{self.id}/download-all?muted=1" if self.status in {"processing", "done"} else None
            ),
        }


jobs: dict[str, JobState] = {}
jobs_lock = threading.Lock()
_nvenc_checked = False
_nvenc_available = False

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


def _video_fps(video_path: Path) -> float:
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    cap.release()
    if fps <= 0:
        return 30.0
    return fps


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
        _set_job(job_id, status="processing", progress=2, stage="Initializing detector")
        _append_log(job_id, "Initializing scene detector.")

        video = open_video(str(job.input_video))
        scene_manager = SceneManager()

        # A hybrid detector setup improves robustness:
        # - Adaptive detector resists false positives from camera motion/light changes.
        # - Content detector catches hard cuts and sharp transitions.
        scene_manager.add_detector(AdaptiveDetector(adaptive_threshold=3.0, min_scene_len=12))
        scene_manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=12))

        _set_job(job_id, progress=8, stage="Analyzing video for scene boundaries")
        _append_log(job_id, "Analyzing visual cuts and transitions.")
        scene_manager.detect_scenes(video=video, show_progress=False)
        scene_list = scene_manager.get_scene_list()

        if not scene_list:
            # Fallback: full video as single scene.
            frame_count = int(video.duration.get_frames())
            fps = _video_fps(job.input_video)
            duration = frame_count / fps if fps > 0 else 0.0
            scene_list = [(video.base_timecode, video.base_timecode + frame_count)]
            _ = duration  # Keep reference for clarity if needed.

        _set_job(job_id, progress=62, stage="Preparing clips")
        _append_log(job_id, "Scene analysis complete. Preparing clip export.")

        output_clips_dir = job.output_dir / "clips"
        thumbs_dir = job.output_dir / "thumbs"
        output_clips_dir.mkdir(parents=True, exist_ok=True)
        thumbs_dir.mkdir(parents=True, exist_ok=True)

        fps = _video_fps(job.input_video)
        segments: list[tuple[int, float, float]] = []
        for idx, (start_tc, end_tc) in enumerate(scene_list, start=1):
            start_sec = start_tc.get_frames() / fps
            end_sec = end_tc.get_frames() / fps
            if end_sec > start_sec:
                segments.append((idx, start_sec, end_sec))

        total = len(segments)
        encode_params = _encode_params()
        _set_job(job_id, expected_scenes=total)
        _append_log(job_id, f"Detected {total} scenes.")
        cpu_count = os.cpu_count() or 4
        max_workers = max(1, min(6, cpu_count // 2))
        _set_job(
            job_id,
            stage=f"Exporting clips in parallel ({max_workers} workers)",
            progress=64,
        )
        _append_log(job_id, f"Export started with {max_workers} parallel workers.")

        results_by_scene: dict[int, dict[str, Any]] = {}
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
                results_by_scene[item["scene_number"]] = item
                partial_payload = []
                for scene_num in sorted(results_by_scene):
                    scene = results_by_scene[scene_num]
                    clip_name = scene["clip_name"]
                    muted_clip_name = scene["muted_clip_name"]
                    thumb_name = scene["thumbnail_name"]
                    partial_payload.append(
                        {
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
                            "clip_name": clip_name,
                            "muted_clip_name": muted_clip_name,
                        }
                    )
                step = 64 + int((completed / max(total, 1)) * 31)
                _set_job(
                    job_id,
                    progress=min(step, 96),
                    stage=f"Exporting clips ({completed}/{total})",
                    scenes=partial_payload,
                )
                _append_log(job_id, f"Clip {item['scene_number']} ready ({completed}/{total}).")

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

        _set_job(job_id, scenes=scenes_payload, progress=100, status="done", stage="Completed")
        _append_log(job_id, "Processing complete.")
    except Exception as exc:  # noqa: BLE001
        _set_job(job_id, status="failed", stage="Failed", error=str(exc), progress=100)
        _append_log(job_id, f"Failed: {exc}")


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

    with video_path.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    with jobs_lock:
        jobs[job_id] = JobState(id=job_id, input_video=video_path, output_dir=output_dir)

    worker = threading.Thread(target=_detect_and_split, args=(job_id,), daemon=True)
    worker.start()

    return JSONResponse({"job_id": job_id})


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
