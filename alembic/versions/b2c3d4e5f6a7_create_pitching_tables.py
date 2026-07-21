"""create pitching tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pitching_sessions
    op.create_table('pitching_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('prof_id', sa.Integer(), nullable=False),
    sa.Column('module_id', sa.Integer(), nullable=True),
    sa.Column('titre', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('statut', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('mode', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['module_id'], ['module_analyses.id'], ),
    sa.ForeignKeyConstraint(['prof_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pitching_sessions_prof_id'), 'pitching_sessions', ['prof_id'], unique=False)

    # pitching_teams
    op.create_table('pitching_teams',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('nom', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('auteur_username', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('score_total', sa.Integer(), nullable=False),
    sa.Column('rang', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['pitching_sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pitching_teams_session_id'), 'pitching_teams', ['session_id'], unique=False)

    # pitching_votes
    op.create_table('pitching_votes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('voter_username', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('voter_user_id', sa.Integer(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('criteria_scores', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['pitching_sessions.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['pitching_teams.id'], ),
    sa.ForeignKeyConstraint(['voter_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pitching_votes_session_id'), 'pitching_votes', ['session_id'], unique=False)
    op.create_index(op.f('ix_pitching_votes_team_id'), 'pitching_votes', ['team_id'], unique=False)

    # pitching_feedbacks
    op.create_table('pitching_feedbacks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=True),
    sa.Column('author_username', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('author_user_id', sa.Integer(), nullable=True),
    sa.Column('texte', sa.Text(), nullable=False),
    sa.Column('sentiment', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['pitching_sessions.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['pitching_teams.id'], ),
    sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pitching_feedbacks_session_id'), 'pitching_feedbacks', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_pitching_feedbacks_session_id'), table_name='pitching_feedbacks')
    op.drop_table('pitching_feedbacks')
    op.drop_index(op.f('ix_pitching_votes_team_id'), table_name='pitching_votes')
    op.drop_index(op.f('ix_pitching_votes_session_id'), table_name='pitching_votes')
    op.drop_table('pitching_votes')
    op.drop_index(op.f('ix_pitching_teams_session_id'), table_name='pitching_teams')
    op.drop_table('pitching_teams')
    op.drop_index(op.f('ix_pitching_sessions_prof_id'), table_name='pitching_sessions')
    op.drop_table('pitching_sessions')
