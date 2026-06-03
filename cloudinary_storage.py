from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path
from typing import Any

CLOUDINARY_FOLDER_PREFIX = "framecut"


def is_enabled() -> bool:
    return bool(
        os.getenv("CLOUDINARY_CLOUD_NAME")
        and os.getenv("CLOUDINARY_API_KEY")
        and os.getenv("CLOUDINARY_API_SECRET")
    )


def public_config() -> dict[str, str] | None:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    upload_preset = os.getenv("CLOUDINARY_UPLOAD_PRESET")
    if not cloud_name or not upload_preset:
        return None
    return {"cloud_name": cloud_name, "upload_preset": upload_preset}


def configure() -> None:
    import cloudinary

    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )


def job_folder(job_id: str) -> str:
    return f"{CLOUDINARY_FOLDER_PREFIX}/{job_id}"


def download_source_video(public_id: str, dest_path: Path) -> None:
    import cloudinary.utils

    configure()
    url, _ = cloudinary.utils.cloudinary_url(public_id, resource_type="video", secure=True)
    with urllib.request.urlopen(url, timeout=120) as response, dest_path.open("wb") as out:
        shutil.copyfileobj(response, out)


def upload_file(local_path: Path, public_id: str, resource_type: str) -> dict[str, Any]:
    import cloudinary.uploader

    configure()
    return cloudinary.uploader.upload(
        str(local_path),
        public_id=public_id,
        resource_type=resource_type,
        overwrite=True,
    )


def delete_job_assets(job_id: str, extra_public_ids: list[str] | None = None) -> None:
    import cloudinary.api

    configure()
    prefix = job_folder(job_id)
    for resource_type in ("video", "image", "raw"):
        try:
            cloudinary.api.delete_resources_by_prefix(prefix, resource_type=resource_type)
        except Exception:
            pass

    if extra_public_ids:
        for resource_type in ("video", "image"):
            try:
                cloudinary.api.delete_resources(extra_public_ids, resource_type=resource_type)
            except Exception:
                pass


def publish_job_outputs(job_id: str, output_dir: Path, scenes_payload: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Upload clips/thumbs/zips to Cloudinary and return updated scene URLs + zip URLs."""
    folder = job_folder(job_id)
    resource_ids: list[str] = []
    updated_scenes: list[dict[str, Any]] = []

    clips_dir = output_dir / "clips"
    thumbs_dir = output_dir / "thumbs"

    for scene in scenes_payload:
        clip_name = scene["clip_name"]
        muted_clip_name = scene["muted_clip_name"]
        thumb_name = scene["thumbnail_name"]

        clip_public_id = f"{folder}/{clip_name.rsplit('.', 1)[0]}"
        muted_public_id = f"{folder}/{muted_clip_name.rsplit('.', 1)[0]}"
        thumb_public_id = f"{folder}/{thumb_name.rsplit('.', 1)[0]}"

        clip_res = upload_file(clips_dir / clip_name, clip_public_id, "video")
        muted_res = upload_file(clips_dir / muted_clip_name, muted_public_id, "video")
        thumb_res = upload_file(thumbs_dir / thumb_name, thumb_public_id, "image")

        resource_ids.extend([clip_res["public_id"], muted_res["public_id"], thumb_res["public_id"]])

        updated_scenes.append(
            {
                **scene,
                "thumbnail_url": thumb_res["secure_url"],
                "clip_url": clip_res["secure_url"],
                "muted_clip_url": muted_res["secure_url"],
                "download_unmuted_url": clip_res["secure_url"],
                "download_muted_url": muted_res["secure_url"],
            }
        )

    unmuted_zip_url = None
    muted_zip_url = None
    unmuted_zip = output_dir / "all_scenes_unmuted.zip"
    muted_zip = output_dir / "all_scenes_muted.zip"
    if unmuted_zip.exists():
        zip_res = upload_file(unmuted_zip, f"{folder}/all_scenes_unmuted", "raw")
        resource_ids.append(zip_res["public_id"])
        unmuted_zip_url = zip_res["secure_url"]
    if muted_zip.exists():
        zip_res = upload_file(muted_zip, f"{folder}/all_scenes_muted", "raw")
        resource_ids.append(zip_res["public_id"])
        muted_zip_url = zip_res["secure_url"]

    return updated_scenes, unmuted_zip_url, muted_zip_url
