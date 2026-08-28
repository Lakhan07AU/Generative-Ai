def test_register_and_login(client):
    res = client.post(
        "/auth/register",
        json={"email": "new@test.com", "name": "New User", "password": "secret123", "role": "INVESTIGATOR"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["email"] == "new@test.com"
    assert "password" not in body

    login = client.post("/auth/login", json={"email": "new@test.com", "password": "secret123"})
    assert login.status_code == 200, login.text
    data = login.json()
    assert data["access_token"]
    assert data["user"]["role"] == "INVESTIGATOR"


def test_register_duplicate_email(client):
    payload = {"email": "dup@test.com", "name": "Dup", "password": "secret123", "role": "INVESTIGATOR"}
    assert client.post("/auth/register", json=payload).status_code == 201
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 409


def test_login_wrong_password(client):
    client.post(
        "/auth/register",
        json={"email": "wrong@test.com", "name": "Wrong", "password": "secret123", "role": "INVESTIGATOR"},
    )
    res = client.post("/auth/login", json={"email": "wrong@test.com", "password": "badpass"})
    assert res.status_code == 401


def test_invalid_role_rejected(client):
    res = client.post(
        "/auth/register",
        json={"email": "badrole@test.com", "name": "Bad", "password": "secret123", "role": "GHOST"},
    )
    assert res.status_code == 400


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code in (401, 403)


def test_me_with_token(client, auth_headers):
    res = client.get("/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["email"] == "investigator@test.com"


def test_logout(client, auth_headers):
    res = client.post("/auth/logout", headers=auth_headers)
    assert res.status_code == 200


def test_password_is_hashed(client, db):
    from app.database.models import User

    client.post(
        "/auth/register",
        json={"email": "hash@test.com", "name": "Hash", "password": "secret123", "role": "INVESTIGATOR"},
    )
    user = db.query(User).filter(User.email == "hash@test.com").first()
    assert user is not None
    assert user.password_hash != "secret123"
    assert user.password_hash.startswith("$2")
