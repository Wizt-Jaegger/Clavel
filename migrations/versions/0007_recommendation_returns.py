"""Allow explicit recommendation return telemetry without inferring purchases."""

from alembic import op


revision = "0007_recommendation_returns"
down_revision = "0006_recommendation_telemetry"
branch_labels = None
depends_on = None


def _replace_event_types(types: str) -> None:
    op.drop_constraint("rec_event_type_valid", "recommendation_events", type_="check")
    op.create_check_constraint(
        "rec_event_type_valid", "recommendation_events", f"event_type IN ({types})",
    )


def upgrade() -> None:
    _replace_event_types("'exposure', 'click', 'add_to_cart', 'purchase', 'return'")


def downgrade() -> None:
    # Existing returns intentionally block downgrade rather than lose evidence.
    _replace_event_types("'exposure', 'click', 'add_to_cart', 'purchase'")
