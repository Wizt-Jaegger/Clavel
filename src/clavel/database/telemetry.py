"""Recommendation generation and explicit observations, with opaque linkage.

A generated result is not an exposure. Only an explicit exposure event records
that observation; click, add_to_cart, purchase and return are separate event types.
Requests may return no results, and results may have no observed events.

Callers supply stable request/event UUIDs for retry deduplication. A request is
attributed only to an explicit anonymous or registered customer record. Its
optional session must already belong to that customer; unresolved sessions are
not inferred or promoted. All child subject keys are required so NULL cannot
bypass composite foreign keys. No payload stores personal data or demographics.

Times are explicit timezone-aware source/receipt instants, never inferred from
each other. Clock ordering and attribution windows need a separate policy.
This schema records observations; it does not verify stock or compatibility.
"""

import sqlalchemy as sa

from clavel.database.sales import metadata


recommendation_requests = sa.Table(
    "recommendation_requests", metadata,
    sa.Column("request_id", sa.Uuid, primary_key=True),
    sa.Column("customer_id", sa.BigInteger, sa.ForeignKey("customers.id"), nullable=False),
    sa.Column("session_id", sa.BigInteger),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("request_id", "customer_id", name="rec_request_subject_unique"),
    sa.ForeignKeyConstraint(
        ["session_id", "customer_id"], ["sessions.id", "sessions.customer_id"],
        name="rec_request_session_subject_fk",
    ),
    sa.CheckConstraint("isfinite(requested_at)", name="rec_request_time_finite"),
    sa.Index("rec_request_subject_time_idx", "customer_id", "requested_at"),
)

recommendation_results = sa.Table(
    "recommendation_results", metadata,
    sa.Column("request_id", sa.Uuid, primary_key=True),
    sa.Column("sku_id", sa.BigInteger, sa.ForeignKey("skus.id"), primary_key=True),
    sa.Column("customer_id", sa.BigInteger, nullable=False),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["request_id", "customer_id"],
        ["recommendation_requests.request_id", "recommendation_requests.customer_id"],
        name="rec_result_request_subject_fk",
    ),
    sa.UniqueConstraint("request_id", "position", name="rec_result_position_unique"),
    sa.UniqueConstraint(
        "request_id", "sku_id", "customer_id", name="rec_result_subject_unique",
    ),
    sa.CheckConstraint("position > 0", name="rec_result_position_positive"),
    sa.CheckConstraint("isfinite(generated_at)", name="rec_result_time_finite"),
)

recommendation_events = sa.Table(
    "recommendation_events", metadata,
    sa.Column("event_id", sa.Uuid, primary_key=True),
    sa.Column("request_id", sa.Uuid, nullable=False),
    sa.Column("sku_id", sa.BigInteger, nullable=False),
    sa.Column("customer_id", sa.BigInteger, nullable=False),
    sa.Column("event_type", sa.Text, nullable=False),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["request_id", "sku_id", "customer_id"],
        ["recommendation_results.request_id", "recommendation_results.sku_id",
         "recommendation_results.customer_id"],
        name="rec_event_result_subject_fk",
    ),
    sa.CheckConstraint(
        "event_type IN ('exposure', 'click', 'add_to_cart', 'purchase', 'return')",
        name="rec_event_type_valid",
    ),
    sa.CheckConstraint(
        "isfinite(occurred_at) AND isfinite(recorded_at)", name="rec_event_times_finite",
    ),
    sa.Index("rec_event_result_type_idx", "request_id", "sku_id", "event_type"),
)
