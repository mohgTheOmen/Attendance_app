"""Add direct and group newsletter conversations.

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
        "newsletter_threads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(recipient_user_id IS NOT NULL AND group_id IS NULL) OR "
            "(recipient_user_id IS NULL AND group_id IS NOT NULL)",
            name="ck_newsletter_exactly_one_audience",
        ),
    )
    op.create_index("ix_newsletter_threads_created_by", "newsletter_threads", ["created_by"])
    op.create_index("ix_newsletter_threads_recipient_user_id", "newsletter_threads", ["recipient_user_id"])
    op.create_index("ix_newsletter_threads_group_id", "newsletter_threads", ["group_id"])
    op.create_index("ix_newsletter_threads_updated_at", "newsletter_threads", ["updated_at"])
    op.create_table(
        "newsletter_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("newsletter_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_newsletter_messages_thread_id", "newsletter_messages", ["thread_id"])
    op.create_index("ix_newsletter_messages_author_id", "newsletter_messages", ["author_id"])


def downgrade() -> None:
    op.drop_table("newsletter_messages")
    op.drop_table("newsletter_threads")
