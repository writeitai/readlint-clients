"""Contract tests exercise actual SDK methods and CLI parsing, not a raw escape hatch."""

import copy
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Literal, Union, get_args, get_origin, get_type_hints, is_typeddict
from urllib.parse import parse_qs

import httpx
import jsonschema
import pytest

from readlint import Readlint, auth, cli
from readlint import types as response_types

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/openapi.json").read_text())
FIXTURES = json.loads((ROOT / "contracts/fixtures.json").read_text())
ID = FIXTURES["evaluation"]["id"]
SPEC = importlib.util.spec_from_file_location(
    "check_contract", ROOT / "scripts/check_contract.py"
)
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def expand(schema, document=SCHEMA):
    if isinstance(schema, list):
        return [expand(item, document) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        value = document
        for segment in schema["$ref"].removeprefix("#/").split("/"):
            value = value[segment]
        return expand(value, document)
    return {key: expand(value, document) for key, value in schema.items()}


def operation(call):
    path = call["path"].replace(ID, "{evaluation_id}")
    return f"{call['method']} {path}", SCHEMA["paths"][path][call["method"].lower()]


def validate_calls(calls, client, document=SCHEMA):
    seen = set()
    for call in calls:
        name, _ = operation(call)
        path = name.split(" ", 1)[1]
        op = document["paths"][path][call["method"].lower()]
        seen.add(name)
        headers = {key.lower(): value for key, value in call["headers"].items()}
        query = call["query"]
        parameters = op.get("parameters", [])
        assert set(query) == {p["name"] for p in parameters if p["in"] == "query"}
        for parameter in parameters:
            where, key = parameter["in"], parameter["name"]
            value = {"path": {"evaluation_id": ID}, "query": query, "header": headers}[
                where
            ][key.lower() if where == "header" else key]
            if where == "query":
                value = int(value)
            jsonschema.validate(
                value,
                expand(parameter["schema"], document),
                format_checker=jsonschema.FormatChecker(),
            )
        assert headers.get("authorization") == (
            "Bearer rlk_contract" if op.get("security") else None
        )
        if "requestBody" in op:
            content_type, media = next(iter(op["requestBody"]["content"].items()))
            assert headers["content-type"] == content_type
            body_schema = expand(media["schema"], document)
            # Exercise all supported fields, including optional fields. A new
            # parameter cannot be covered by editing just the inventory.
            assert set(call["body"]) == set(body_schema["properties"])
            jsonschema.validate(call["body"], body_schema)
        else:
            assert call["body"] is None
    coverage = json.loads((ROOT / "contracts/clients.json").read_text())[client]
    assert seen == {
        op for op, entry in coverage.items() if not entry.startswith("Excluded:")
    }


def capture(request):
    content_type = request.headers.get("content-type", "")
    body = None
    if request.content:
        body = (
            json.loads(request.content)
            if content_type == "application/json"
            else {
                key: values[0]
                for key, values in parse_qs(
                    request.content.decode(), keep_blank_values=True
                ).items()
            }
        )
    return {
        "method": request.method,
        "path": request.url.path,
        "headers": dict(request.headers),
        "query": dict(request.url.params),
        "body": body,
    }


@pytest.fixture
def transport(monkeypatch):
    calls = []

    def serve(request):
        calls.append(capture(request))
        path = request.url.path
        if request.method == "DELETE":
            return httpx.Response(204)
        fixture = (
            "billing_" + path.rsplit("/", 1)[1]
            if path.startswith("/v1/billing/")
            else "agent_permissions"
            if path == "/v1/agent-permissions"
            else "device_code"
            if path == "/auth/device/code"
            else "device_token"
            if path == "/auth/device/token"
            else "page"
            if path == "/v1/evaluations" and request.method == "GET"
            else "evaluation"
        )
        return httpx.Response(200, json=FIXTURES[fixture])

    monkeypatch.setattr(auth.time, "sleep", lambda _: None)
    monkeypatch.setattr(auth, "save_credentials", lambda *args: None)
    return calls, httpx.MockTransport(serve)


def test_python_requests(transport):
    calls, mock = transport
    with Readlint("rlk_contract", transport=mock) as client:
        auth.login(client, lambda *args: None)
        assert (
            client.evaluate(
                "# Article",
                idempotency_key="contract-key",
                title="Contract",
                description="Context",
            )
            == FIXTURES["evaluation"]
        )
        assert client.get_agent_permissions() == FIXTURES["agent_permissions"]
        assert client.get_billing_status() == FIXTURES["billing_status"]
        assert client.create_billing_quote() == FIXTURES["billing_quote"]
        assert (
            client.confirm_billing_order(
                ID,
                terms_version="2026-11-25",
                paid_order_confirmed=True,
                idempotency_key=ID,
            )
            == FIXTURES["billing_order"]
        )
        assert (
            client.cancel_billing_plan(idempotency_key=ID) == FIXTURES["billing_cancel"]
        )
        assert client.create_billing_portal() == FIXTURES["billing_portal"]
        assert client.list_evaluations(limit=3, offset=2) == FIXTURES["page"]
        assert client.get_evaluation(ID) == FIXTURES["evaluation"]
        client.delete_evaluation(ID)
    validate_calls(calls, "python")


def test_cli_requests(transport, monkeypatch, capsys):
    calls, mock = transport
    monkeypatch.setattr(
        cli, "Readlint", lambda **kwargs: Readlint(transport=mock, **kwargs)
    )
    for arguments, expected in [
        (["login"], {"signed_in": True}),
        (["agent-permissions", "get"], FIXTURES["agent_permissions"]),
        (["billing", "status"], FIXTURES["billing_status"]),
        (["billing", "quote"], FIXTURES["billing_quote"]),
        (
            [
                "billing",
                "order",
                "--quote-id",
                ID,
                "--terms-version",
                "2026-11-25",
                "--agree-to-pay",
                "--idempotency-key",
                ID,
            ],
            FIXTURES["billing_order"],
        ),
        (["billing", "cancel", "--idempotency-key", ID], FIXTURES["billing_cancel"]),
        (["billing", "portal"], FIXTURES["billing_portal"]),
        (
            [
                "evaluate",
                "-",
                "--title",
                "Contract",
                "--description",
                "Context",
                "--idempotency-key",
                "contract-key",
            ],
            FIXTURES["evaluation"],
        ),
        (["list", "--limit", "3", "--offset", "2"], FIXTURES["page"]),
        (["get", ID], FIXTURES["evaluation"]),
        (["delete", ID], {"deleted": True, "id": ID}),
    ]:
        from io import StringIO

        monkeypatch.setattr(sys, "stdin", StringIO("# Article"))
        monkeypatch.setattr(
            sys, "argv", ["readlint", "--json", "--api-key", "rlk_contract", *arguments]
        )
        assert cli.main() == 0
        assert json.loads(capsys.readouterr().out) == expected
    validate_calls(calls, "cli")


def typescript_calls():
    return json.loads(
        subprocess.check_output(
            ["node", "sdk/typescript/test/requests.mjs"], cwd=ROOT, text=True
        )
    )


def test_typescript_requests():
    validate_calls(typescript_calls(), "typescript")


def test_inventory_and_response_fixtures():
    CHECK.check_coverage(SCHEMA)
    for path, methods in SCHEMA["paths"].items():
        for method, op in methods.items():
            if method == "delete":
                assert "204" in op["responses"]
                continue
            fixture = (
                "billing_" + path.rsplit("/", 1)[1]
                if path.startswith("/v1/billing/")
                else "agent_permissions"
                if path == "/v1/agent-permissions"
                else "device_code"
                if path == "/auth/device/code"
                else "device_token"
                if path == "/auth/device/token"
                else "page"
                if path == "/v1/evaluations" and method == "get"
                else "evaluation"
            )
            jsonschema.validate(
                FIXTURES[fixture],
                expand(op["responses"]["200"]["content"]["application/json"]["schema"]),
                format_checker=jsonschema.FormatChecker(),
            )
            for status, response in op["responses"].items():
                if int(status) < 400:
                    continue
                schema = response["content"]["application/json"]["schema"]
                if status == "502" and path == "/v1/evaluations":
                    body = {
                        **FIXTURES["evaluation"],
                        "status": "failed",
                        "error_code": "upstream_error",
                    }
                elif path.startswith("/auth/") and status == "400":
                    body = {"error": "authorization_pending"}
                else:
                    body = {
                        "detail": {
                            "code": "validation_error"
                            if status == "422"
                            else "authentication_required"
                        }
                    }
                jsonschema.validate(body, expand(schema))


def assert_type(annotation, schema):
    schema = expand(schema)
    assert isinstance(schema, dict)
    origin = get_origin(annotation)
    if origin in (types.UnionType, Union):
        assert len(get_args(annotation)) == len(schema["anyOf"])
        for item, branch in zip(get_args(annotation), schema["anyOf"], strict=True):
            assert_type(item, branch)
    elif origin is Literal:
        assert set(get_args(annotation)) == set(
            schema.get("enum", [schema.get("const")])
        )
    elif origin is list:
        assert schema["type"] == "array"
        assert_type(get_args(annotation)[0], schema["items"])
    elif is_typeddict(annotation):
        hints = get_type_hints(annotation)
        assert set(hints) == set(schema["properties"])
        assert annotation.__required_keys__ == set(schema["required"])
        for key, value in hints.items():
            assert_type(value, schema["properties"][key])
    else:
        assert {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            type(None): "null",
        }[annotation] == schema["type"]


def test_python_public_types_match_response_schema():
    for name, schema in [
        ("AgentPermissions", "AgentPermissions"),
        ("BillingStatus", "AgentBillingStatus"),
        ("BillingQuote", "AgentQuote"),
        ("BillingOrder", "OrderAccepted"),
        ("BillingCancellation", "Cancellation"),
        ("BillingPortal", "PortalLink"),
        ("Evaluation", "EvaluationResult"),
        ("EvaluationPage", "EvaluationPage"),
    ]:
        assert_type(
            getattr(response_types, name), SCHEMA["components"]["schemas"][schema]
        )


def test_added_operation_fails_coverage():
    changed = copy.deepcopy(SCHEMA)
    changed["paths"]["/v1/new-operation"] = {"post": {}}
    with pytest.raises(AssertionError, match="stale operation coverage"):
        CHECK.check_coverage(changed)


def test_added_parameter_and_changed_body_fail_actual_clients(transport):
    calls, mock = transport
    with Readlint("rlk_contract", transport=mock) as client:
        client.list_evaluations(limit=3, offset=2)
    changed = copy.deepcopy(SCHEMA)
    changed["paths"]["/v1/evaluations"]["get"]["parameters"].append(
        {"in": "query", "name": "search", "schema": {"type": "string"}}
    )
    with pytest.raises(AssertionError):
        validate_calls(calls, "python", changed)
    calls = typescript_calls()
    changed = copy.deepcopy(SCHEMA)
    changed["components"]["schemas"]["EvaluationRequest"]["properties"]["audience"] = {
        "type": "string"
    }
    with pytest.raises(AssertionError):
        validate_calls(calls, "typescript", changed)


def test_stale_generated_types_fail(tmp_path):
    changed = copy.deepcopy(SCHEMA)
    changed["components"]["schemas"]["EvaluationResult"]["properties"]["new_field"] = {
        "type": "boolean"
    }
    schema = tmp_path / "changed.json"
    schema.write_text(json.dumps(changed))
    import os

    run = subprocess.run(
        ["npm", "run", "check:openapi"],
        cwd=ROOT / "sdk/typescript",
        env={**os.environ, "READLINT_OPENAPI_INPUT": str(schema)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode != 0
    assert "new_field" in run.stdout


def test_python_mcp_requests(transport, monkeypatch):
    from readlint import mcp

    calls, mock = transport
    monkeypatch.setattr(
        mcp,
        "Readlint",
        lambda *args, **kwargs: Readlint(*args, transport=mock, **kwargs),
    )
    for name, arguments in [
        (
            "evaluate_article",
            {
                "article": "# Article",
                "title": "Contract",
                "description": "Context",
                "idempotency_key": "contract-key",
            },
        ),
        ("list_evaluations", {"limit": 3, "offset": 2}),
        ("get_evaluation", {"evaluation_id": ID}),
        ("delete_evaluation", {"evaluation_id": ID}),
    ]:
        assert not mcp.call_tool(name, arguments, api_key="rlk_contract").isError
    validate_calls(calls, "python_mcp")


def test_node_cli_and_mcp_requests():
    results = json.loads(
        subprocess.check_output(
            ["node", "sdk/typescript/test/surfaces.mjs"], cwd=ROOT, text=True
        )
    )
    for surface, calls in results.items():
        validate_calls(calls, surface)


def test_tool_catalogue_matches_python_and_stays_small():
    from readlint.mcp import TOOLS

    expected = [tool.model_dump(exclude_none=True) for tool in TOOLS]
    actual = json.loads(
        subprocess.check_output(
            [
                "node",
                "--input-type=module",
                "-e",
                "import {TOOLS} from './sdk/typescript/dist/tools.js'; console.log(JSON.stringify(TOOLS))",
            ],
            cwd=ROOT,
            text=True,
        )
    )
    assert actual == expected
    assert len(json.dumps(actual, separators=(",", ":")).encode()) <= 6000


def test_renamed_mcp_tool_fails_coverage(transport, monkeypatch):
    from readlint import mcp

    calls, _ = transport
    monkeypatch.setattr(
        mcp,
        "TOOLS",
        [
            tool.model_copy(update={"name": "renamed"})
            if tool.name == "evaluate_article"
            else tool
            for tool in mcp.TOOLS
        ],
    )
    assert mcp.call_tool(
        "evaluate_article",
        {"article": "text", "idempotency_key": "retained"},
        api_key="rlk_contract",
    ).isError
    with pytest.raises(AssertionError):
        validate_calls(calls, "python_mcp")
