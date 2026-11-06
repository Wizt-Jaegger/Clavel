"""P0021 synthetic-only evidence: invented records, no live/provider acceptance."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import random
import subprocess
import sys

import pytest

from clavel.data.import_validation import validate_rows
from clavel.data.synthetic_fixtures import generate_fixtures, serialize_fixtures


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/generate_fixtures.py"


def test_seed_reproducibility_and_random_state_isolation():
    before = random.getstate()
    first = serialize_fixtures(generate_fixtures(seed=21))
    assert random.getstate() == before
    assert first == serialize_fixtures(generate_fixtures(seed=21))
    other = generate_fixtures(seed=22)
    original = json.loads(first)
    assert original["sales"] != other["sales"]
    assert original["inventory"] != other["inventory"]
    original["catalog"][0]["name"] = "changed synthetic copy"
    assert first == serialize_fixtures(generate_fixtures(seed=21))


@pytest.mark.parametrize("seed,counts", [
    (0, {}), (21, {"skus": 5, "subjects": 4, "sales": 3}),
    (-7, {"skus": 7, "subjects": 5, "sales": 31}),
    (12345, {"skus": 20, "subjects": 20, "sales": 60}),
])
def test_bundle_references_canonical_contract_and_return_limits(seed, counts):
    bundle = generate_fixtures(seed=seed, **counts)
    assert bundle["fixture_version"] == "v1"
    provenance = bundle["provenance"]
    assert provenance["synthetic"] is True
    assert provenance["scope"] == "all nested records"
    assert provenance["seed"] == seed
    assert provenance["source"] == "invented; no provider or personal data"
    assert "not live or representative" in provenance["evidence"]
    categories = {row["code"] for row in bundle["categories"]}
    catalog = {row["sku"]: row for row in bundle["catalog"]}
    subjects = {row["opaque_ref"]: row for row in bundle["subjects"]}
    assert len(categories) == len(bundle["categories"])
    assert len(catalog) == len(bundle["catalog"]) == counts.get("skus", 12)
    assert len(subjects) == len(bundle["subjects"]) == counts.get("subjects", 8)
    assert len(bundle["sales"]) == counts.get("sales", 24)
    assert all(ref.startswith("synthetic-") for ref in [*categories, *catalog, *subjects])
    assert all(row["category_code"] in categories for row in catalog.values())
    for subject in subjects.values():
        assert subject["subject_kind"] in {"anonymous", "registered"}
        assert datetime.fromisoformat(subject["created_at"]) <= datetime.fromisoformat(
            subject["last_activity_at"])
    inventory_keys = [row["sku"] for row in bundle["inventory"]]
    assert len(set(inventory_keys)) == len(inventory_keys)
    assert set(inventory_keys) <= catalog.keys()
    sold = {}
    purchased_skus, purchasing_subjects = set(), set()
    for sale in bundle["sales"]:
        key = (sale["source_system"], sale["source_order_id"], sale["source_line_id"])
        assert key not in sold
        sold[key] = sale
        assert sale["sku"] in catalog
        assert sale["customer_ref"] is None or sale["customer_ref"] in subjects
        purchased_skus.add(sale["sku"])
        if sale["customer_ref"] is not None:
            purchasing_subjects.add(sale["customer_ref"])
            subject = subjects[sale["customer_ref"]]
            assert datetime.fromisoformat(subject["created_at"]) <= datetime.fromisoformat(
                sale["sold_at"]) <= datetime.fromisoformat(subject["last_activity_at"])
    returned = defaultdict(Decimal)
    return_keys = set()
    for row in bundle["returns"]:
        key = (row["source_system"], row["source_return_id"], row["source_line_id"])
        assert key not in return_keys
        return_keys.add(key)
        sale_key = (row["source_system"], row["source_order_id"], row["sale_source_line_id"])
        sale = sold[sale_key]
        assert datetime.fromisoformat(row["returned_at"]) >= datetime.fromisoformat(sale["sold_at"])
        returned[sale_key] += Decimal(row["quantity"])
        assert returned[sale_key] <= Decimal(sale["quantity"])
    assert any(quantity == Decimal(2) for quantity in returned.values())
    rows = bundle["sales"] + bundle["returns"]
    assert all(row["source_system"] == "synthetic-p0021" for row in rows)
    result = validate_rows(rows)
    assert result.valid and len(result.rows) == len(rows)
    assert all(d.code == "unknown_cost" and d.severity == "warning" for d in result.diagnostics)
    assert {row["unit_cost"] for row in bundle["sales"]} >= {None, "0", "5.00"}
    assert any(row["customer_ref"] is None for row in bundle["sales"])
    assert {subjects[ref]["subject_kind"] for ref in purchasing_subjects} == {
        "anonymous", "registered"}
    cold = bundle["cold_start"]
    assert set(cold["skus_without_sales"]) <= catalog.keys() - purchased_skus
    assert cold["skus_without_sales"]
    assert set(cold["subjects_without_sales"]) <= subjects.keys() - purchasing_subjects
    assert {subjects[ref]["subject_kind"] for ref in cold["subjects_without_sales"]} == {
        "anonymous", "registered"}


def test_unknown_and_stale_states_survive_serialization():
    bundle = json.loads(serialize_fixtures(generate_fixtures()))
    inventory = bundle["inventory"]
    as_of = datetime.fromisoformat(bundle["as_of"])
    assert any(row["sellable_stock"] is None for row in inventory)
    assert any(row["sellable_stock"] == 0 for row in inventory)
    assert any(row["sellable_stock"] > 0 and row["observed_at"] == bundle["as_of"]
               for row in inventory if row["sellable_stock"] is not None)
    assert any(as_of - datetime.fromisoformat(row["observed_at"]) == timedelta(days=30)
               and row["sellable_stock"] > 0 for row in inventory
               if row["sellable_stock"] is not None)
    assert {row["sku"] for row in bundle["catalog"]} - {row["sku"] for row in inventory}
    for row in bundle["catalog"]:
        attribute, = row["attributes"]
        assert attribute["name"] == "compatibility" and attribute["value_kind"] == "unknown"
        assert all(attribute[field] is None for field in ("text_value", "number_value", "boolean_value"))


@pytest.mark.parametrize("changes", [
    {"skus": 4}, {"subjects": 3}, {"sales": 2}, {"sales": -1},
    {"skus": True}, {"subjects": 4.5}, {"sales": "3"}, {"seed": True}, {"seed": "21"},
])
def test_invalid_generation_requests_fail(changes):
    with pytest.raises(ValueError):
        generate_fixtures(**changes)


def test_cli_bytes_match_across_processes_and_existing_evidence_is_preserved(tmp_path):
    outputs = [tmp_path / "synthetic-a.json", tmp_path / "synthetic-b.json"]
    for index, output in enumerate(outputs):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--seed", "21", "--output", str(output)],
            cwd=ROOT, env={**os.environ, "PYTHONHASHSEED": str(index)},
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
    expected = serialize_fixtures(generate_fixtures()).encode("utf-8")
    assert outputs[0].read_bytes() == outputs[1].read_bytes() == expected
    overwrite = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(outputs[0])],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert overwrite.returncode == 1
    assert "already exists" in overwrite.stderr
    assert outputs[0].read_bytes() == expected


def test_cli_invalid_counts_do_not_create_output(tmp_path):
    output = tmp_path / "synthetic-invalid.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--sales", "0", "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "sales must be an integer >= 3" in result.stderr
    assert not output.exists()
