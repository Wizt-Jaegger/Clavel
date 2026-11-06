"""Versioned fixture contracts, independent of vendor mapping and HTTP APIs.

Rows carry contract_version="v1" and record_type="sale" or "return". One sale
row describes one order line; repeated order headers must be checked by a future
order assembler. References are opaque, case-sensitive source tokens, never
personal data. SKU/customer resolution, replay checks, order completeness and
cumulative return limits belong to the resolver/repository transaction.

Only currency spelling, exact decimals and offset timestamps are normalized.
Currency syntax is three ASCII letters, not a claim of ISO registry membership
or conversion. Missing cost/customer stays unknown. Returns inherit currency
from their original sale. No stock, compatibility or eligibility is inferred.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError


def _reference(value: object) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(unicodedata.category(char).startswith("C") for char in value)):
        raise ValueError("invalid opaque identifier")
    return value


def _timestamp(value: object) -> datetime:
    if isinstance(value, str):
        # Require full ISO date/time, seconds and explicit offset; never infer TZ.
        if not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])", value,
        ):
            raise ValueError("invalid offset timestamp")
        # RFC3339 -00:00 means an unknown offset, not a verified UTC instant.
        if value.endswith("-00:00"):
            raise ValueError("unknown timezone offset")
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("invalid offset timestamp") from None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamp requires timezone")
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise ValueError("timestamp outside UTC range") from None


def _currency(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value.strip()):
        raise ValueError("currency requires three ASCII letters")
    return value.strip().upper()


def _number(value: object, *, places: int, ceiling: int, positive: bool) -> Decimal:
    if type(value) is int:
        value = Decimal(value)
    elif isinstance(value, str):
        if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value.strip()):
            raise ValueError("invalid exact decimal")
        try:
            value = Decimal(value.strip())
        except InvalidOperation:
            raise ValueError("invalid exact decimal") from None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("finite exact decimal required")
    if value < 0 or (positive and value == 0) or value >= ceiling:
        raise ValueError("decimal outside allowed range")
    _, digits, exponent = value.as_tuple()
    # Count insignificant zeros without rounding or depending on Decimal context.
    trailing_zeros = 0
    for digit in reversed(digits):
        if digit:
            break
        trailing_zeros += 1
    if value != 0 and exponent + trailing_zeros < -places:
        raise ValueError("excess decimal precision")
    return value


def _quantity(value: object) -> Decimal:
    return _number(value, places=6, ceiling=10**12, positive=True)


def _amount(value: object) -> Decimal:
    return _number(value, places=4, ceiling=10**15, positive=False)


Reference = Annotated[str, BeforeValidator(_reference)]
Timestamp = Annotated[datetime, BeforeValidator(_timestamp)]
Currency = Annotated[str, BeforeValidator(_currency)]
Quantity = Annotated[Decimal, BeforeValidator(_quantity)]
Amount = Annotated[Decimal, BeforeValidator(_amount)]


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    contract_version: Literal["v1"]
    source_system: Reference
    source_order_id: Reference
    source_line_id: Reference
    quantity: Quantity


class SaleRowV1(_Row):
    record_type: Literal["sale"]
    sku: Reference
    sold_at: Timestamp
    currency: Currency
    unit_price: Amount
    unit_cost: Amount | None = None
    customer_ref: Reference | None = None


class ReturnRowV1(_Row):
    record_type: Literal["return"]
    source_return_id: Reference
    sale_source_line_id: Reference
    returned_at: Timestamp


@dataclass(frozen=True)
class RowDiagnostic:
    """Safe positional diagnostics: never include values or unknown field names."""

    row_number: int
    field: str
    code: str
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True)
class ValidatedRow:
    row_number: int
    value: SaleRowV1 | ReturnRowV1


@dataclass(frozen=True)
class ImportValidation:
    rows: tuple[ValidatedRow, ...]
    diagnostics: tuple[RowDiagnostic, ...]

    @property
    def valid(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)


def validate_rows(rows: Iterable[object]) -> ImportValidation:
    """Validate every row in order, retaining 1-based positions across failures.

    Invalid rows produce no normalized record; a batch with errors is not ready
    for import. Valid rows remain available for fixture inspection only. This
    function never writes, logs input, resolves identifiers or deduplicates rows.
    """
    accepted = []
    diagnostics = []
    for number, raw in enumerate(rows, 1):
        if not isinstance(raw, dict):
            diagnostics.append(RowDiagnostic(number, "$row", "invalid_row"))
            continue
        if raw.get("contract_version") != "v1":
            diagnostics.append(RowDiagnostic(number, "contract_version", "unsupported_version"))
            continue
        kind = raw.get("record_type")
        if kind not in ("sale", "return"):
            diagnostics.append(RowDiagnostic(number, "record_type", "invalid_record_type"))
            continue
        contract = SaleRowV1 if kind == "sale" else ReturnRowV1
        try:
            value = contract.model_validate(raw)
        except ValidationError as error:
            for item in error.errors(include_input=False, include_context=False, include_url=False):
                field = item["loc"][0] if item["loc"] else "$row"
                if field not in contract.model_fields:
                    field = "$row"
                code = {"missing": "required", "extra_forbidden": "unexpected_field"}.get(
                    item["type"], "invalid_value",
                )
                diagnostics.append(RowDiagnostic(number, field, code))
            continue
        accepted.append(ValidatedRow(number, value))
        if isinstance(value, SaleRowV1) and value.unit_cost is None:
            diagnostics.append(RowDiagnostic(number, "unit_cost", "unknown_cost", "warning"))
    return ImportValidation(tuple(accepted), tuple(diagnostics))
