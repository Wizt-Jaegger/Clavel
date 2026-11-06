"""Minimal opaque subjects and sessions; references must not contain personal data.

The customers registry includes both anonymous and registered subjects. Kind is
explicit source information, never inferred from a reference. An unresolved
session may have no customer link. TIMESTAMPTZ stores activity as UTC instants;
callers must supply timezone-aware times and request UTC when displaying them.

Anonymous-to-known linkage, merges and historical attribution require a separate
reviewed policy (docs/P0010_CUSTOMER_SESSION_SCHEMA.md); no automatic linking or
promotion is implemented here.
"""

import sqlalchemy as sa

from clavel.database.inventory import metadata


customers = sa.Table(
    "customers", metadata,
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

sessions = sa.Table(
    "sessions", metadata,
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
