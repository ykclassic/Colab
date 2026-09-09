from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from colab.api import create_app


def test_quant_backtest_endpoint():
    bars = []
    for i in range(30):
        close = 100 + i * 0.5
        bars.append({
            "timestamp": (datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=i)).isoformat(),
            "symbol": "API",
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000,
        })
    response = TestClient(create_app()).post("/api/quant/backtest", json={
        "workspace_id": "00000000-0000-0000-0000-000000000001",
        "symbol": "API", "bars": bars, "fast_window": 3, "slow_window": 10,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset_checksum"]
    assert payload["result"]["metrics"]["trade_count"] >= 0


def test_quant_backtest_rejects_lookahead_window_order():
    response = TestClient(create_app()).post("/api/quant/backtest", json={
        "workspace_id": "00000000-0000-0000-0000-000000000001",
        "symbol": "API", "bars": [
            {"timestamp": "2025-01-01T00:00:00Z", "symbol": "API", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"timestamp": "2025-01-02T00:00:00Z", "symbol": "API", "open": 100, "high": 101, "low": 99, "close": 101, "volume": 1},
        ], "fast_window": 20, "slow_window": 10,
    })
    assert response.status_code == 422
