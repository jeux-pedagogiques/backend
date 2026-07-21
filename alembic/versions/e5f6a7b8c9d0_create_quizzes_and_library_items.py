"""Create quizzes and library_items tables with FTS support.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, TSVECTOR


# revision identifiers
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- Quiz table ----
    op.create_table(
        "quizzes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("module_id", sa.Integer(), sa.ForeignKey("module_analyses.id"), nullable=True, index=True),
        sa.Column("titre", sa.String(255), nullable=False),
        sa.Column("nb_questions", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("mode", sa.String(50), nullable=False, server_default="formatif"),
        sa.Column("quiz_data", JSON, nullable=False, server_default="{}"),
        sa.Column("module_title", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ---- Library items table ----
    op.create_table(
        "library_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("game_type", sa.String(50), nullable=False, index=True),
        sa.Column("game_id", sa.Integer(), nullable=False, index=True),
        sa.Column("module_id", sa.Integer(), sa.ForeignKey("module_analyses.id"), nullable=True, index=True),
        sa.Column("titre", sa.String(255), nullable=False),
        sa.Column("niveaux_bloom", JSON, nullable=False, server_default="[]"),
        sa.Column("concepts_cles", JSON, nullable=False, server_default="[]"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="false", index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("search_vector", TSVECTOR, nullable=True),
        sa.UniqueConstraint("game_type", "game_id", name="uq_library_game"),
    )

    # GIN index for full-text search
    op.create_index(
        "ix_library_items_search",
        "library_items",
        ["search_vector"],
        postgresql_using="gin",
    )

    # ---- FTS trigger function ----
    op.execute("""
        CREATE OR REPLACE FUNCTION library_items_search_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('french',
                coalesce(NEW.titre, '') || ' ' ||
                coalesce(
                    array_to_string(
                        ARRAY(SELECT jsonb_array_elements_text(NEW.concepts_cles::jsonb)),
                        ' '
                    ),
                    ''
                )
            );
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_library_items_search
        BEFORE INSERT OR UPDATE ON library_items
        FOR EACH ROW EXECUTE FUNCTION library_items_search_update();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_library_items_search ON library_items;")
    op.execute("DROP FUNCTION IF EXISTS library_items_search_update();")
    op.drop_index("ix_library_items_search", table_name="library_items")
    op.drop_table("library_items")
    op.drop_table("quizzes")
