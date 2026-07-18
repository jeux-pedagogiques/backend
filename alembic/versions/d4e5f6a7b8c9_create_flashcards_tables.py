"""create flashcards tables

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-07-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # flashcard_sets
    op.create_table('flashcard_sets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('module_id', sa.Integer(), nullable=False),
    sa.Column('titre', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('nb_cartes', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['module_id'], ['module_analyses.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_flashcard_sets_user_id'), 'flashcard_sets', ['user_id'], unique=False)
    op.create_index(op.f('ix_flashcard_sets_module_id'), 'flashcard_sets', ['module_id'], unique=False)

    # flashcards
    op.create_table('flashcards',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('set_id', sa.Integer(), nullable=False),
    sa.Column('recto', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('verso', sa.Text(), nullable=False),
    sa.Column('aa_source', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('niveau_bloom', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('ordre', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['set_id'], ['flashcard_sets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_flashcards_set_id'), 'flashcards', ['set_id'], unique=False)

    # flashcard_reviews
    op.create_table('flashcard_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('flashcard_id', sa.Integer(), nullable=False),
    sa.Column('participant_name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('statut', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('review_date', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['flashcard_id'], ['flashcards.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_flashcard_reviews_flashcard_id'), 'flashcard_reviews', ['flashcard_id'], unique=False)
    op.create_index('ix_flashcard_reviews_flashcard_participant', 'flashcard_reviews', ['flashcard_id', 'participant_name'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_flashcard_reviews_flashcard_participant', table_name='flashcard_reviews')
    op.drop_index(op.f('ix_flashcard_reviews_flashcard_id'), table_name='flashcard_reviews')
    op.drop_table('flashcard_reviews')
    op.drop_index(op.f('ix_flashcards_set_id'), table_name='flashcards')
    op.drop_table('flashcards')
    op.drop_index(op.f('ix_flashcard_sets_module_id'), table_name='flashcard_sets')
    op.drop_index(op.f('ix_flashcard_sets_user_id'), table_name='flashcard_sets')
    op.drop_table('flashcard_sets')
