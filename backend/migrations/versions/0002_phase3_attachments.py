"""Phase 3 event attachments."""
from alembic import op
import sqlalchemy as sa

revision = "0002_phase3_attachments"
down_revision = "0001_phase1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(255), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_attachments_event_id", "attachments", ["event_id"])


def downgrade():
    op.drop_index("ix_attachments_event_id", table_name="attachments")
    op.drop_table("attachments")
