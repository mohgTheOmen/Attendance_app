"""Attendance analytics for the charts on the admin Attendances page.

Two kinds of numbers:
- volume (trend, weekday): counted from the attendances matching every filter;
- rates (turnout, per student, per group): need to know who was *expected* at which event,
  so they are computed over past events in scope, counting any non-rejected attendance as
  present. Status/source/late filters therefore don't change rates, only volumes.

Aggregation is done in Python so it behaves the same on SQLite and Postgres.
"""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.models import Attendance, AttendanceStatus, Event, Role, User
from app.recurrence import get_zone
from app.timeutil import as_utc, now_utc

MAX_EVENTS = 300
MAX_BUCKETS = 120
AT_RISK_RATE = 0.5


def _bucket(d: date, granularity: str) -> date:
    if granularity == "week":
        return d - timedelta(days=d.weekday())
    if granularity == "month":
        return d.replace(day=1)
    return d


def _next(d: date, granularity: str) -> date:
    if granularity == "week":
        return d + timedelta(days=7)
    if granularity == "month":
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return d + timedelta(days=1)


def volume(db, filtered_ids, tz: str, granularity: str) -> dict:
    """Trend per period and distribution per weekday, from the filtered attendances."""
    zone = _zone(tz)
    rows = db.execute(
        select(Event.starts_at, Attendance.source, Attendance.is_late)
        .join(Event, Event.id == Attendance.event_id)
        .where(Attendance.id.in_(filtered_ids))
    ).all()
    buckets: dict[date, dict] = defaultdict(lambda: {"self": 0, "ocr": 0, "late": 0})
    weekday = [0] * 7
    for starts_at, source, is_late in rows:
        local = as_utc(starts_at).astimezone(zone).date()
        b = buckets[_bucket(local, granularity)]
        b[source if source in ("self", "ocr") else "self"] += 1
        b["late"] += bool(is_late)
        weekday[local.weekday()] += 1

    trend = []
    if buckets:  # fill empty periods so gaps show as zero instead of being skipped
        start, end = min(buckets), max(buckets)
        d = start
        while d <= end and len(trend) < MAX_BUCKETS:
            trend.append({"period": d, **buckets.get(d, {"self": 0, "ocr": 0, "late": 0})})
            d = _next(d, granularity)
        if d <= end:  # too many periods: keep the most recent ones
            trend = [{"period": k, **v} for k, v in sorted(buckets.items())][-MAX_BUCKETS:]
    return {"trend": trend, "by_weekday": weekday}


def rates(db, f, series_id: int | None) -> dict:
    """Turnout and per-student / per-group attendance rates over past events in scope."""
    ev_stmt = select(Event).options(selectinload(Event.groups)).where(Event.starts_at <= now_utc())
    if f.event_id:
        ev_stmt = ev_stmt.where(Event.id == f.event_id)
    if series_id:
        ev_stmt = ev_stmt.where(Event.series_id == series_id)
    if f.date_from:
        ev_stmt = ev_stmt.where(Event.starts_at >= f.date_from)
    if f.date_to:
        ev_stmt = ev_stmt.where(Event.starts_at <= f.date_to)
    events = db.scalars(ev_stmt.order_by(Event.starts_at.desc()).limit(MAX_EVENTS)).all()

    st_stmt = (select(User).options(selectinload(User.groups))
               .where(User.is_active.is_(True), User.role == Role.user))
    if f.user_id:
        st_stmt = st_stmt.where(User.id == f.user_id)
    if f.q:
        like = f"%{f.q.lower()}%"
        st_stmt = st_stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.email).like(like)))
    students = db.scalars(st_stmt).all()
    if f.group_id:
        students = [u for u in students if any(g.id == f.group_id for g in u.groups)]
    user_groups = {u.id: {g.id for g in u.groups} for u in students}
    group_names = {g.id: g.name for u in students for g in u.groups}

    present = set(db.execute(
        select(Attendance.event_id, Attendance.user_id).where(
            Attendance.event_id.in_([e.id for e in events]),
            Attendance.status != AttendanceStatus.rejected,
        )
    ).all())

    expected_n: dict[int, int] = defaultdict(int)
    attended_n: dict[int, int] = defaultdict(int)
    group_exp: dict[int, int] = defaultdict(int)
    group_att: dict[int, int] = defaultdict(int)
    turnouts = []
    for e in events:
        audience = {g.id for g in e.groups}
        exp = [uid for uid, gs in user_groups.items() if not audience or gs & audience]
        if not exp:
            continue
        here = sum((e.id, uid) in present for uid in exp)
        turnouts.append(here / len(exp))
        for uid in exp:
            was_here = (e.id, uid) in present
            expected_n[uid] += 1
            attended_n[uid] += was_here
            # a student counts towards each of their groups this event was meant for
            for gid in (user_groups[uid] & audience) if audience else user_groups[uid]:
                group_exp[gid] += 1
                group_att[gid] += was_here

    names = {u.id: u.full_name for u in students}
    per_student = [
        {"user_id": uid, "full_name": names[uid], "attended": attended_n[uid], "expected": n,
         "rate": round(attended_n[uid] / n, 4)}
        for uid, n in expected_n.items()
    ]
    low = sorted(per_student, key=lambda s: (s["rate"], -s["expected"], s["full_name"]))[:10]
    high = sorted(per_student, key=lambda s: (-s["rate"], -s["attended"], s["full_name"]))[:10]
    groups = sorted(
        ({"group_id": gid, "group": group_names[gid], "attended": group_att[gid], "expected": group_exp[gid],
          "rate": round(group_att[gid] / group_exp[gid], 4)} for gid in group_exp),
        key=lambda g: -g["rate"],
    )
    return {
        "events_in_scope": len(turnouts),
        "avg_turnout": round(sum(turnouts) / len(turnouts), 4) if turnouts else None,
        "students_low": low,
        "students_high": high,
        "group_rates": groups,
        "at_risk": sum(1 for s in per_student if s["rate"] < AT_RISK_RATE and s["expected"] >= 2),
        "students_in_scope": len(per_student),
    }


def _zone(tz: str):
    try:
        return get_zone(tz)
    except ValueError:
        return get_zone("UTC")
