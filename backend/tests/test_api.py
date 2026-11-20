import json
from dataclasses import dataclass

import pytest


@dataclass
class FakeContext:
    function_name: str = "api"
    memory_limit_in_mb: int = 256
    invoked_function_arn: str = "arn:aws:lambda:us-east-1:000000000000:function:api"
    aws_request_id: str = "test-request"


def _event(method: str, path: str) -> dict:
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {},
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": "127.0.0.1"},
            "requestId": "req",
            "stage": "$default",
        },
        "isBase64Encoded": False,
    }


@pytest.fixture(autouse=True)
def _no_xray(monkeypatch):
    monkeypatch.setenv("POWERTOOLS_TRACE_DISABLED", "true")


def test_health():
    from finxplore.api.handler import handler

    resp = handler(_event("GET", "/health"), FakeContext())
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "ok"


def test_unimplemented_route_returns_501():
    from finxplore.api.handler import handler

    resp = handler(_event("GET", "/companies/aapl"), FakeContext())
    assert resp["statusCode"] == 501
