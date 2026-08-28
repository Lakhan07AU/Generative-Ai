def test_list_cameras_requires_auth(client):
    assert client.get("/cameras").status_code in (401, 403)


def test_create_and_list_camera(client, auth_headers):
    res = client.post(
        "/cameras",
        headers=auth_headers,
        json={"camera_name": "CAM-10", "location": "Parking", "description": "North entrance"},
    )
    assert res.status_code == 201, res.text
    camera_id = res.json()["id"]
    assert res.json()["camera_name"] == "CAM-10"

    ls = client.get("/cameras", headers=auth_headers)
    assert ls.status_code == 200
    ids = [c["id"] for c in ls.json()]
    assert camera_id in ids


def test_get_camera(client, auth_headers):
    created = client.post(
        "/cameras", headers=auth_headers, json={"camera_name": "CAM-11", "location": "Gate"}
    ).json()
    res = client.get(f"/cameras/{created['id']}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["location"] == "Gate"


def test_get_missing_camera_404(client, auth_headers):
    res = client.get("/cameras/99999", headers=auth_headers)
    assert res.status_code == 404
