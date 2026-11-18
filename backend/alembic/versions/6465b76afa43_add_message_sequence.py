"""add message sequence

Revision ID: 6465b76afa43
Revises: 0df8df84f938
Create Date: 2026-11-18 20:27:32.511312

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6465b76afa43'
down_revision: Union[str, Sequence[str], None] = '0df8df84f938'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("sequence_no", sa.Integer(), nullable=True),
    )

    op.execute(
        """
        WITH numbered AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY conversation_id
                    ORDER BY
                        created_at,
                        CASE WHEN role = 'user' THEN 0 ELSE 1 END,
                        id
                ) AS sequence_no
            FROM messages
        )
        UPDATE messages AS m
        SET sequence_no = numbered.sequence_no
        FROM numbered
        WHERE m.id = numbered.id
        """
    )

    op.alter_column(
        "messages",
        "sequence_no",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_unique_constraint(
        "uq_messages_conversation_sequence",
        "messages",
        ["conversation_id", "sequence_no"],
    )
    op.create_check_constraint(
        "ck_messages_sequence_positive",
        "messages",
        "sequence_no > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_messages_sequence_positive",
        "messages",
        type_="check",
    )
    op.drop_constraint(
        "uq_messages_conversation_sequence",
        "messages",
        type_="unique",
    )
    op.drop_column("messages", "sequence_no")
