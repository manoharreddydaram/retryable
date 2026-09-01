"""Tests for GET /api/results/latest."""

import src.api.results as results_module


def test_results_returns_the_committed_eval_output(api_client) -> None:
    response = api_client.get("/api/results/latest")
    body = response.json()

    assert response.status_code == 200
    assert "incremental_lift" in body
    assert "treatment" in body
    assert "control" in body


def test_results_404s_when_no_file_exists(api_client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(results_module, "_RESULTS_PATH", tmp_path / "missing.json")

    response = api_client.get("/api/results/latest")

    assert response.status_code == 404
    assert response.json()["detail"] == "no_eval_results_yet"
