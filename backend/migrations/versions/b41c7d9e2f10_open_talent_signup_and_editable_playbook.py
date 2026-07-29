"""open talent sign-up + editable playbook requirement docs

Revision ID: b41c7d9e2f10
Revises: 1898188f191f
Create Date: 2026-07-28 21:10:00.000000

Two additive columns, both nullable:

* `talents.signup_source` — 'self' when a talent registered themselves through
  the portal, 'agency' when GDF added them. Existing rows stay NULL and read as
  agency-added, so nothing has to be backfilled.
* `requirement_documents.updated_at` / `updated_by` — requirement documents
  became editable in place from the Playbook; these record who last touched one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b41c7d9e2f10'
down_revision: Union[str, Sequence[str], None] = '1898188f191f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('talents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('signup_source', sa.String(length=20), nullable=True))

    with op.batch_alter_table('requirement_documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('updated_by', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_requirement_documents_updated_by_users',
                                    'users', ['updated_by'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('requirement_documents', schema=None) as batch_op:
        batch_op.drop_constraint('fk_requirement_documents_updated_by_users', type_='foreignkey')
        batch_op.drop_column('updated_by')
        batch_op.drop_column('updated_at')

    with op.batch_alter_table('talents', schema=None) as batch_op:
        batch_op.drop_column('signup_source')
