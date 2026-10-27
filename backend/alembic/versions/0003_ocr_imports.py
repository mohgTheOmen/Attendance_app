"""OCR imports of paper attendance lists

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ocr_imports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id", ondelete="SET NULL")),
        sa.Column("engine", sa.String(32), nullable=False),
        sa.Column("detected_date", sa.Date),
        sa.Column("date_text", sa.String(100), nullable=False),
        sa.Column("photo_date", sa.Date),
        sa.Column("image_paths", sa.Text, nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("result", sa.Text, nullable=False),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_ocr_imports_event_id", "ocr_imports", ["event_id"])
    with op.batch_alter_table("attendances") as b:
        b.add_column(sa.Column("source", sa.String(16), nullable=False, server_default="self"))
        b.add_column(sa.Column("ocr_import_id", sa.Integer, nullable=True))
        b.create_foreign_key("fk_attendances_ocr_import_id", "ocr_imports", ["ocr_import_id"], ["id"],
                             ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("attendances") as b:
        b.drop_constraint("fk_attendances_ocr_import_id", type_="foreignkey")
        b.drop_column("ocr_import_id")
        b.drop_column("source")
    op.drop_index("ix_ocr_imports_event_id", "ocr_imports")
    op.drop_table("ocr_imports")
