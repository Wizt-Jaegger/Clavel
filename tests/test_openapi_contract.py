"""Synthetic draft fixtures prove contract mechanics, never live capability."""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate

from clavel.api.app import create_app
from clavel.core.errors import ErrorResponse
from clavel.core.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "docs/openapi/clavel-v1.draft.json").read_text())
OPERATIONS = [(path, method, op) for path, methods in SPEC["paths"].items()
              for method, op in methods.items()]


def resolve(node):
    if "$ref" not in node:
        return node
    result = SPEC
    for part in node["$ref"].removeprefix("#/").split("/"):
        result = result[part]
    return result


def validator(schema):
    # Keep local #/components refs in the same JSON Schema resource.
    root = {**schema, "components": SPEC["components"]}
    return Draft202012Validator(root, format_checker=FormatChecker())


def example_cases():
    for path, method, op in OPERATIONS:
        containers = list(op["responses"].items())
        if "requestBody" in op:
            containers.append(("request", op["requestBody"]))
        for status, container in containers:
            for media in resolve(container)["content"].values():
                for name, example in media["examples"].items():
                    yield pytest.param(media["schema"], example["value"],
                                       id=f"{method}:{path}:{status}:{name}")


def test_openapi_lint():
    validate(SPEC)
    for schema in SPEC["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(("schema", "example"), list(example_cases()))
def test_all_synthetic_request_and_response_examples(schema, example):
    validator(schema).validate(example)


def test_contract_has_provenance_and_explicit_stage_roles_and_examples():
    assert SPEC["info"]["version"] == "1.0.0-draft.2"
    assert SPEC["x-fixture-provenance"]["kind"] == "synthetic"
    ids = [op["operationId"] for _, _, op in OPERATIONS]
    assert len(ids) == len(set(ids))
    for path, method, op in OPERATIONS:
        assert path.startswith("/v1/")
        assert op["operationId"].startswith("v1_")
        assert op["x-availability"] == "design-time"
        initial = path in {"/v1/catalog", "/v1/inventory", "/v1/segments",
                           "/v1/recommendations/preview", "/v1/events"}
        assert op["x-stage"] == ("foundation" if initial else "emi")
        assert op["security"] == [{"BearerAuth": []}]
        assert op["x-required-roles"]
        if method == "post" and op["x-stage"] == "emi":
            assert op["x-required-roles"] == ["operator"]
        for status in ("400", "401", "403", "404", "409", "422", "500", "503"):
            response = resolve(op["responses"][status])
            assert "X-Request-ID" in response["headers"]
            assert response["content"]["application/json"]["examples"]
        for status, response in op["responses"].items():
            if status.startswith("2"):
                media = response["content"]["application/json"]
                assert "happy" in media["examples"]
                schema = resolve(media["schema"])
                properties = schema["properties"]
                needs_empty = "items" in properties or (
                    path.startswith("/v1/reports/") and "metrics" in properties)
                if needs_empty:
                    assert "empty" in media["examples"]


def test_error_examples_match_existing_runtime_envelope():
    for name, response in SPEC["components"]["responses"].items():
        if name.startswith("Error"):
            value = response["content"]["application/json"]["examples"]["error"]["value"]
            assert ErrorResponse.model_validate(value).model_dump() == value


@pytest.mark.parametrize("stock", ["unknown", "stale", "out_of_stock"])
def test_ineligible_stock_is_preserved_but_cannot_be_recommended(stock):
    inventory = {"item_id": "synthetic-item-1", "stock": stock,
                 "observed_at": None, "source_version": None}
    validator({"$ref": "#/components/schemas/InventoryItem"}).validate(inventory)
    value = copy.deepcopy(SPEC["paths"]["/v1/recommendations/preview"]["post"]
                          ["responses"]["200"]["content"]["application/json"]
                          ["examples"]["happy"]["value"])
    value["items"][0]["stock"] = stock
    assert not validator({"$ref": "#/components/schemas/Preview"}).is_valid(value)


@pytest.mark.parametrize(("field", "value"), [
    ("compatibility", "unknown"), ("compatibility", "incompatible"),
    ("stock_observed_at", None), ("stock_observed_at", "invalid-date"),
    ("stock_source_version", None),
])
def test_missing_eligibility_evidence_is_rejected(field, value):
    example = SPEC["paths"]["/v1/recommendations/preview"]["post"]["responses"]\
        ["200"]["content"]["application/json"]["examples"]["happy"]["value"]
    item = {**example["items"][0], field: value}
    assert not validator({"$ref": "#/components/schemas/Recommendation"}).is_valid(item)


def test_empty_preview_and_unavailable_metrics_cannot_disguise_success():
    example = SPEC["paths"]["/v1/recommendations/preview"]["post"]["responses"]\
        ["200"]["content"]["application/json"]["examples"]["empty"]["value"]
    check = validator({"$ref": "#/components/schemas/Preview"})
    assert not check.is_valid({**example, "state": "ready"})
    assert not check.is_valid({**example, "empty_reason": None})
    metric = {"name": "silhouette", "value": 0, "state": "unavailable",
              "reason": "not_measured", "sample_count": None}
    assert not validator({"$ref": "#/components/schemas/Metric"}).is_valid(metric)


def paused_preview_contract():
    operation = SPEC["paths"]["/v1/recommendations/preview"]["post"]
    response = resolve(operation["responses"]["503"])
    media = response["content"]["application/json"]
    return operation, media, media["examples"]["recommendations_paused"]["value"]


def test_paused_preview_is_unavailable_and_requires_operator_enable():
    operation, media, example = paused_preview_contract()
    assert example == {
        "state": "unavailable", "reason": "recommendations_paused",
        "retryable": False, "request_id": "synthetic-request-1",
    }
    validator(media["schema"]).validate(example)
    success = operation["responses"]["200"]["content"]["application/json"]
    assert not validator(success["schema"]).is_valid(example)
    for name in ("happy", "empty"):
        assert not validator(media["schema"]).is_valid(success["examples"][name]["value"])


@pytest.mark.parametrize(("field", "value"), [
    ("state", "ready"), ("state", "empty"), ("retryable", True),
    ("reason", "unknown_pause_reason"), ("request_id", ""), ("items", []),
])
def test_paused_preview_rejects_misleading_or_invalid_payloads(field, value):
    _, media, example = paused_preview_contract()
    assert not validator(media["schema"]).is_valid({**example, field: value})


def test_draft_adds_no_runtime_routes_or_business_schema():
    # Synthetic local settings; no external service or database is accessed.
    app = create_app(settings=Settings(
        _env_file=None, app_env="test",
        database_url="postgresql://synthetic:fake@localhost/synthetic"))
    with TestClient(app) as client:
        runtime = client.get("/openapi.json").json()
        assert set(runtime["paths"]) == {"/health"}
        for path, method, _ in OPERATIONS:
            response = client.request(method, path)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "not_found"
        assert client.get("/health").json() == {"status": "ok"}
