"""add parent_chat_id to chats

Revision ID: 001
Revises: 
Create Date: 2026-05-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add parent_chat_id column to chats table
    op.add_column('chats', sa.Column('parent_chat_id', sa.String(36), nullable=True))
    
    # Add foreign key constraint
    op.create_foreign_key(
        'fk_chats_parent_chat',
        'chats', 'chats',
        ['parent_chat_id'], ['id']
    )


def downgrade() -> None:
    # Remove foreign key constraint
    op.drop_constraint('fk_chats_parent_chat', 'chats', type_='foreignkey')
    
    # Remove parent_chat_id column
    op.drop_column('chats', 'parent_chat_id')
