"""Add a covering index for historical station aggregations."""

from alembic import op


revision = "0003_history_covering_index"
down_revision = "0002_historical_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE INDEX idx_observations_station_history_covering
        ON observations(
            provider_id, station_id, observed_at,
            mechanical_bikes, electric_bikes, free_docks, capacity
        )"""
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_observations_station_history_covering")
