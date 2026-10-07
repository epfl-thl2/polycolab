"""Follow and interest are independent unique intents, not mathematical assurance."""

from fastapi.testclient import TestClient
from test_catalogue_api import admit, enable, headers


def test_follow_and_interest_are_independent_idempotent_and_private(client: TestClient) -> None:
    enable(client)
    entry = admit(client)
    endpoint = f"/api/v1/community/{entry['entry_id']}"
    original = client.get(f"/api/v1/catalogue/{entry['entry_id']}").json()
    for _ in range(2):
        result = client.put(endpoint + "/follow", headers=headers(), json={"active": True})
        assert result.status_code == 200, result.text
        assert result.json() == {"following": True, "interested": False, "interest_count": 0}
    for _ in range(2):
        result = client.put(endpoint + "/interest", headers=headers(), json={"active": True})
        assert result.json() == {"following": True, "interested": True, "interest_count": 1}
    public = client.get(f"/api/v1/community/{entry['entry_id']}")
    assert public.json() == {"interest_count": 1}
    assert client.get(endpoint + "/me", headers=headers("outsider")).json() == {
        "following": False,
        "interested": False,
        "interest_count": 1,
    }
    for _ in range(2):
        result = client.put(endpoint + "/interest", headers=headers(), json={"active": False})
        assert result.json() == {"following": True, "interested": False, "interest_count": 0}
    assert client.get(f"/api/v1/catalogue/{entry['entry_id']}").json() == original
    assert client.put(endpoint + "/follow", json={"active": True}).status_code == 401
