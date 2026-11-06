"""HTTP + disposable PostgreSQL; all stock, credentials and policy are synthetic.

This proves database/API mechanics, not production authentication or Q07's SLA.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from clavel.api.app import create_app
from clavel.api.inventory import InventoryRuntime
from clavel.core.settings import Settings
from clavel.database.repositories import CatalogRepository, StockObservation, StockRepository
from clavel.intelligence.recommendations.inventory import FreshnessPolicy
from tests.integration.test_migrations import run_alembic
from tests.test_openapi_contract import validator


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
POLICY = FreshnessPolicy(timedelta(minutes=5))  # Synthetic; not a provider decision.
HEADERS = {"Authorization": "Bearer synthetic", "X-Request-ID": "synthetic-inventory"}


@pytest.fixture
def client(migration_database_url):
    run_alembic(migration_database_url, "upgrade", "head")
    app = create_app(
        settings=Settings(_env_file=None, app_env="test", database_url=migration_database_url),
        inventory_runtime=InventoryRuntime(
            verify_bearer=lambda token: frozenset({"viewer"}) if token == "synthetic" else None,
            freshness_policy=POLICY, clock=lambda: NOW,
        ),
    )
    with TestClient(app, headers=HEADERS) as result:
        yield result


def seed(client, observations):
    ids = []
    with client.app.state.database.session() as connection:
        catalog, stock = CatalogRepository(connection), StockRepository(connection)
        for index, observation in enumerate(observations):
            sku = catalog.upsert_sku(f"SYNTHETIC-{index}", f"Synthetic item {index}")
            ids.append(str(sku.id))
            if observation is not None:
                quantity, observed_at = observation
                stock.upsert(StockObservation(sku.id, quantity, index, observed_at))
    return ids


def inventory_response(response):
    assert response.status_code == 200, response.text
    value = response.json()
    validator({"$ref": "#/components/schemas/InventoryPage"}).validate(value)
    assert response.headers["X-Request-ID"] == "synthetic-inventory"
    return value


def test_stale_unknown_zero_and_fresh_examples_match_existing_contract(client):
    observations = [
        None, (None, NOW), (0, NOW), (4, NOW),
        (4, NOW - POLICY.max_age),
        (4, NOW - POLICY.max_age - timedelta(microseconds=1)),
        (4, NOW + timedelta(microseconds=1)),
        (None, NOW - timedelta(days=1)), (0, NOW - timedelta(days=1)),
    ]
    ids = seed(client, observations)
    value = inventory_response(client.get("/v1/inventory"))
    assert value["page"] == {"limit": 20, "next_cursor": None}
    assert [item["item_id"] for item in value["items"]] == ids
    assert [item["stock"] for item in value["items"]] == [
        "unknown", "unknown", "out_of_stock", "in_stock", "in_stock", "stale",
        "unknown", "unknown", "out_of_stock",
    ]
    assert value["items"][0] == {
        "item_id": ids[0], "stock": "unknown", "observed_at": None, "source_version": None,
    }
    for index, item in enumerate(value["items"][1:], start=1):
        assert datetime.fromisoformat(item["observed_at"]) == observations[index][1]
        assert item["source_version"] == str(index)


def test_missing_policy_preserves_evidence_without_verifying_positive_stock(client):
    seed(client, [(3, NOW), (0, NOW), (None, NOW)])
    client.app.state.inventory_runtime = InventoryRuntime(
        verify_bearer=lambda _: frozenset({"viewer"}), clock=lambda: NOW,
    )
    items = inventory_response(client.get("/v1/inventory"))["items"]
    assert [item["stock"] for item in items] == ["unknown", "out_of_stock", "unknown"]
    assert items[0]["source_version"] == "0"
    assert datetime.fromisoformat(items[0]["observed_at"]) == NOW


def test_empty_catalog_and_snapshot_bound_pagination(client):
    assert inventory_response(client.get("/v1/inventory")) == {
        "items": [], "page": {"limit": 20, "next_cursor": None},
    }
    ids = seed(client, [(1, NOW), None, (1, NOW)])
    first = inventory_response(client.get("/v1/inventory?limit=2"))
    assert [item["item_id"] for item in first["items"]] == ids[:2]
    cursor = first["page"]["next_cursor"]
    assert isinstance(cursor, str) and 1 <= len(cursor) <= 128
    second = inventory_response(client.get("/v1/inventory", params={"limit": 2, "cursor": cursor}))
    assert [item["item_id"] for item in second["items"]] == ids[2:]
    assert second["items"][0]["stock"] == "in_stock"
    assert second["page"]["next_cursor"] is None


@pytest.mark.parametrize("change", ["stock", "catalog", "in_flight"])
def test_cursor_rejects_changed_snapshot_instead_of_reading_new_rows(client, change):
    ids = seed(client, [(1, NOW), (1, NOW)])
    with client.app.state.database.session() as connection:
        if change == "in_flight":
            # An uncommitted writer excluded by the first snapshot later commits.
            StockRepository(connection).upsert(StockObservation(int(ids[1]), 0, 100, NOW))
        first = inventory_response(client.get("/v1/inventory?limit=1"))
        if change == "stock":
            StockRepository(connection).upsert(StockObservation(int(ids[1]), 0, 100, NOW))
        if change == "catalog":
            CatalogRepository(connection).upsert_sku("SYNTHETIC-NEW", "Synthetic new item")
    response = client.get("/v1/inventory", params={
        "limit": 1, "cursor": first["page"]["next_cursor"],
    })
    assert response.status_code == 400
    validator({"$ref": "#/components/schemas/Error"}).validate(response.json())
    assert response.json()["error"]["code"] == "bad_request"
    assert "items" not in response.json()


def test_continuation_freezes_freshness_evaluation_time(client):
    seed(client, [(1, NOW - POLICY.max_age), (1, NOW - POLICY.max_age)])
    first = inventory_response(client.get("/v1/inventory?limit=1"))
    client.app.state.inventory_runtime = InventoryRuntime(
        verify_bearer=lambda _: frozenset({"viewer"}), freshness_policy=POLICY,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    second = inventory_response(client.get("/v1/inventory", params={
        "limit": 1, "cursor": first["page"]["next_cursor"],
    }))
    assert first["items"][0]["stock"] == second["items"][0]["stock"] == "in_stock"


def test_page_uses_read_only_repeatable_read_and_leaves_stock_unchanged(client, monkeypatch):
    ids = seed(client, [(7, NOW)])
    original_get = StockRepository.get
    modes = []

    def checked_get(repository, sku_id):
        modes.append((
            repository.connection.execute("SHOW transaction_isolation").fetchone()[0],
            repository.connection.execute("SHOW transaction_read_only").fetchone()[0],
        ))
        return original_get(repository, sku_id)

    monkeypatch.setattr(StockRepository, "get", checked_get)
    inventory_response(client.get("/v1/inventory"))
    assert modes == [("repeatable read", "on")]
    with client.app.state.database.session() as connection:
        assert original_get(StockRepository(connection), int(ids[0])) == StockObservation(
            int(ids[0]), 7, 0, NOW,
        )
