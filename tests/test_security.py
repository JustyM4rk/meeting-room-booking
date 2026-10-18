from datetime import datetime, timedelta, timezone

from jose import jwt

import auth


def slot(day_offset=1, hour=10, hours=1):
    start = (datetime.now() + timedelta(days=day_offset)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(hours=hours)).isoformat()


def book(client, headers, user_id, room_id, start, end):
    return client.post("/bookings/", headers=headers, json={
        "room_id": room_id, "user_id": user_id, "start_time": start, "end_time": end,
    })


# ---------- authentication ----------

def test_login_returns_token(client, seeded):
    res = client.post("/login/", json={"email": "alice@test.com", "password": "Password123"})
    assert res.status_code == 200
    assert res.json()["token_type"] == "bearer"
    assert res.json()["access_token"]


def test_login_errors_do_not_reveal_which_emails_exist(client, seeded):
    wrong_password = client.post("/login/", json={"email": "alice@test.com", "password": "wrong"})
    unknown_user = client.post("/login/", json={"email": "nobody@test.com", "password": "wrong"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_protected_endpoints_require_a_token(client):
    for method, url in [
        ("get", "/rooms/"), ("get", "/bookings/"), ("get", "/users/"),
        ("get", "/analytics/dashboard"), ("post", "/ml/train"), ("get", "/ml/predict?day=1&hour=10"),
    ]:
        assert getattr(client, method)(url).status_code == 401, url


def test_garbage_and_forged_tokens_are_rejected(client, seeded):
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert client.get("/rooms/", headers=bad).status_code == 401

    forged = jwt.encode({"sub": str(seeded["admin"]), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                        "some-other-secret", algorithm="HS256")
    assert client.get("/users/", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_expired_token_is_rejected(client, seeded):
    expired = jwt.encode({"sub": str(seeded["alice"]), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
                         auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    assert client.get("/rooms/", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


# ---------- roles ----------

def test_regular_user_cannot_use_admin_endpoints(client, alice_h):
    assert client.get("/users/", headers=alice_h).status_code == 403
    assert client.post("/rooms/", headers=alice_h, json={"name": "X", "capacity": 2}).status_code == 403
    assert client.get("/analytics/dashboard", headers=alice_h).status_code == 403
    assert client.post("/ml/train", headers=alice_h).status_code == 403


def test_admin_can_manage_rooms_and_list_users(client, admin_h):
    assert client.get("/users/", headers=admin_h).status_code == 200
    assert client.post("/rooms/", headers=admin_h, json={"name": "Admin room", "capacity": 4}).status_code == 200


def test_registration_cannot_choose_a_role_and_enforces_password_length(client):
    ok = client.post("/users/", json={"email": "eve@test.com", "name": "Eve", "password": "LongEnough1", "role": "admin"})
    assert ok.status_code == 200
    assert ok.json()["role"] == "user"
    short = client.post("/users/", json={"email": "eve2@test.com", "name": "Eve", "password": "short"})
    assert short.status_code == 422


# ---------- bookings: ownership and rules ----------

def test_user_cannot_book_on_behalf_of_someone_else(client, alice_h, seeded):
    start, end = slot(day_offset=2)
    res = book(client, alice_h, seeded["bob"], seeded["room"], start, end)
    assert res.status_code == 403


def test_overlapping_booking_is_rejected_with_409(client, alice_h, bob_h, seeded):
    start, end = slot(day_offset=3)
    assert book(client, alice_h, seeded["alice"], seeded["room"], start, end).status_code == 200
    assert book(client, bob_h, seeded["bob"], seeded["room"], start, end).status_code == 409


def test_user_cannot_edit_or_delete_someone_elses_booking(client, alice_h, bob_h, seeded):
    start, end = slot(day_offset=4)
    created = book(client, alice_h, seeded["alice"], seeded["room"], start, end).json()
    url = f"/bookings/{created['id']}"
    assert client.put(url, headers=bob_h, json={"comment": "hijacked"}).status_code == 403
    assert client.delete(url, headers=bob_h).status_code == 403
    assert client.delete(url, headers=alice_h).status_code == 200


def test_user_cannot_approve_their_own_booking_but_admin_can(client, alice_h, admin_h, seeded):
    start, end = slot(day_offset=5, hour=8, hours=5)  # longer than 3 hours -> pending
    created = book(client, alice_h, seeded["alice"], seeded["room"], start, end).json()
    assert created["status"] == "pending"
    url = f"/bookings/{created['id']}"
    assert client.put(url, headers=alice_h, json={"status": "confirmed"}).status_code == 403
    assert client.put(url, headers=admin_h, json={"status": "confirmed"}).status_code == 200


def test_editing_into_an_occupied_slot_is_rejected(client, alice_h, bob_h, seeded):
    a_start, a_end = slot(day_offset=6, hour=10)
    b_start, b_end = slot(day_offset=6, hour=12)
    book(client, alice_h, seeded["alice"], seeded["room"], a_start, a_end)
    bobs = book(client, bob_h, seeded["bob"], seeded["room"], b_start, b_end).json()
    res = client.put(f"/bookings/{bobs['id']}", headers=bob_h, json={"start_time": a_start, "end_time": a_end})
    assert res.status_code == 409


def test_invalid_status_value_is_rejected(client, admin_h, alice_h, seeded):
    start, end = slot(day_offset=7)
    created = book(client, alice_h, seeded["alice"], seeded["room"], start, end).json()
    res = client.put(f"/bookings/{created['id']}", headers=admin_h, json={"status": "hacked"})
    assert res.status_code == 422
