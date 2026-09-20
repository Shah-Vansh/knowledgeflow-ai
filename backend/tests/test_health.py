def test_health_returns_200_when_db_connected(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["db_connected"] is True
    assert body["status"] == "ok"


def test_health_response_shape(client):
    response = client.get("/health")
    body = response.json()
    assert "status" in body
    assert "db_connected" in body
    assert "environment" in body