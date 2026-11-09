from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.deps import AdminUser, CurrentUser, DB
from app.models import (
    Group,
    NewsletterMessage,
    NewsletterThread,
    Role,
    User,
    group_members,
)
from app.schemas import (
    GroupBrief,
    NewsletterCreate,
    NewsletterRecipient,
    NewsletterReply,
    NewsletterThreadOut,
    UserBrief,
)
from app.timeutil import now_utc

router = APIRouter(prefix="/newsletters", tags=["newsletters"])


def accessible_threads(user: User):
    if user.role == Role.admin:
        return NewsletterThread.id.is_not(None)
    member_groups = select(group_members.c.group_id).where(group_members.c.user_id == user.id)
    return or_(NewsletterThread.audience_all.is_(True), NewsletterThread.group_id.in_(member_groups))


def load_thread(db, thread_id: int, user: User) -> NewsletterThread:
    thread = db.scalar(
        select(NewsletterThread)
        .where(NewsletterThread.id == thread_id, accessible_threads(user))
        .options(
            selectinload(NewsletterThread.creator),
            selectinload(NewsletterThread.recipient),
            selectinload(NewsletterThread.group),
            selectinload(NewsletterThread.messages).selectinload(NewsletterMessage.author),
        )
    )
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Newsletter not found")
    return thread


@router.get("/recipients", response_model=NewsletterRecipient)
def recipients(user: CurrentUser, db: DB):
    if user.role == Role.admin:
        groups = db.scalars(select(Group).order_by(Group.name)).all()
    else:
        groups = db.scalars(
            select(Group).join(group_members).where(group_members.c.user_id == user.id).order_by(Group.name)
        ).all()
    return NewsletterRecipient(
        users=[],
        groups=[GroupBrief.model_validate(group) for group in groups],
    )


@router.get("", response_model=list[NewsletterThreadOut])
def list_newsletters(user: CurrentUser, db: DB):
    return db.scalars(
        select(NewsletterThread)
        .where(accessible_threads(user))
        .options(
            selectinload(NewsletterThread.creator),
            selectinload(NewsletterThread.recipient),
            selectinload(NewsletterThread.group),
            selectinload(NewsletterThread.messages).selectinload(NewsletterMessage.author),
        )
        .order_by(NewsletterThread.updated_at.desc(), NewsletterThread.id.desc())
    ).all()


@router.get("/{thread_id}", response_model=NewsletterThreadOut)
def get_newsletter(thread_id: int, user: CurrentUser, db: DB):
    return load_thread(db, thread_id, user)


@router.post("", response_model=NewsletterThreadOut, status_code=201)
def create_newsletter(body: NewsletterCreate, user: AdminUser, db: DB):
    group = db.get(Group, body.group_id) if body.group_id else None
    if body.group_id is not None and group is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown group")

    thread = NewsletterThread(
        subject=body.subject.strip(), created_by=user.id,
        recipient_user_id=None, group_id=body.group_id, audience_all=body.audience_all,
    )
    db.add(thread)
    db.flush()
    db.add(NewsletterMessage(thread_id=thread.id, author_id=user.id, body=body.body.strip()))
    db.commit()
    return load_thread(db, thread.id, user)


@router.post("/{thread_id}/messages", response_model=NewsletterThreadOut, status_code=201)
def reply(thread_id: int, body: NewsletterReply, user: CurrentUser, db: DB):
    load_thread(db, thread_id, user)
    raise HTTPException(status.HTTP_405_METHOD_NOT_ALLOWED, "Newsletters are read-only announcements")
