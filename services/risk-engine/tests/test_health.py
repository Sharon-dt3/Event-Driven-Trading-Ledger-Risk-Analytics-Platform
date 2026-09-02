from fastapi.testclient import TestClient

from app.correlation import CORRELATION_HEADER
from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "UP", "service": "risk-engine"}


def test_correlation_header_generated():
    resp = client.get("/health")
    assert resp.headers.get(CORRELATION_HEADER)


def test_correlation_header_preserved():
    cid = "test-correlation-id"
    resp = client.get("/health", headers={CORRELATION_HEADER: cid})
    assert resp.headers.get(CORRELATION_HEADER) == cid
