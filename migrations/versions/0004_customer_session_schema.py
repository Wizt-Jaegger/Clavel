"""Opaque registered/anonymous subjects and optionally linked sessions."""

from alembic import op
import sqlalchemy as sa


revision = "0004_customer_session_schema"
down_revision = "0003_inventory_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("opaque_ref", sa.Text, nullable=False, unique=True),
        sa.Column("subject_kind", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "opaque_ref <> '' AND opaque_ref = btrim(opaque_ref)",
            name="customer_ref_valid",
        ),
        sa.CheckConstraint(
            "subject_kind IN ('registered', 'anonymous')", name="customer_kind_valid",
        ),
        sa.CheckConstraint(
            "isfinite(created_at) AND isfinite(last_activity_at) "
            "AND last_activity_at >= created_at", name="customer_activity_valid",
        ),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("opaque_ref", sa.Text, nullable=False, unique=True),
        sa.Column("customer_id", sa.BigInteger, sa.ForeignKey("customers.id")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "opaque_ref <> '' AND opaque_ref = btrim(opaque_ref)",
            name="session_ref_valid",
        ),
        sa.CheckConstraint(
            "isfinite(started_at) AND isfinite(last_activity_at) "
            "AND last_activity_at >= started_at", name="session_activity_valid",
        ),
    )


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("customers")
