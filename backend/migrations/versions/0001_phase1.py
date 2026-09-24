"""Phase 1 core schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_phase1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("admin_users", sa.Column("id", sa.String(36), primary_key=True), sa.Column("username", sa.String(100), nullable=False), sa.Column("password_hash", sa.String(300), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_admin_users_username", "admin_users", ["username"], unique=True)
    op.create_table("students", sa.Column("id", sa.String(36), primary_key=True), sa.Column("student_no", sa.String(50), nullable=False), sa.Column("name", sa.String(100), nullable=False), sa.Column("pinyin", sa.String(200)), sa.Column("avatar_path", sa.String(500)), sa.Column("aliases", sa.Text(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_students_student_no", "students", ["student_no"], unique=True)
    op.create_index("ix_students_name", "students", ["name"])
    op.create_index("ix_students_status", "students", ["status"])
    op.create_table("events", sa.Column("id", sa.String(36), primary_key=True), sa.Column("occurred_at", sa.DateTime(), nullable=False), sa.Column("recorded_at", sa.DateTime(), nullable=False), sa.Column("location", sa.String(200)), sa.Column("category", sa.String(100), nullable=False), sa.Column("event_description", sa.Text(), nullable=False), sa.Column("student_response", sa.Text()), sa.Column("teacher_action", sa.Text()), sa.Column("follow_up", sa.Text()), sa.Column("raw_transcript", sa.Text()), sa.Column("record_method", sa.String(20), nullable=False), sa.Column("ai_processed", sa.Boolean(), nullable=False), sa.Column("ai_confidence", sa.Float()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_events_occurred_at", "events", ["occurred_at"])
    op.create_index("ix_events_recorded_at", "events", ["recorded_at"])
    op.create_index("ix_events_category", "events", ["category"])
    op.create_table("tags", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(60), nullable=False))
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)
    op.create_table("event_students", sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True), sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), primary_key=True))
    op.create_table("event_tags", sa.Column("event_id", sa.String(36), sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True), sa.Column("tag_id", sa.String(36), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True))


def downgrade():
    op.drop_table("event_tags")
    op.drop_table("event_students")
    op.drop_table("tags")
    op.drop_table("events")
    op.drop_table("students")
    op.drop_table("admin_users")
