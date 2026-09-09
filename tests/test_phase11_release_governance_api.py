from uuid import uuid4

from fastapi.testclient import TestClient

from colab.api import create_app


def _payload(workspace_id: str, name: str = "demo") -> dict[str, object]:
    return {"workspace_id": workspace_id, "name": name, "version": "1.0.0", "artifact_digest": "artifact", "manifest_hash": "manifest"}


def _gates() -> list[dict[str, object]]:
    return [
        {"gate": "reproducibility", "passed": True, "score": 100},
        {"gate": "version_integrity", "passed": True, "score": 100},
        {"gate": "regression", "passed": True, "score": 100},
        {"gate": "operational_readiness", "passed": True, "score": 100},
        {"gate": "risk", "passed": True, "score": 100},
    ]


def test_release_governance_version_and_promotion_flow() -> None:
    client = TestClient(create_app())
    workspace_id = str(uuid4())
    created = client.post("/api/governance/versions", json=_payload(workspace_id))
    assert created.status_code == 201
    version_id = created.json()["version_id"]
    listed = client.get("/api/governance/versions", params={"workspace_id": workspace_id})
    assert listed.status_code == 200
    assert listed.json()[0]["workspace_id"] == workspace_id
    response = client.post(f"/api/governance/versions/{version_id}/promote", json={"workspace_id": workspace_id, "from_stage": "staging", "to_stage": "production", "gates": _gates()})
    assert response.status_code == 200
    assert response.json()["approved"] is True
    decisions = client.get("/api/governance/decisions", params={"workspace_id": workspace_id})
    assert decisions.status_code == 200
    assert len(decisions.json()) == 1


def test_release_governance_rejects_cross_workspace_access() -> None:
    client = TestClient(create_app())
    workspace_a = str(uuid4())
    workspace_b = str(uuid4())
    created = client.post("/api/governance/versions", json=_payload(workspace_a, "isolated"))
    assert created.status_code == 201
    version_id = created.json()["version_id"]
    assert client.get("/api/governance/versions", params={"workspace_id": workspace_b}).json() == []
    response = client.post(f"/api/governance/versions/{version_id}/promote", json={"workspace_id": workspace_b, "from_stage": "staging", "to_stage": "production", "gates": _gates()})
    assert response.status_code == 404


def test_release_governance_rejects_missing_required_gate() -> None:
    client = TestClient(create_app())
    workspace_id = str(uuid4())
    created = client.post("/api/governance/versions", json=_payload(workspace_id, "demo-missing"))
    version_id = created.json()["version_id"]
    response = client.post(f"/api/governance/versions/{version_id}/promote", json={"workspace_id": workspace_id, "from_stage": "staging", "to_stage": "production", "gates": _gates()[:-1]})
    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is False
    assert any("risk" in reason for reason in body["reasons"])
