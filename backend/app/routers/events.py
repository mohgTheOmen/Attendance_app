from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import or_, select, update

from app.config import get_settings
from app.deps import DB, AdminUser, CurrentUser
from app.models import Attendance, Event, EventSeries, Group, OcrImport, Role, User
from app.recurrence import expand
from app.schemas import EventCreate, EventOut, EventUpdate, UserEventOut
from app.storage import delete_photo, unused_photos
from app.timeutil import as_utc, now_utc

router = APIRouter(prefix="/events", tags=["events"])

SCOPE = Query("this", pattern="^(this|future|all)$", description="for recurring events")
TIME_FIELDS = ("starts_at", "ends_at", "check_in_opens_at", "check_in_closes_at")


def is_check_in_open(event: Event) -> bool:
    return as_utc(event.check_in_opens_at) <= now_utc() <= as_utc(event.check_in_closes_at)


def can_attend(user: User, event: Event) -> bool:
    """Events without groups are open to everyone; otherwise only to group members."""
    if not event.groups:
        return True
    return bool({g.id for g in event.groups} & {g.id for g in user.groups})


def visible_to(user: User):
    """SQL filter: events the user is allowed to see."""
    return or_(~Event.groups.any(), Event.groups.any(Group.id.in_([g.id for g in user.groups])))


def _apply_defaults(event: Event) -> None:
    s = get_settings()
    if event.check_in_opens_at is None:
        event.check_in_opens_at = event.starts_at - timedelta(minutes=s.default_check_in_lead_minutes)
    if event.check_in_closes_at is None:
        event.check_in_closes_at = event.ends_at
    if event.late_after_minutes is None:
        event.late_after_minutes = s.default_late_after_minutes


def _validate(event: Event) -> None:
    if as_utc(event.ends_at) <= as_utc(event.starts_at):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ends_at must be after starts_at")
    if as_utc(event.check_in_closes_at) <= as_utc(event.check_in_opens_at):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Check-in window is invalid")


def _load_groups(db, ids: list[int]) -> list[Group]:
    groups = db.scalars(select(Group).where(Group.id.in_(ids))).all() if ids else []
    if len(groups) != len(set(ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown group id")
    return list(groups)


def get_event_or_404(db, event_id: int) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return event


def _targets(db, event: Event, scope: str) -> list[Event]:
    if scope == "this" or event.series_id is None:
        return [event]
    stmt = select(Event).where(Event.series_id == event.series_id)
    if scope == "future":
        stmt = stmt.where(Event.starts_at >= event.starts_at)
    return list(db.scalars(stmt.order_by(Event.starts_at)))


def _user_view(e: Event, status_) -> UserEventOut:
    return UserEventOut(
        **EventOut.model_validate(e).model_dump(),
        check_in_open=is_check_in_open(e),
        my_attendance_status=status_,
    )


@router.get("", response_model=list[UserEventOut])
def list_events(
    user: CurrentUser,
    db: DB,
    scope: str = Query("relevant", pattern="^(relevant|all)$"),
):
    """Users see events for their groups whose check-in hasn't closed more than a week ago
    and that open within 60 days; admins can request all."""
    stmt = select(Event).order_by(Event.starts_at.desc())
    if user.role != Role.admin:
        stmt = stmt.where(visible_to(user))
    if scope == "relevant" or user.role != Role.admin:
        stmt = stmt.where(
            Event.check_in_closes_at >= now_utc() - timedelta(days=7),
            Event.check_in_opens_at <= now_utc() + timedelta(days=60),
        )
    events = db.scalars(stmt).all()
    mine = {
        a.event_id: a.status
        for a in db.scalars(select(Attendance).where(Attendance.user_id == user.id))
    }
    return [_user_view(e, mine.get(e.id)) for e in events]


@router.get("/{event_id}", response_model=UserEventOut)
def get_event(event_id: int, user: CurrentUser, db: DB):
    e = get_event_or_404(db, event_id)
    if user.role != Role.admin and not can_attend(user, e):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    att = db.scalar(select(Attendance).where(Attendance.event_id == e.id, Attendance.user_id == user.id))
    return _user_view(e, att.status if att else None)


@router.post("", response_model=list[EventOut], status_code=201)
def create_event(body: EventCreate, admin: AdminUser, db: DB):
    """Create one event, or every occurrence of a recurring event."""
    data = body.model_dump(exclude={"recurrence", "group_ids"})
    groups = _load_groups(db, body.group_ids)
    template = Event(**data, created_by=admin.id)
    _apply_defaults(template)
    _validate(template)

    starts = [template.starts_at]
    series = None
    if r := body.recurrence:
        try:
            starts = expand(
                template.starts_at, frequency=r.frequency, interval=r.interval, weekdays=r.weekdays,
                until=r.until, count=r.count, timezone=r.timezone,
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        if not starts:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Recurrence produces no occurrences")
        series = EventSeries(
            frequency=r.frequency, interval=r.interval, weekdays=",".join(map(str, r.weekdays)),
            until=r.until, count=r.count, timezone=r.timezone,
        )
        db.add(series)

    base = as_utc(template.starts_at)
    offsets = {f: as_utc(getattr(template, f)) - base for f in TIME_FIELDS}
    events = []
    for start in starts:
        e = Event(
            title=template.title, description=template.description, location=template.location,
            late_after_minutes=template.late_after_minutes, created_by=admin.id,
            series=series, groups=list(groups),
            **{f: start + offsets[f] for f in TIME_FIELDS},
        )
        db.add(e)
        events.append(e)
    db.commit()
    return events


@router.patch("/{event_id}", response_model=list[EventOut])
def update_event(event_id: int, body: EventUpdate, _: AdminUser, db: DB, scope: str = SCOPE):
    """Edit an occurrence, or this-and-future / all occurrences of its series.
    Time changes are applied to every targeted occurrence as the same shift."""
    event = get_event_or_404(db, event_id)
    data = body.model_dump(exclude_unset=True)
    group_ids = data.pop("group_ids", None)
    groups = _load_groups(db, group_ids) if group_ids is not None else None

    shifts = {}
    for f in TIME_FIELDS:
        if (v := data.pop(f, None)) is not None:
            if v.tzinfo is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{f} must include a timezone offset")
            shifts[f] = as_utc(v) - as_utc(getattr(event, f))

    targets = _targets(db, event, scope)
    for e in targets:
        for k, v in data.items():
            if v is not None:
                setattr(e, k, v)
        for f, delta in shifts.items():
            setattr(e, f, as_utc(getattr(e, f)) + delta)
        if groups is not None:
            e.groups = list(groups)
        _validate(e)
    db.commit()
    return targets


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: int, _: AdminUser, db: DB, scope: str = SCOPE):
    """Delete events with their attendances. Paper-list imports for them are kept, unassigned
    (they can be pointed at another event), so their photos stay too."""
    event = get_event_or_404(db, event_id)
    targets = _targets(db, event, scope)
    photos = [a.photo_path for e in targets for a in e.attendances]
    db.execute(update(OcrImport).where(OcrImport.event_id.in_([e.id for e in targets])).values(event_id=None))
    for e in targets:
        db.delete(e)
    orphaned = unused_photos(db, photos)
    db.commit()
    for p in orphaned:
        delete_photo(p)
