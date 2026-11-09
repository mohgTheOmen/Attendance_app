"""Group-scoped polls with one vote per student.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "polls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "poll_groups",
        sa.Column("poll_id", sa.Integer(), sa.ForeignKey("polls.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_poll_groups_group_id", "poll_groups", ["group_id"])
    op.create_table(
        "poll_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("poll_id", sa.Integer(), sa.ForeignKey("polls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.UniqueConstraint("id", "poll_id", name="uq_poll_option_id_poll"),
    )
    op.create_index("ix_poll_options_poll_id", "poll_options", ["poll_id"])
    op.create_table(
        "poll_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("poll_id", sa.Integer(), sa.ForeignKey("polls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("option_id", sa.Integer(), nullable=False),
        sa.UniqueConstraint("poll_id", "user_id", name="uq_poll_vote_poll_user"),
        sa.ForeignKeyConstraint(["option_id", "poll_id"], ["poll_options.id", "poll_options.poll_id"],
                                name="fk_poll_vote_option_poll", ondelete="CASCADE"),
    )
    for column in ("poll_id", "user_id", "option_id"):
        op.create_index(f"ix_poll_votes_{column}", "poll_votes", [column])


def downgrade() -> None:
    op.drop_table("poll_votes")
    op.drop_table("poll_options")
    op.drop_table("poll_groups")
    op.drop_table("polls")
