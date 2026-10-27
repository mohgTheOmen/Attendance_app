"""Import paper attendance lists: upload photos -> OCR + matching -> admin review -> commit.

Nothing is recorded until the admin commits. Whatever the pipeline is unsure about (the date,
and so the event, or who a line refers to) is left for the admin to decide in the review.
"""
import json
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.config import get_settings
from app.deps import DB, AdminUser
from app.metrics import ocr_duration, ocr_imports, ocr_lines
from app.models import Attendance, AttendanceStatus, Event, OcrImport, Role, User
from app.ocr.dates import find_date, photo_taken
from app.ocr.engines import ENGINES, EngineUnavailable, available_engines
from app.ocr.matching import Candidate, match_lines
from app.recurrence import get_zone
from app.routers.admin import expected_users
from app.routers.events import get_event_or_404
from app.schemas import (
    EventOut,
    OcrCommitIn,
    OcrCommitOut,
    OcrImportBrief,
    OcrImportOut,
    OcrImportUpdate,
)
from app.storage import delete_photo, photo_abspath, read_upload_limited, store_image_bytes, unused_photos
from app.timeutil import now_utc

router = APIRouter(prefix="/admin/ocr", tags=["ocr"])

MAX_IMAGES = 10  # per upload
MAX_IMAGES_PER_IMPORT = 20  # after adding more photos to an import
MAX_IMAGE_MB = 15
STORED_IMAGE_PX = 2400  # keep the evidence photo readable when zoomed


def events_on(db, day: date, tz: str) -> list[Event]:
    """Events starting on `day` in the admin's timezone."""
    try:
        zone = get_zone(tz)
    except ValueError:
        zone = get_zone("UTC")
    start = datetime.combine(day, datetime.min.time(), zone)
    return list(db.scalars(
        select(Event).where(Event.starts_at >= start, Event.starts_at < start + timedelta(days=1))
        .order_by(Event.starts_at)
    ))


def _out(db, imp: OcrImport, tz: str = "UTC") -> OcrImportOut:
    day = imp.detected_date or imp.photo_date
    return OcrImportOut(
        id=imp.id, event_id=imp.event_id, engine=imp.engine, created_at=imp.created_at,
        committed_at=imp.committed_at, image_count=len(json.loads(imp.image_paths)),
        detected_date=imp.detected_date, date_text=imp.date_text, photo_date=imp.photo_date,
        event=db.get(Event, imp.event_id) if imp.event_id else None,
        suggested_events=events_on(db, day, tz) if day else [],
        lines=json.loads(imp.result),
        created_attendances=db.scalar(
            select(func.count()).where(Attendance.ocr_import_id == imp.id)) or 0,
    )


def _get(db, import_id: int) -> OcrImport:
    imp = db.get(OcrImport, import_id)
    if imp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return imp


def _match(db, raw_lines: list[tuple[int, str]], event: Event | None) -> list[dict]:
    """Match against all active users; with an event, flag who is outside its audience and
    who already has an attendance for it."""
    users = db.scalars(select(User).where(User.is_active.is_(True), User.role == Role.user)).all()
    audience = set(db.scalars(expected_users(event).with_only_columns(User.id))) if event else None
    present = set(db.scalars(select(Attendance.user_id).where(Attendance.event_id == event.id))) if event else set()
    candidates = [Candidate(u.id, u.full_name, in_audience=audience is None or u.id in audience) for u in users]
    s = get_settings()
    results = match_lines(raw_lines, candidates, already_present=present,
                          match_threshold=s.ocr_match_threshold, review_threshold=s.ocr_review_threshold)
    return [asdict(r) for r in results]


def _raw_lines(imp: OcrImport) -> list[tuple[int, str]]:
    return [(line["image_index"], line["raw"]) for line in json.loads(imp.result)]


def _read_images(files: list[UploadFile], engine: str, first_index: int):
    """Store and OCR uploaded photos. Returns (stored paths, (image_index, text) lines, photo dates).
    On failure nothing stays on disk."""
    lines: list[tuple[int, str]] = []
    paths: list[str] = []
    photo_dates: list[date] = []
    try:
        for i, f in enumerate(files, start=first_index):
            data = read_upload_limited(f, MAX_IMAGE_MB)
            paths.append(store_image_bytes(data, STORED_IMAGE_PX))  # also validates it is an image
            if d := photo_taken(data):
                photo_dates.append(d)
            lines += [(i, text) for text in ENGINES[engine](data)]
            ocr_imports.labels(engine=engine, result="ok").inc()
    except EngineUnavailable as exc:
        ocr_imports.labels(engine=engine, result="error").inc()
        for p in paths:
            delete_photo(p)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    except HTTPException:
        for p in paths:
            delete_photo(p)
        raise
    return paths, lines, photo_dates


