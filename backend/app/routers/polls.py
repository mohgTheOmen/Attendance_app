from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import AdminUser, CurrentUser, DB
from app.models import Group, Poll, PollOption, PollVote, Role, User
from app.voting_schemas import PollCreate, PollOut, VoteCreate

router = APIRouter(prefix="/polls", tags=["polls"])


def visible_to(user: User):
    return Poll.groups.any(Group.id.in_([group.id for group in user.groups]))


def poll_results(db: Session, polls: list[Poll], user: User) -> list[PollOut]:
    """Expose only aggregate counts and the caller's participation flag."""
    if not polls:
        return []
    ids = [poll.id for poll in polls]
    counts = dict(db.execute(
        select(PollVote.option_id, func.count(PollVote.id))
        .where(PollVote.poll_id.in_(ids)).group_by(PollVote.option_id)
    ).all())
    voted = set(db.scalars(
        select(PollVote.poll_id).where(PollVote.poll_id.in_(ids), PollVote.user_id == user.id)
    )) if user.role == Role.user else set()
    return [PollOut(
        id=poll.id, subject=poll.subject, is_open=poll.is_open, created_at=poll.created_at,
        groups=poll.groups,
        options=[{"id": option.id, "label": option.label, "vote_count": counts.get(option.id, 0)}
                 for option in poll.options],
        total_votes=sum(counts.get(option.id, 0) for option in poll.options),
        has_voted=poll.id in voted,
    ) for poll in polls]


def get_locked_poll(db: Session, poll_id: int, user: User) -> Poll:
    # Voting and closing take the same row lock. A vote that waits for a close
    # observes the committed closed state under PostgreSQL READ COMMITTED.
    stmt = select(Poll).where(Poll.id == poll_id).with_for_update()
    if user.role != Role.admin:
        stmt = stmt.where(visible_to(user))
    poll = db.scalar(stmt)
    if poll is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Poll not found")
    return poll


@router.get("", response_model=list[PollOut])
def list_polls(user: CurrentUser, db: DB):
    stmt = select(Poll).order_by(Poll.created_at.desc(), Poll.id.desc())
    if user.role != Role.admin:
        stmt = stmt.where(visible_to(user))
    return poll_results(db, list(db.scalars(stmt)), user)


@router.post("", response_model=PollOut, status_code=201)
def create_poll(body: PollCreate, user: AdminUser, db: DB):
    groups = list(db.scalars(select(Group).where(Group.id.in_(body.group_ids))))
    if len(groups) != len(body.group_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown group id")
    poll = Poll(subject=body.subject, groups=groups,
                options=[PollOption(label=label) for label in body.options])
    db.add(poll)
    db.commit()
    return poll_results(db, [poll], user)[0]


@router.post("/{poll_id}/close", response_model=PollOut)
def close_poll(poll_id: int, user: AdminUser, db: DB):
    poll = get_locked_poll(db, poll_id, user)
    poll.is_open = False
    db.commit()
    return poll_results(db, [poll], user)[0]


@router.post("/{poll_id}/votes", response_model=PollOut, status_code=201)
def cast_vote(poll_id: int, body: VoteCreate, user: CurrentUser, db: DB):
    if user.role != Role.user:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only students can vote")
    poll = get_locked_poll(db, poll_id, user)
    if not poll.is_open:
        raise HTTPException(status.HTTP_409_CONFLICT, "This poll is closed")
    if db.scalar(select(PollVote.id).where(PollVote.poll_id == poll.id, PollVote.user_id == user.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already voted in this poll")
    if body.option_id not in {option.id for option in poll.options}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Option does not belong to this poll")
    db.add(PollVote(poll_id=poll.id, user_id=user.id, option_id=body.option_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # The unique constraint remains the final arbiter across concurrent
        # requests, including engines that do not support SELECT FOR UPDATE.
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already voted in this poll")
    return poll_results(db, [poll], user)[0]
