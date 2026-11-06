"""Seeded, entirely invented P0021 fixtures; no live representativeness claims."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from random import Random


SOURCE = "synthetic-p0021"
AS_OF = datetime(2026, 1, 31, tzinfo=timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def generate_fixtures(*, seed: int = 21, skus: int = 12, subjects: int = 8,
                      sales: int = 24) -> dict:
    """Return a fresh bundle with provenance covering every nested record.

    Counts reserve one unsold SKU and two subjects without purchases (one of
    each kind). Inventory includes current positive, zero, unknown, stale and
    absent observations relative to the fixed synthetic as_of, never wall time.
    Sale/return rows conform to canonical v1 without adding forbidden fields.
    """
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    for name, value, minimum in (("skus", skus, 5), ("subjects", subjects, 4),
                                 ("sales", sales, 3)):
        if type(value) is not int or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}")
    rng = Random(seed)
    categories = [{"code": f"synthetic-category-{i}", "name": f"Synthetic category {i}"}
                  for i in range(2)]
    catalog = [{"sku": f"synthetic-sku-{i:04d}", "name": f"Synthetic item {i}",
                "category_code": categories[i % 2]["code"],
                "attributes": [{"name": "compatibility", "value_kind": "unknown",
                                "text_value": None, "number_value": None,
                                "boolean_value": None, "unit": None}]}
               for i in range(skus)]
    inventory = []
    for i, sku in enumerate(catalog[:-1]):
        stock = 0 if i == 1 else None if i == 2 else rng.randint(1, 50)
        inventory.append({"sku": sku["sku"], "sellable_stock": stock,
                          "source_version": 1,
                          "observed_at": _timestamp(AS_OF - timedelta(
                              days=30 if i == 3 else 0))})
    created = AS_OF - timedelta(days=30)
    customers = [{"opaque_ref": f"synthetic-subject-{i:04d}",
                  "subject_kind": "registered" if i % 2 == 0 else "anonymous",
                  "created_at": _timestamp(created),
                  "last_activity_at": _timestamp(AS_OF)}
                 for i in range(subjects)]
    # Reserve one subject of each kind, including for odd subject counts.
    cold_subjects = customers[-2:]
    active_subjects = customers[:-2]
    sale_rows = []
    for i in range(sales):
        # First three guarantee registered, anonymous and unresolved subjects.
        subject = active_subjects[i % len(active_subjects)] if i % 3 != 2 else None
        sale_rows.append({
            "contract_version": "v1", "record_type": "sale", "source_system": SOURCE,
            "source_order_id": f"synthetic-order-{i:06d}",
            "source_line_id": "synthetic-sale-line-0",
            "sku": rng.choice(catalog[:-1])["sku"],
            "sold_at": _timestamp(created + timedelta(days=1, seconds=i % 86400)),
            "customer_ref": subject["opaque_ref"] if subject else None,
            "currency": "MXN", "quantity": "3" if i == 0 else str(rng.randint(1, 5)),
            "unit_price": f"{rng.randint(10, 200)}.{rng.randint(0, 99):02d}",
            "unit_cost": None if i % 3 == 0 else "0" if i % 3 == 1 else "5.00",
        })
    return_rows = []
    # Two partial returns exercise cumulative limits against the same sale.
    for i in [0, 0, *range(5, sales, 5)]:
        sale = sale_rows[i]
        return_rows.append({
            "contract_version": "v1", "record_type": "return", "source_system": SOURCE,
            "source_order_id": sale["source_order_id"],
            "source_return_id": f"synthetic-return-{len(return_rows):06d}",
            "source_line_id": "synthetic-return-line-0",
            "sale_source_line_id": sale["source_line_id"], "quantity": "1",
            "returned_at": _timestamp(created + timedelta(days=3, seconds=i % 86400)),
        })
    return {
        "fixture_version": "v1",
        "provenance": {
            "synthetic": True, "scope": "all nested records",
            "generator": "clavel.data.synthetic_fixtures:v1", "seed": seed,
            "parameters": {"skus": skus, "subjects": subjects, "sales": sales},
            "source": "invented; no provider or personal data",
            "evidence": "mechanics only; not live or representative",
        },
        "as_of": _timestamp(AS_OF), "categories": categories, "catalog": catalog,
        "inventory": inventory, "subjects": customers,
        "sales": sale_rows, "returns": return_rows,
        "cold_start": {
            "skus_without_sales": [catalog[-1]["sku"]],
            "subjects_without_sales": [row["opaque_ref"] for row in cold_subjects],
        },
    }


def serialize_fixtures(bundle: dict) -> str:
    """Canonical UTF-8 JSON text with a final newline, independent of wall time."""
    return json.dumps(bundle, ensure_ascii=True, sort_keys=True, indent=2,
                      allow_nan=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic P0021 fixtures only")
    parser.add_argument("--seed", type=int, default=21)
    parser.add_argument("--skus", type=int, default=12)
    parser.add_argument("--subjects", type=int, default=8)
    parser.add_argument("--sales", type=int, default=24)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bundle = generate_fixtures(seed=args.seed, skus=args.skus,
                                   subjects=args.subjects, sales=args.sales)
    except ValueError as error:
        parser.error(str(error))
    try:
        # Exclusive creation keeps existing fixture evidence intact.
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialize_fixtures(bundle))
    except OSError:
        parser.exit(1, "fixture output unavailable or already exists\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
