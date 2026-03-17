"""add course/document/curriculum and exam versioning structures

Revision ID: 7b8d5f4e2c21
Revises: 4e7a9c2f1d11
Create Date: 2026-03-17 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7b8d5f4e2c21"
down_revision: Union[str, None] = "4e7a9c2f1d11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("course_name", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("academic_level", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "course_memberships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "user_id", name="uq_course_membership_course_user"),
    )

    op.add_column("textbooks", sa.Column("course_id", sa.String(), nullable=True))
    op.add_column("textbooks", sa.Column("file_storage_url", sa.String(length=1000), nullable=True))
    op.add_column("textbooks", sa.Column("file_hash", sa.String(length=128), nullable=True))
    op.add_column("textbooks", sa.Column("language", sa.String(length=20), nullable=True))
    op.add_column("textbooks", sa.Column("total_pages_or_slides", sa.Integer(), nullable=True))
    op.add_column("textbooks", sa.Column("parse_error_message", sa.Text(), nullable=True))
    op.add_column("textbooks", sa.Column("curriculum_tree_json", sa.JSON(), nullable=True))
    op.create_foreign_key("fk_textbooks_course_id", "textbooks", "courses", ["course_id"], ["id"])

    op.create_table(
        "sections",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("parent_section_id", sa.String(), nullable=True),
        sa.Column("section_title", sa.String(length=500), nullable=False),
        sa.Column("section_type", sa.String(length=50), nullable=False),
        sa.Column("section_order", sa.Integer(), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("scope_label", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["textbooks.id"]),
        sa.ForeignKeyConstraint(["parent_section_id"], ["sections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "learning_objectives",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=True),
        sa.Column("objective_text", sa.Text(), nullable=False),
        sa.Column("objective_level", sa.String(length=100), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("exams", sa.Column("course_id", sa.String(), nullable=True))
    op.create_foreign_key("fk_exams_course_id", "exams", "courses", ["course_id"], ["id"])

    op.create_table(
        "exam_specs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("exam_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=True),
        sa.Column("creator_user_id", sa.String(), nullable=False),
        sa.Column("exam_type", sa.String(length=50), nullable=False),
        sa.Column("time_limit_minutes", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("strict_scope_flag", sa.Boolean(), nullable=False),
        sa.Column("bloom_distribution_json", sa.JSON(), nullable=True),
        sa.Column("question_mix_json", sa.JSON(), nullable=True),
        sa.Column("formatting_preferences_json", sa.JSON(), nullable=True),
        sa.Column("total_questions", sa.Integer(), nullable=False),
        sa.Column("selected_scope_json", sa.JSON(), nullable=True),
        sa.Column("source_prompt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["creator_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_id"),
    )

    op.create_table(
        "blueprint_cells",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("exam_spec_id", sa.String(), nullable=False),
        sa.Column("cell_key", sa.String(length=255), nullable=False),
        sa.Column("scope_unit_json", sa.JSON(), nullable=False),
        sa.Column("question_type", sa.String(length=50), nullable=False),
        sa.Column("bloom_level", sa.String(length=50), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("generated_count", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("overgenerate_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["exam_spec_id"], ["exam_specs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "exam_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("exam_id", sa.String(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("parent_version_id", sa.String(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"]),
        sa.ForeignKeyConstraint(["parent_version_id"], ["exam_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("exams", sa.Column("current_version_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_exams_current_version_id",
        "exams",
        "exam_versions",
        ["current_version_id"],
        ["id"],
    )

    op.add_column("exam_questions", sa.Column("exam_version_id", sa.String(), nullable=True))
    op.add_column(
        "exam_questions",
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_exam_questions_exam_version_id",
        "exam_questions",
        "exam_versions",
        ["exam_version_id"],
        ["id"],
    )

    op.create_table(
        "edit_operations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("exam_version_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("edit_type", sa.String(length=50), nullable=False),
        sa.Column("target_question_id", sa.String(length=255), nullable=True),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("prompt_used", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["exam_version_id"], ["exam_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("edit_operations")
    op.drop_constraint("fk_exam_questions_exam_version_id", "exam_questions", type_="foreignkey")
    op.drop_column("exam_questions", "is_locked")
    op.drop_column("exam_questions", "exam_version_id")

    op.drop_constraint("fk_exams_current_version_id", "exams", type_="foreignkey")
    op.drop_column("exams", "current_version_id")
    op.drop_table("exam_versions")
    op.drop_table("blueprint_cells")
    op.drop_table("exam_specs")
    op.drop_constraint("fk_exams_course_id", "exams", type_="foreignkey")
    op.drop_column("exams", "course_id")

    op.drop_table("learning_objectives")
    op.drop_table("sections")

    op.drop_constraint("fk_textbooks_course_id", "textbooks", type_="foreignkey")
    op.drop_column("textbooks", "curriculum_tree_json")
    op.drop_column("textbooks", "parse_error_message")
    op.drop_column("textbooks", "total_pages_or_slides")
    op.drop_column("textbooks", "language")
    op.drop_column("textbooks", "file_hash")
    op.drop_column("textbooks", "file_storage_url")
    op.drop_column("textbooks", "course_id")

    op.drop_table("course_memberships")
    op.drop_table("courses")
