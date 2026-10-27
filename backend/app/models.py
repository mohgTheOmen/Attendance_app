import enum
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Role(str, enum.Enum):
    admin = "admin"
    user = "user"


class AttendanceStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Frequency(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


group_members = Table(
    "group_members",
    Base.metadata,
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True),
)

event_groups = Table(
    "event_groups",
    Base.metadata,
    Column("event_id", ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), default=Role.user)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    groups: Mapped[list["Group"]] = relationship(secondary=group_members, back_populates="members")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[list[User]] = relationship(secondary=group_members, back_populates="groups")


class EventSeries(Base):
    """Recurrence rule; the concrete occurrences are rows in `events`."""

    __tablename__ = "event_series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    frequency: Mapped[Frequency] = mapped_column(Enum(Frequency, name="recurrence_frequency"))
    interval: Mapped[int] = mapped_column(Integer, default=1)
    weekdays: Mapped[str] = mapped_column(String(20), default="")  # "0,2,4" = Mon,Wed,Fri
    until: Mapped[date | None] = mapped_column(Date)
    count: Mapped[int | None] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    events: Mapped[list["Event"]] = relationship(back_populates="series")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    check_in_opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    check_in_closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    late_after_minutes: Mapped[int] = mapped_column(Integer, default=10)
    series_id: Mapped[int | None] = mapped_column(
        ForeignKey("event_series.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    attendances: Mapped[list["Attendance"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )
    groups: Mapped[list[Group]] = relationship(secondary=event_groups, lazy="selectin")
    series: Mapped[EventSeries | None] = relationship(back_populates="events", lazy="joined")


class OcrImport(Base):
    """A batch of photographed paper attendance lists for one event."""

    __tablename__ = "ocr_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Chosen by the admin during review; may be unknown at upload time.
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), index=True)
    engine: Mapped[str] = mapped_column(String(32))
    detected_date: Mapped[date | None] = mapped_column(Date)  # read from the sheet
    date_text: Mapped[str] = mapped_column(String(100), default="")  # the text it was read from
    photo_date: Mapped[date | None] = mapped_column(Date)  # camera EXIF date, a fallback hint
    image_paths: Mapped[str] = mapped_column(Text)  # JSON list of upload-relative paths
    raw_text: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of matched lines
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Attendance(Base):
    __tablename__ = "attendances"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_attendance_event_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    photo_path: Mapped[str] = mapped_column(String(300))
    activity_summary: Mapped[str] = mapped_column(Text)
    location_note: Mapped[str] = mapped_column(String(200), default="")
    declaration: Mapped[bool] = mapped_column(Boolean, default=False)
    is_late: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus, name="attendance_status"), default=AttendanceStatus.pending, index=True
    )
    review_comment: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(16), default="self")  # self | ocr
    ocr_import_id: Mapped[int | None] = mapped_column(ForeignKey("ocr_imports.id", ondelete="SET NULL"))

    event: Mapped[Event] = relationship(back_populates="attendances")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
