"""Synthetic P0019 fixtures; mechanics only, no vendor or live acceptance evidence."""

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, localcontext

import pytest

from clavel.data.import_validation import ReturnRowV1, SaleRowV1, validate_rows


def sale(**changes):
    """Hand-authored synthetic fixture, not derived from a provider dataset."""
    return {
        "contract_version": "v1", "record_type": "sale",
        "source_system": "synthetic-pos", "source_order_id": "synthetic-order",
        "source_line_id": "synthetic-line", "sku": "SYNTHETIC-SKU",
        "sold_at": "2026-01-01T06:00:00-06:00", "currency": " mxn ",
        "quantity": "2.123456", "unit_price": "12.3456", **changes,
    }


def returned(**changes):
    return {
        "contract_version": "v1", "record_type": "return",
        "source_system": "synthetic-pos", "source_order_id": "synthetic-order",
        "source_line_id": "synthetic-return-line", "source_return_id": "synthetic-return",
        "sale_source_line_id": "synthetic-line", "quantity": "1",
        "returned_at": "2026-01-02T12:00:00Z", **changes,
    }


def test_normalization_is_exact_utc_and_nonmutating():
    raw = sale(unit_cost="0", customer_ref="synthetic-customer")
    original = deepcopy(raw)
    result = validate_rows([raw, returned()])
    assert result.valid and result.diagnostics == ()
    value, refund = (row.value for row in result.rows)
    assert isinstance(value, SaleRowV1) and isinstance(refund, ReturnRowV1)
    assert value.sold_at == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    assert value.sold_at.tzinfo is timezone.utc
    assert value.currency == "MXN" and value.sku == "SYNTHETIC-SKU"
    assert value.quantity == Decimal("2.123456")
    assert value.unit_price == Decimal("12.3456") and value.unit_cost == Decimal(0)
    assert value.customer_ref == "synthetic-customer"
    assert refund.returned_at.tzinfo is timezone.utc and refund.quantity == Decimal(1)
    assert raw == original


@pytest.mark.parametrize("cost", [None, "absent", "0", 0, Decimal("0"), "1.2345"])
def test_unknown_cost_is_preserved_and_distinct_from_zero(cost):
    raw = sale() if cost == "absent" else sale(unit_cost=cost)
    result = validate_rows([raw])
    assert result.valid
    if cost in (None, "absent"):
        assert result.rows[0].value.unit_cost is None
        assert [(d.field, d.code, d.severity) for d in result.diagnostics] == [
            ("unit_cost", "unknown_cost", "warning"),
        ]
    else:
        assert result.rows[0].value.unit_cost == Decimal(str(cost))
        assert result.diagnostics == ()
    assert result.rows[0].value.customer_ref is None


@pytest.mark.parametrize("field,build", [("sold_at", sale), ("returned_at", returned)])
@pytest.mark.parametrize("bad", [
    "not-a-date", "2026-02-30T12:00:00Z", "2026-01-01", "2026-01-01T12:00:00",
    "2026-01-01 12:00:00Z", "2026-01-01T12:00:00+25:00", "2026-01-01T12:00:00+01:60",
    "2026-01-01T12:00:00-00:00", "2026-01-01T12:00:60Z",
    "2026-01-01T12:00:00.1234567Z", "0001-01-01T00:00:00+01:00",
    "9999-12-31T23:59:59-01:00", datetime(2026, 1, 1), 0, True, None,
])
def test_malformed_or_unknown_timestamps_fail_without_rows(field, build, bad):
    result = validate_rows([build(**{field: bad})])
    assert not result.valid and result.rows == ()
    assert [(d.row_number, d.field, d.code) for d in result.diagnostics] == [
        (1, field, "invalid_value"),
    ]


@pytest.mark.parametrize("value", ["2026-01-01T12:00:00Z", "2026-01-01T18:00:00+06:00",
                                   datetime(2026, 1, 1, 12, tzinfo=timezone.utc)])
def test_equivalent_timestamp_inputs_normalize_to_one_instant(value):
    assert validate_rows([sale(sold_at=value)]).rows[0].value.sold_at == datetime(
        2026, 1, 1, 12, tzinfo=timezone.utc,
    )


@pytest.mark.parametrize("bad", [None, "", "MX", "MXNN", "12A", "$MX", "ＭＸＮ", 123, True])
def test_malformed_currency_fails(bad):
    result = validate_rows([sale(currency=bad)])
    assert not result.valid and result.rows == ()
    assert result.diagnostics[0].field == "currency"


@pytest.mark.parametrize("build,field", [
    (sale, "source_system"), (sale, "source_order_id"), (sale, "source_line_id"),
    (sale, "sku"), (sale, "customer_ref"), (returned, "source_return_id"),
    (returned, "sale_source_line_id"),
])
@pytest.mark.parametrize("bad", ["", "  ", " padded", "padded ", "bad\x00id", "bad\nid",
                                 "bad\u200bid", 123, True, []])
