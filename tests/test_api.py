"""Tests de l'API Vélo'v."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient


def test_predict_valid(client, valid_payload):
    r = client.post("/v1/predict", json=valid_payload)
    assert r.status_code == 200
    # 8 h à Lyon (+02:00) + 1 h = 7 h UTC, quel que soit le fuseau dans lequel l'API répond
    target = datetime.fromisoformat(r.json()["target_timestamp"])
    assert target == datetime(2026, 10, 6, 7, tzinfo=UTC)
    pred = r.json()["predicted_bikes"]
    assert 0 <= pred <= valid_payload["capacity"]


def test_predict_rejects_bikes_above_capacity(client, valid_payload):
    r = client.post("/v1/predict", json={**valid_payload, "bikes_available": 25})
    assert r.status_code == 422


def test_predict_rejects_zero_capacity(client, valid_payload):
    r = client.post("/v1/predict", json={**valid_payload, "capacity": 0})
    assert r.status_code == 422


def test_predict_rejects_naive_timestamp(client, valid_payload):
    r = client.post("/v1/predict", json={**valid_payload, "timestamp": "2026-10-06T08:00:00"})
    assert r.status_code == 422


def test_predict_rejects_unknown_field(client, valid_payload):
    r = client.post("/v1/predict", json={**valid_payload, "unexpected_field": 123})
    assert r.status_code == 422


def test_same_instant_different_timezone(client, valid_payload):
    # 06:00:00Z == 08:00:00+02:00
    payload_utc = {**valid_payload, "timestamp": "2026-10-06T06:00:00Z"}
    r1 = client.post("/v1/predict", json=valid_payload)
    r2 = client.post("/v1/predict", json=payload_utc)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["predicted_bikes"] == r2.json()["predicted_bikes"]
    assert r1.json()["target_timestamp"] == r2.json()["target_timestamp"]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_and_model_metadata(client):
    r_ready = client.get("/ready")
    assert r_ready.status_code == 200
    assert r_ready.json()["status"] == "ok"
    assert "model_version" in r_ready.json()

    r_model = client.get("/v1/model")
    assert r_model.status_code == 200
    assert r_model.json()["model_version"] == r_ready.json()["model_version"]


def test_ready_when_model_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from velov.api.main import app

    with TestClient(app) as empty_client:
        r_health = empty_client.get("/health")
        assert r_health.status_code == 200

        r_ready = empty_client.get("/ready")
        assert r_ready.status_code == 503

        r_model = empty_client.get("/v1/model")
        assert r_model.status_code == 503
