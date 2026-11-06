"""Current stock observations, with no default or implied eligibility.

One authoritative stream per SKU uses nonnegative, strictly increasing integer
source versions. This is a local storage contract, not a vendor protocol. A NULL
sellable_stock or absent row means unknown; zero means observed out of stock.
observed_at is an explicit timezone-aware source observation, never receipt time.
The migration rejects version replays/regressions and observation time regressions
atomically, including direct SQL and upserts. Higher versions may share a timestamp.
Age-based freshness and eligibility remain the caller's responsibility: persisting
an observation does not verify that it is still current.
"""

import sqlalchemy as sa

from clavel.database.catalog import metadata


inventory = sa.Table(
    "inventory", metadata,
    sa.Column("sku_id", sa.BigInteger, sa.ForeignKey("skus.id"), primary_key=True),
    sa.Column("sellable_stock", sa.BigInteger),
    sa.Column("source_version", sa.BigInteger, nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("sellable_stock >= 0", name="inventory_stock_nonnegative"),
    sa.CheckConstraint("source_version >= 0", name="inventory_version_nonnegative"),
    sa.CheckConstraint("isfinite(observed_at)", name="inventory_observation_finite"),
)
