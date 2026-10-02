"""Initial StudyAgent schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("code", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("term", sa.String(length=100), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("url"),
    )
    op.create_index("ix_courses_external_id", "courses", ["external_id"])
    op.create_index("ix_courses_code", "courses", ["code"])
    op.create_table(
        "assessments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(length=36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("assessment_type", sa.String(length=50), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("weight_percent", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.UniqueConstraint("course_id", "title", "due_at", name="uq_assessment_course_title_due"),
    )
    op.create_index("ix_assessments_course_id", "assessments", ["course_id"])
    op.create_index("ix_assessments_due_at", "assessments", ["due_at"])
    op.create_table(
        "announcements",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(length=36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "course_id", "title", "published_at", name="uq_announcement_course_title_date"
        ),
    )
    op.create_index("ix_announcements_course_id", "announcements", ["course_id"])
    op.create_table(
        "resources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(length=36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=30), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("local_path", sa.String(length=2048), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("processed", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_resources_course_id", "resources", ["course_id"])
    op.create_table(
        "topics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(length=36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "source_resource_id",
            sa.String(length=36),
            sa.ForeignKey("resources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mastery", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.UniqueConstraint("course_id", "name", name="uq_topic_course_name"),
    )
    op.create_index("ix_topics_course_id", "topics", ["course_id"])
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("courses_found", sa.Integer(), nullable=False),
        sa.Column("assessments_found", sa.Integer(), nullable=False),
        sa.Column("resources_found", sa.Integer(), nullable=False),
        sa.Column("changes_found", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "change_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "class_meetings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(length=36),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    for table in (
        "class_meetings",
        "change_events",
        "sync_runs",
        "topics",
        "resources",
        "announcements",
        "assessments",
        "courses",
    ):
        op.drop_table(table)