@router.get("/engines")
def engines(_: AdminUser) -> dict[str, bool]:
    """Which engines are usable on this server."""
    return available_engines()


@router.get("/events", response_model=list[EventOut])
def events_for_date(_: AdminUser, db: DB, day: date = Query(alias="date"), tz: str = "UTC"):
    return events_on(db, day, tz)


@router.post("/imports", response_model=OcrImportOut, status_code=201)
def create_import(
    admin: AdminUser,
    db: DB,
    files: Annotated[list[UploadFile], File()],
    event_id: Annotated[int | None, Form()] = None,
    engine: Annotated[str, Form(pattern="^(tesseract|azure)$")] = "tesseract",
    tz: Annotated[str, Form()] = "UTC",
):
    """OCR one or more photos of a paper list. The event is optional: when it is not given,
    the date is read from the sheet (or the photo) and matching events are suggested."""
    event = get_event_or_404(db, event_id) if event_id else None
    if not 1 <= len(files) <= MAX_IMAGES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Upload 1 to {MAX_IMAGES} images")

    started = time.perf_counter()
    paths, lines, photo_dates = _read_images(files, engine, first_index=0)
    detected, date_text = find_date([text for _, text in lines])
    results = _match(db, lines, event)
    for r in results:
        ocr_lines.labels(status=r["status"]).inc()
    ocr_duration.labels(engine=engine).observe(time.perf_counter() - started)

    if event is None:  # exactly one event on the detected date -> pre-select it
        day = detected or (photo_dates[0] if photo_dates else None)
        on_day = events_on(db, day, tz) if day else []
        if len(on_day) == 1:
            event = on_day[0]
            results = _match(db, lines, event)

    imp = OcrImport(
        event_id=event.id if event else None, engine=engine, image_paths=json.dumps(paths),
        detected_date=detected, date_text=date_text, photo_date=photo_dates[0] if photo_dates else None,
        created_by=admin.id, raw_text="\n".join(f"[{i}] {t}" for i, t in lines), result=json.dumps(results),
    )
    db.add(imp)
    db.commit()
    return _out(db, imp, tz)


@router.get("/imports", response_model=list[OcrImportBrief])
def list_imports(_: AdminUser, db: DB, event_id: int | None = None):
    stmt = select(OcrImport).order_by(OcrImport.created_at.desc()).limit(50)
    if event_id:
        stmt = stmt.where(OcrImport.event_id == event_id)
    imports = db.scalars(stmt).all()
    created = dict(db.execute(
        select(Attendance.ocr_import_id, func.count())
        .where(Attendance.ocr_import_id.in_([i.id for i in imports]))
        .group_by(Attendance.ocr_import_id)
    ).all())
    titles = dict(db.execute(
        select(Event.id, Event.title).where(Event.id.in_({i.event_id for i in imports if i.event_id}))
    ).all())
    return [
        OcrImportBrief(
            id=i.id, event_id=i.event_id, event_title=titles.get(i.event_id), engine=i.engine,
            created_at=i.created_at, committed_at=i.committed_at,
            image_count=len(json.loads(i.image_paths)), line_count=len(json.loads(i.result)),
            created_attendances=created.get(i.id, 0),
        )
        for i in imports
    ]


@router.get("/imports/{import_id}", response_model=OcrImportOut)
def get_import(import_id: int, _: AdminUser, db: DB, tz: str = "UTC"):
    return _out(db, _get(db, import_id), tz)


@router.patch("/imports/{import_id}", response_model=OcrImportOut)
def choose_event(import_id: int, body: OcrImportUpdate, _: AdminUser, db: DB, tz: str = "UTC"):
    """Set (or change) the event and re-match, so audience and already-present flags apply."""
    imp = _get(db, import_id)
    event = get_event_or_404(db, body.event_id)
    imp.event_id = event.id
    imp.result = json.dumps(_match(db, _raw_lines(imp), event))
    db.commit()
    return _out(db, imp, tz)


