import os
import sys
from pathlib import Path

# Must be set before the app is imported
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
TEST_DB = Path(__file__).parent / "test.db"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "booking_service"))

import pytest
from fastapi.testclient import TestClient

import crud
import main
import models
import schemas
from database import SessionLocal


def _make_user(db, email, role="user"):
    user = crud.create_user(db, schemas.UserCreate(email=email, name=email.split("@")[0], password="Password123"))
    user.role = role
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(scope="session")
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(scope="session")
def seeded():
    db = SessionLocal()
    admin = _make_user(db, "admin@test.com", role="admin")
    alice = _make_user(db, "alice@test.com")
    bob = _make_user(db, "bob@test.com")
    room = models.Room(name="Room A", capacity=10)
    db.add(room)
    db.commit()
    db.refresh(room)
    data = {"admin": admin.id, "alice": alice.id, "bob": bob.id, "room": room.id}
    db.close()
    return data


def login(client, email, password="Password123"):
    res = client.post("/login/", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_h(client, seeded):
    return login(client, "admin@test.com")


@pytest.fixture(scope="session")
def alice_h(client, seeded):
    return login(client, "alice@test.com")


@pytest.fixture(scope="session")
def bob_h(client, seeded):
    return login(client, "bob@test.com")
