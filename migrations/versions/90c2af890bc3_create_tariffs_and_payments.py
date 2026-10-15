"""create tariffs and payments

Revision ID: 90c2af890bc3
Revises:
Create Date: 2026-10-15 20:53:42.338427

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "90c2af890bc3"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tariffs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    # Миграция не импортирует `app`: модели меняются, а миграция должна создавать ту схему, что была
    # на момент её написания. Поэтому enum-колонки — VARCHAR + явный CHECK (так их создаёт `Enum`
    # с `native_enum=False`), а `UTCDateTime` — его тип в БД, `DateTime(timezone=True)`.
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tariff_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("installment_months", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("discount", sa.Integer(), nullable=False),
        sa.Column("promo_code", sa.String(length=32), nullable=True),
        sa.Column("schedule", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("method IN ('card', 'sbp', 'installment')", name="ck_payments_method"),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'refunded')", name="ck_payments_status"
        ),
        sa.ForeignKeyConstraint(["tariff_id"], ["tariffs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("tariffs")
