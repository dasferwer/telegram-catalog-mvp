"""Initial catalog, sessions, carts, orders and durable bot state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_states",
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("waiting", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("bot_id", "user_id"),
    )
    op.create_table(
        "bot_updates",
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("reply", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("delivered", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("bot_id", "update_id"),
    )
    op.create_table(
        "owners",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("cart_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("cart_version >= 0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("object_key", sa.String(length=200), nullable=False),
        sa.Column("content_type", sa.String(length=40), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(name) BETWEEN 1 AND 200"),
        sa.CheckConstraint("size > 0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", "update_id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_table(
        "browser_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("csrf", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
        ),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_browser_sessions_owner_id"), "browser_sessions", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_browser_sessions_expires_at"), "browser_sessions", ["expires_at"], unique=False
    )
    op.create_table(
        "cart_items",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity BETWEEN 1 AND 99"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
        ),
        sa.PrimaryKeyConstraint("owner_id", "product_id"),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.UUID(), nullable=False),
        sa.Column("cart_version", sa.BigInteger(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("jsonb_array_length(items) > 0"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "idempotency_key"),
    )
    op.create_index(op.f("ix_orders_owner_id"), "orders", ["owner_id"], unique=False)


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_table("cart_items")
    op.drop_table("browser_sessions")
    op.drop_table("products")
    op.drop_table("owners")
    op.drop_table("bot_updates")
    op.drop_table("admin_states")
