"""Tests for FastAPI health, pipeline tooltips, and presets endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_check():
    from backend.main import app

    client = TestClient(app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_pipeline_tooltips_endpoint():
    from backend.main import app

    client = TestClient(app)
    resp = client.get("/api/v1/pipeline/tooltips")
    assert resp.status_code == 200
    data = resp.json()
    assert "best_of_n" in data
    assert "rag_enabled" in data
    assert data["best_of_n"]["title"] != ""


def test_pipeline_presets_endpoint():
    from backend.main import app

    client = TestClient(app)
    resp = client.get("/api/v1/pipeline/presets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    names = {item["name"] for item in data}
    assert names == {"fast", "balanced", "precise"}


def test_generate_endpoint_exists():
    from backend.main import app

    client = TestClient(app)
    # POST without file should return 422 (validation error), not 404
    resp = client.post("/api/generate")
    assert resp.status_code == 422