@router.post("/imports/{import_id}/images", response_model=OcrImportOut)
def add_images(
    import_id: int,
    _: AdminUser,
    db: DB,
    files: Annotated[list[UploadFile], File()],
    engine: Annotated[str | None, Form(pattern="^(tesseract|azure)$")] = None,
    tz: Annotated[str, Form()] = "UTC",
):
    """Add more photos to an existing import (e.g. the back of the sheet, or a second page).
    New lines are appended - existing line indexes stay stable - and all lines are re-matched
    together, so a student on two photos is reported once and anyone already saved for the
    event shows as already present. Works after a commit too: just commit the new students."""
    imp = _get(db, import_id)
    existing_paths = json.loads(imp.image_paths)
    if not files or len(existing_paths) + len(files) > MAX_IMAGES_PER_IMPORT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"An import holds at most {MAX_IMAGES_PER_IMPORT} photos")
    engine = engine or imp.engine
    started = time.perf_counter()
    paths, new_lines, photo_dates = _read_images(files, engine, first_index=len(existing_paths))

    all_lines = _raw_lines(imp) + new_lines
    event = db.get(Event, imp.event_id) if imp.event_id else None
    results = _match(db, all_lines, event)
    for r in results[len(all_lines) - len(new_lines):]:
        ocr_lines.labels(status=r["status"]).inc()
    ocr_duration.labels(engine=engine).observe(time.perf_counter() - started)

    if imp.detected_date is None:
        imp.detected_date, imp.date_text = find_date([text for _, text in new_lines])
    if imp.photo_date is None and photo_dates:
        imp.photo_date = photo_dates[0]
    imp.image_paths = json.dumps(existing_paths + paths)
    imp.raw_text += "".join(f"\n[{i}] {t}" for i, t in new_lines)
    imp.result = json.dumps(results)
    db.commit()
    return _out(db, imp, tz)


@router.delete("/imports/{import_id}", status_code=204)
def delete_import(import_id: int, _: AdminUser, db: DB, delete_attendances: bool = False):
    """Delete an imported list. The attendances saved from it are kept by default (they stay
    valid records, still showing the list photo); with delete_attendances=true they go too.
    Photos are removed once nothing refers to them."""
    imp = _get(db, import_id)
    photos = json.loads(imp.image_paths)
    saved = db.scalars(select(Attendance).where(Attendance.ocr_import_id == imp.id)).all()
    for a in saved:
        if delete_attendances:
            photos.append(a.photo_path)
            db.delete(a)
        else:
            a.ocr_import_id = None
    db.delete(imp)
    orphaned = unused_photos(db, photos)
    db.commit()
    for p in orphaned:
        delete_photo(p)


@router.get("/imports/{import_id}/images/{n}", response_class=FileResponse)
def get_image(import_id: int, n: int, _: AdminUser, db: DB):
    paths = json.loads(_get(db, import_id).image_paths)
    if not 0 <= n < len(paths):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    return FileResponse(photo_abspath(paths[n]), media_type="image/jpeg")


@router.post("/imports/{import_id}/commit", response_model=OcrCommitOut)
def commit_import(import_id: int, body: OcrCommitIn, admin: AdminUser, db: DB):
    """Create approved attendances for the reviewed entries. Users who already have an
    attendance for the event are skipped, so committing twice is harmless. Different
    selections can be committed to different events (e.g. two sessions on one sheet)."""
    imp = _get(db, import_id)
    event_id = body.event_id or imp.event_id
    if event_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose the event this list belongs to")
    event = get_event_or_404(db, event_id)
    paths = json.loads(imp.image_paths)
    lines = {line["index"]: line for line in json.loads(imp.result)}
    present = set(db.scalars(select(Attendance.user_id).where(Attendance.event_id == event.id)))
    user_ids = {e.user_id for e in body.entries}
    valid = set(db.scalars(select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True))))
    if missing := user_ids - valid:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown or inactive user ids: {sorted(missing)}")

    now = now_utc()
    created = skipped = 0
    for e in body.entries:
        if e.user_id in present:
            skipped += 1
            continue
        line = lines.get(e.line_index) if e.line_index is not None else None
        image = paths[line["image_index"]] if line else paths[0]
        written = f' (written as "{line["raw"]}")' if line else ""
        db.add(Attendance(
            event_id=event.id, user_id=e.user_id, photo_path=image,
            activity_summary=f"Recorded from paper attendance list, import #{imp.id}{written}",
            declaration=False, is_late=False, status=AttendanceStatus.approved,
            reviewed_by=admin.id, reviewed_at=now, submitted_at=now,
            source="ocr", ocr_import_id=imp.id,
        ))
        present.add(e.user_id)
        created += 1
    imp.committed_at = now
    if imp.event_id is None:
        imp.event_id = event.id
    if imp.event_id == event.id:  # refresh statuses so saved students now read "already recorded"
        db.flush()
        imp.result = json.dumps(_match(db, _raw_lines(imp), event))
    db.commit()
    return OcrCommitOut(created=created, skipped_existing=skipped)
