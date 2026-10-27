import io
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def _root() -> Path:
    root = get_settings().upload_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


async def save_photo(upload: UploadFile) -> str:
    """Validate an uploaded image, strip metadata, re-encode as JPEG; return relative path."""
    s = get_settings()
    max_bytes = s.max_upload_mb * 1024 * 1024
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Photo exceeds {s.max_upload_mb} MB")
    return store_image_bytes(data, s.max_image_px)


def read_upload_limited(upload: UploadFile, max_mb: int) -> bytes:
    data = upload.file.read(max_mb * 1024 * 1024 + 1)
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{upload.filename} exceeds {max_mb} MB")
    return data


def store_image_bytes(data: bytes, max_px: int) -> str:
    """Validate image bytes, strip metadata, re-encode as JPEG <= max_px; return relative path."""
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Photo is empty")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()
        if fmt not in ALLOWED_FORMATS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Photo must be JPEG, PNG or WebP")
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File is not a valid image")

    img.thumbnail((max_px, max_px))
    rel = Path(uuid.uuid4().hex[:2]) / f"{uuid.uuid4().hex}.jpg"
    dest = _root() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "JPEG", quality=85, optimize=True)
    return rel.as_posix()


def photo_abspath(rel: str) -> Path:
    root = _root().resolve()
    path = (root / rel).resolve()
    if root not in path.parents:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    return path


def delete_photo(rel: str) -> None:
    try:
        photo_abspath(rel).unlink(missing_ok=True)
    except HTTPException:
        pass


def unused_photos(db, paths) -> list[str]:
    """The paths no attendance or list import refers to any more. A paper-list photo is shared
    by every student on the list and by its import, so it must outlive any single one of them.
    Call after the deletes are flushed and delete the files only once the commit succeeded."""
    from sqlalchemy import func, select

    from app.models import Attendance, OcrImport

    db.flush()
    return [
        p for p in set(paths)
        if not db.scalar(select(func.count()).where(Attendance.photo_path == p))
        and not db.scalar(select(func.count()).where(OcrImport.image_paths.contains(f'"{p}"')))
    ]