def test_invalid_identifiers_are_not_coerced_or_repaired(build, field, bad):
    result = validate_rows([build(**{field: bad})])
    assert not result.valid and result.rows == ()
    assert result.diagnostics[0].field == field


@pytest.mark.parametrize("field", ["quantity", "unit_price", "unit_cost"])
@pytest.mark.parametrize("bad", [True, False, 1.2, float("nan"), "NaN", Decimal("NaN"),
                                 Decimal("sNaN"), Decimal("Infinity"), "Infinity", "-1",
                                 "1,234", "1e2", "", [], {}])
def test_invalid_numeric_values_fail_without_rounding_or_float_conversion(field, bad):
    result = validate_rows([sale(**{field: bad})])
    assert not result.valid and result.rows == ()
    assert result.diagnostics[0].field == field


@pytest.mark.parametrize("field,bad", [
    ("quantity", "0"), ("quantity", None), ("quantity", "0.0000001"),
    ("quantity", "1000000000000"), ("unit_price", "0.00001"), ("unit_price", None),
    ("unit_price", "1000000000000000"), ("unit_cost", "1000000000000000"),
    ("unit_cost", "0.00001"),
])
def test_database_numeric_bounds_and_precision_are_respected(field, bad):
    result = validate_rows([sale(**{field: bad})])
    assert not result.valid and result.rows == ()


def test_boundary_values_and_insignificant_zeros_do_not_depend_on_decimal_context():
    with localcontext() as context:
        context.prec = 6
        result = validate_rows([sale(
            quantity="999999999999.9999990", unit_price="999999999999999.99990",
            unit_cost=Decimal("0.000000000000"),
        )])
    assert result.valid and not result.diagnostics
    assert result.rows[0].value.quantity == Decimal("999999999999.999999")
    assert result.rows[0].value.unit_price == Decimal("999999999999999.9999")


def test_row_diagnostics_collect_errors_preserve_positions_and_redact_input():
    raw = sale(currency="synthetic-sensitive-value", sold_at="synthetic-sensitive-value")
    raw["synthetic-private-field"] = "synthetic-sensitive-value"
    result = validate_rows([sale(), raw, returned(), None, [], "synthetic-sensitive-value"])
    assert not result.valid
    assert [row.row_number for row in result.rows] == [1, 3]
    errors = {(d.row_number, d.field, d.code) for d in result.diagnostics if d.severity == "error"}
    assert errors == {(2, "currency", "invalid_value"), (2, "sold_at", "invalid_value"),
                      (2, "$row", "unexpected_field"), (4, "$row", "invalid_row"),
                      (5, "$row", "invalid_row"), (6, "$row", "invalid_row")}
    assert "synthetic-sensitive-value" not in repr(result)
    assert "synthetic-private-field" not in repr(result)


@pytest.mark.parametrize("field", ["contract_version", "record_type", "sku", "quantity",
                                   "source_system", "source_order_id", "source_line_id",
                                   "sold_at", "currency", "unit_price"])
def test_required_sale_fields_are_not_inferred(field):
    raw = sale()
    del raw[field]
    result = validate_rows([raw])
    assert not result.valid and result.rows == ()
    assert result.diagnostics[0].field == field


@pytest.mark.parametrize("changes,field,code", [
    ({"contract_version": "v2"}, "contract_version", "unsupported_version"),
    ({"contract_version": 1}, "contract_version", "unsupported_version"),
    ({"record_type": "vendor-sale"}, "record_type", "invalid_record_type"),
    ({"record_type": []}, "record_type", "invalid_record_type"),
    ({"extra": 1}, "$row", "unexpected_field"),
])
def test_unrecognized_versions_kinds_and_fields_fail_closed(changes, field, code):
    result = validate_rows([sale(**changes)])
    assert not result.valid and result.rows == ()
    assert (result.diagnostics[0].field, result.diagnostics[0].code) == (field, code)


@pytest.mark.parametrize("field", ["source_order_id", "source_return_id", "source_line_id",
                                   "sale_source_line_id", "returned_at", "quantity"])
def test_return_link_fields_are_required_without_inventing_a_sale(field):
    raw = returned()
    del raw[field]
    result = validate_rows([raw])
    assert not result.valid and result.rows == ()
    assert result.diagnostics[0].field == field


@pytest.mark.parametrize("field", ["currency", "unit_cost", "sku", "sellable_stock", "eligible"])
def test_return_cannot_override_currency_or_add_unrelated_claims(field):
    result = validate_rows([returned(**{field: "synthetic"})])
    assert not result.valid and result.rows == ()
    assert result.diagnostics[0].code == "unexpected_field"


def test_empty_generator_and_repeated_validation_are_deterministic():
    empty = validate_rows(iter(()))
    assert empty.valid and empty.rows == () and empty.diagnostics == ()
    records = [sale(), returned(), sale(currency="invalid")]
    assert validate_rows(iter(records)) == validate_rows(records)
