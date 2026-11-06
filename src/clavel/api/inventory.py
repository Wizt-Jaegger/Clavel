"""Inventory reads; deployment must supply approved authentication and freshness.

The verifier is a trusted in-process integration seam, never a token parser or
provider protocol. No verifier is installed by default. Continuation is allowed
only while the PostgreSQL snapshot is unchanged; changed/expired cursors fail 400.
"""

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, Field

from clavel.core.errors import ApplicationError, ErrorCode, ErrorResponse
from clavel.database.repositories import CatalogRepository, StockRepository
from clavel.intelligence.recommendations.inventory import (
    FreshnessPolicy,
    InventoryEligibility,
    inventory_eligibility,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class InventoryRuntime:
    # None returned by the verifier means invalid credentials, not no roles.
    verify_bearer: Callable[[str], frozenset[str] | None] | None = None
    freshness_policy: FreshnessPolicy | None = None
    clock: Callable[[], datetime] = utc_now


class InventoryItem(BaseModel):
    item_id: str = Field(min_length=1, max_length=128)
    stock: Literal["in_stock", "out_of_stock", "unknown", "stale"]
    observed_at: AwareDatetime | None
    source_version: str | None = Field(min_length=1, max_length=128)


class InventoryPageInfo(BaseModel):
    limit: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(min_length=1, max_length=128)


class InventoryPage(BaseModel):
    items: list[InventoryItem]
    page: InventoryPageInfo


class InventoryUnavailableResponse(BaseModel):
    state: Literal["unavailable"] = "unavailable"
    reason: Literal["dependency_unavailable"] = "dependency_unavailable"
    retryable: bool
    request_id: str


class InventoryUnavailable(Exception):
    def __init__(self, *, retryable: bool):
        self.retryable = retryable


bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


def require_inventory_reader(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    if credentials is None:
        raise HTTPException(401)
    runtime: InventoryRuntime = request.app.state.inventory_runtime
    if runtime.verify_bearer is None:
        raise InventoryUnavailable(retryable=False)
    try:
        roles = runtime.verify_bearer(credentials.credentials)
    except Exception:
        # Provider details and credentials never cross the HTTP boundary.
        raise InventoryUnavailable(retryable=True) from None
    if roles is None:
        raise HTTPException(401)
    if "viewer" not in roles:
        raise HTTPException(403)


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# Operational cursor lifetime only; unrelated to provider stock freshness.
CURSOR_TTL = timedelta(minutes=5)
CURSOR_BODY = struct.Struct("!BQqB16s8s")


def policy_digest(policy: FreshnessPolicy | None) -> bytes:
    return hashlib.sha256(str(policy.max_age if policy else None).encode()).digest()[:8]


@dataclass(frozen=True)
class InventoryCursor:
    after_id: int
    evaluated_at: datetime
    limit: int
    snapshot: bytes
    policy: bytes


class InventoryCursors:
    """Process-local signing key; restarts/other workers safely invalidate tokens.

    No stored snapshots or open transactions survive the HTTP request. Unrelated
    PostgreSQL writes can also invalidate continuation: clients restart on 400.
    """

    def __init__(self):
        self._key = secrets.token_bytes(32)

    def encode(self, cursor: InventoryCursor) -> str:
        micros = (cursor.evaluated_at - EPOCH) // timedelta(microseconds=1)
        body = CURSOR_BODY.pack(1, cursor.after_id, micros, cursor.limit,
                                cursor.snapshot, cursor.policy)
        tag = hmac.digest(self._key, b"inventory\0" + body, "sha256")[:16]
        return base64.urlsafe_b64encode(body + tag).decode().rstrip("=")

    def decode(self, token: str, *, now: datetime, limit: int,
               policy: FreshnessPolicy | None) -> InventoryCursor:
        try:
            raw = base64.b64decode(token + "=" * (-len(token) % 4),
                                   altchars=b"-_", validate=True)
            if (len(raw) != CURSOR_BODY.size + 16 or
                    base64.urlsafe_b64encode(raw).decode().rstrip("=") != token):
                raise ValueError("invalid encoding")
            body, tag = raw[:-16], raw[-16:]
            if not hmac.compare_digest(
                tag, hmac.digest(self._key, b"inventory\0" + body, "sha256")[:16],
            ):
                raise ValueError("invalid signature")
            version, after_id, micros, bound_limit, snapshot, bound_policy = CURSOR_BODY.unpack(body)
            evaluated_at = EPOCH + timedelta(microseconds=micros)
            if (version != 1 or not 0 < after_id <= 2**63 - 1 or
                    bound_limit != limit or bound_policy != policy_digest(policy) or
                    not timedelta(0) <= now - evaluated_at <= CURSOR_TTL):
                raise ValueError("invalid binding or expiration")
            return InventoryCursor(after_id, evaluated_at, limit, snapshot, bound_policy)
        except (ValueError, OverflowError, binascii.Error, struct.error):
            raise ApplicationError(ErrorCode.BAD_REQUEST) from None


router = APIRouter()


@router.get(
    "/v1/inventory",
    operation_id="v1_list_inventory",
    response_model=InventoryPage,
    dependencies=[Depends(require_inventory_reader)],
    responses={
        **{status: {"model": ErrorResponse} for status in (400, 401, 403, 422, 500)},
        503: {"model": InventoryUnavailableResponse},
    },
    openapi_extra={"x-stage": "foundation", "x-required-roles": ["viewer"],
                   "x-availability": "local-validation-only"},
)
def list_inventory(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> InventoryPage:
    """Read inventory from a consistent snapshot; no live provider is configured."""
    runtime: InventoryRuntime = request.app.state.inventory_runtime
    now = runtime.clock()
    cursors: InventoryCursors = request.app.state.inventory_cursors
    continuation = cursors.decode(cursor, now=now, limit=limit, policy=runtime.freshness_policy) \
        if cursor is not None else None
    after = f"v1:skus:{continuation.after_id}" if continuation else None
    evaluated_at = continuation.evaluated_at if continuation else now
    try:
        with request.app.state.database.session() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            snapshot_text = connection.execute("SELECT pg_current_snapshot()::text").fetchone()[0]
            snapshot = hashlib.sha256(snapshot_text.encode()).digest()[:16]
            if continuation and continuation.snapshot != snapshot:
                raise ApplicationError(ErrorCode.BAD_REQUEST)
            page = CatalogRepository(connection).list_skus(limit=limit, cursor=after)
            stock = StockRepository(connection)
            items = []
            for sku in page.items:
                observation = stock.get(sku.id)
                decision = inventory_eligibility(
                    observation, now=evaluated_at, policy=runtime.freshness_policy,
                )
                availability = {
                    InventoryEligibility.IN_STOCK: "in_stock",
                    InventoryEligibility.OUT_OF_STOCK: "out_of_stock",
                    InventoryEligibility.STALE_STOCK: "stale",
                }.get(decision, "unknown")
                items.append(InventoryItem(
                    item_id=str(sku.id), stock=availability,
                    observed_at=observation.observed_at if observation else None,
                    source_version=str(observation.source_version) if observation else None,
                ))
    except psycopg.Error:
        raise InventoryUnavailable(retryable=True) from None
    next_cursor = cursors.encode(InventoryCursor(
        int(page.next_cursor.rsplit(":", 1)[1]), evaluated_at, limit,
        snapshot, policy_digest(runtime.freshness_policy),
    )) if page.next_cursor else None
    return InventoryPage(items=items, page=InventoryPageInfo(limit=limit, next_cursor=next_cursor))
