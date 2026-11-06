"""Subject-bound recommendation generation and explicit telemetry events."""

from alembic import op
import sqlalchemy as sa


revision = "0006_recommendation_telemetry"
down_revision = "0005_sales_return_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("session_id_customer_unique", "sessions", ["id", "customer_id"])
    op.create_table(
        "recommendation_requests",
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
    )
    op.create_index(
        "rec_request_subject_time_idx", "recommendation_requests", ["customer_id", "requested_at"],
    )
    op.create_table(
        "recommendation_results",
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
    op.create_table(
        "recommendation_events",
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
            "event_type IN ('exposure', 'click', 'add_to_cart', 'purchase')",
            name="rec_event_type_valid",
        ),
        sa.CheckConstraint(
            "isfinite(occurred_at) AND isfinite(recorded_at)", name="rec_event_times_finite",
        ),
    )
    op.create_index(
        "rec_event_result_type_idx", "recommendation_events", ["request_id", "sku_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_table("recommendation_events")
    op.drop_table("recommendation_results")
    op.drop_table("recommendation_requests")
    op.drop_constraint("session_id_customer_unique", "sessions", type_="unique")
