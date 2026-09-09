from fastapi.testclient import TestClient

from colab.api import create_app


def test_release_governance_version_and_promotion_flow() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/api/governance/versions",
        json={
            "name": "demo",
            "version": "1.0.0",
            "artifact_digest": "artifact",
            "manifest_hash": "manifest",
        },
    )
    assert created.status_code == 201
    version_id = created.json()["version_id"]
    response = client.post(
        f"/api/governance/versions/{version_id}/promote",
        json={
            "from_stage": "staging",
            "to_stage": "production",
            "gates": [
                {"gate": "reproducibility", "passed": True, "score": 100},
                {"gate": "version_integrity", "passed": True, "score": 100},
                {"gate": "regression", "passed": True, "score": 100},
                {"gate": "operational_readiness", "passed": True, "score": 100},
                {"gate": "risk", "passed": True, "score": 100},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["approved"] is True


def test_release_governance_rejects_missing_required_gate() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/api/governance/versions",
        json={"name": "demo-missing", "version": "1.0.0", "artifact_digest": "a", "manifest_hash": "m"},
    )
    version_id = created.json()["version_id"]
    response = client.post(
        f"/api/governance/versions/{version_id}/promote",
        json={
            "from_stage": "staging",
            "to_stage": "production",
            "gates": [
                {"gate": "reproducibility", "passed": True, "score": 100},
                {"gate": "version_integrity", "passed": True, "score": 100},
                {"gate": "regression", "passed": True, "score": 100},
                {"gate": "operational_readiness", "passed": True, "score": 100},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is False
    assert any("risk" in reason for reason in body["reasons"])
