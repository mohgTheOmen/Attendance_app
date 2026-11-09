"""Make newsletters professor-authored announcements for everyone or one group.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "newsletter_threads",
        sa.Column("audience_all", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    with op.batch_alter_table("newsletter_threads") as batch:
        batch.drop_constraint("ck_newsletter_exactly_one_audience", type_="check")
        batch.create_check_constraint(
            "ck_newsletter_exactly_one_audience",
            "(audience_all = true AND group_id IS NULL AND recipient_user_id IS NULL) OR "
            "(audience_all = false AND group_id IS NOT NULL AND recipient_user_id IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("newsletter_threads") as batch:
        batch.drop_constraint("ck_newsletter_exactly_one_audience", type_="check")
        batch.create_check_constraint(
            "ck_newsletter_exactly_one_audience",
            "(recipient_user_id IS NOT NULL AND group_id IS NULL) OR "
            "(recipient_user_id IS NULL AND group_id IS NOT NULL)",
        )
        batch.drop_column("audience_all")
