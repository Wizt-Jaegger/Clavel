"""Inventory observations with database-enforced ordering."""

from alembic import op
import sqlalchemy as sa


revision = "0003_inventory_schema"
down_revision = "0002_catalog_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory",
        sa.Column("sku_id", sa.BigInteger, sa.ForeignKey("skus.id"), primary_key=True),
        sa.Column("sellable_stock", sa.BigInteger),
        sa.Column("source_version", sa.BigInteger, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sellable_stock >= 0", name="inventory_stock_nonnegative"),
        sa.CheckConstraint("source_version >= 0", name="inventory_version_nonnegative"),
        sa.CheckConstraint("isfinite(observed_at)", name="inventory_observation_finite"),
    )
    op.execute("""
        CREATE FUNCTION enforce_inventory_observation_order() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.sku_id IS DISTINCT FROM OLD.sku_id THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    CONSTRAINT = 'inventory_sku_immutable',
                    MESSAGE = 'Inventory observation SKU cannot change';
            END IF;
            IF NEW.source_version <= OLD.source_version
               OR NEW.observed_at < OLD.observed_at THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    CONSTRAINT = 'inventory_update_fresh',
                    MESSAGE = 'Inventory update must advance version without regressing time';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER inventory_observation_order
        BEFORE UPDATE ON inventory
        FOR EACH ROW EXECUTE FUNCTION enforce_inventory_observation_order()
    """)


def downgrade() -> None:
    op.drop_table("inventory")
    op.execute("DROP FUNCTION enforce_inventory_observation_order()")
