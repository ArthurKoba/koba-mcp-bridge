"""create control-plane account and invocation tables

Revision ID: 20260923_0001
Revises:
Create Date: 2026-09-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260923_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("alias", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("verify_tls", sa.Boolean(), nullable=False),
        sa.Column("ca_cert_pem", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("encrypted_credential", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("alias", name="uq_accounts_alias"),
    )
    op.create_index("ix_accounts_alias", "accounts", ["alias"])
    op.create_index("ix_accounts_provider", "accounts", ["provider"])
    op.create_index("ix_accounts_role", "accounts", ["role"])
    op.create_index("ix_accounts_enabled", "accounts", ["enabled"])
    op.create_table(
        "invocations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("tool", sa.String(length=256), nullable=False),
        sa.Column("account_id", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("error_type", sa.String(length=256), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "request_id",
        "module",
        "tool",
        "account_id",
        "provider",
        "status",
        "occurred_at",
    ):
        op.create_index(f"ix_invocations_{column}", "invocations", [column])


def downgrade() -> None:
    op.drop_table("invocations")
    op.drop_table("accounts")
