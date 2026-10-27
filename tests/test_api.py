from fastapi.testclient import TestClient

from fretflow.api import create_app


def test_health_endpoint():
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_stem_types_endpoint_exposes_only_product_allowlist():
    response = TestClient(create_app()).get("/api/stem-types")
    assert response.status_code == 200
    payload = response.json()
    assert [item["value"] for item in payload] == [
        "acoustic-guitar",
        "electric-guitar",
        "bass",
        "drums",
        "vocal",
    ]
    assert [item["value"] for item in payload if item["default_selected"]] == [
        "acoustic-guitar",
        "electric-guitar",
    ]


def test_http_errors_use_the_stable_error_envelope():
    response = TestClient(create_app()).get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "HTTP_404",
            "message": "Not Found",
            "details": {},
        }
    }
