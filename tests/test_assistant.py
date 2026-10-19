import copy
from datetime import timedelta

import httpx
import pytest

import assistant
import ml_engine
import models
from database import SessionLocal

URL = "/assistant/chat"


# ------------------------------------------------------------------ helpers
def future(days, hour, hours=1):
    start = (assistant.now_local() + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return start, start + timedelta(hours=hours)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M")


def text_reply(text):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}


def tool_call(name, args, call_id=None):
    call = {"name": name, "args": args}
    if call_id:
        call["id"] = call_id
    return {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": call}]}}]}


class FakeLLM:
    """Stands in for Gemini: returns scripted responses and records every request."""

    def __init__(self, *responses, repeat_last=False):
        self.responses = list(responses)
        self.repeat_last = repeat_last
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(copy.deepcopy(payload))
        if len(self.responses) > 1 or (self.responses and not self.repeat_last):
            return self.responses.pop(0)
        return self.responses[0]

    def last_tool_result(self):
        parts = self.payloads[-1]["contents"][-1]["parts"]
        return parts[0]["functionResponse"]["response"]["result"]


def ask(client, headers, text="Привіт", fake=None, monkeypatch=None):
    if fake is not None:
        monkeypatch.setattr(assistant, "call_llm", fake)
    return client.post(URL, headers=headers, json={"messages": [{"role": "user", "content": text}]})


@pytest.fixture(autouse=True)
def _clean_rate_limits():
    assistant.reset_rate_limits()
    yield
    assistant.reset_rate_limits()


@pytest.fixture()
def db():
    session = SessionLocal()
    yield session
    session.close()


def user_by_email(db, email):
    return db.query(models.User).filter(models.User.email == email).first()


def booking_count(db):
    return db.query(models.Booking).count()


# ------------------------------------------------------ access and validation
def test_assistant_requires_authentication(client):
    res = client.post(URL, json={"messages": [{"role": "user", "content": "hi"}]})
    assert res.status_code == 401


def test_returns_503_when_api_key_is_missing(client, alice_h, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert ask(client, alice_h).status_code == 503


def test_rejects_invalid_requests(client, alice_h):
    assert client.post(URL, headers=alice_h, json={"messages": []}).status_code == 422
    too_many = [{"role": "user", "content": "x"}] * 13
    assert client.post(URL, headers=alice_h, json={"messages": too_many}).status_code == 422
    assert client.post(URL, headers=alice_h, json={"messages": [{"role": "system", "content": "x"}]}).status_code == 422
    last_is_assistant = [{"role": "assistant", "content": "hello"}]
    assert client.post(URL, headers=alice_h, json={"messages": last_is_assistant}).status_code == 400
    long_message = [{"role": "user", "content": "x" * (assistant.MAX_USER_MESSAGE_CHARS + 1)}]
    assert client.post(URL, headers=alice_h, json={"messages": long_message}).status_code == 400


def test_rate_limit_per_user(client, alice_h, bob_h, monkeypatch):
    monkeypatch.setattr(assistant, "RATE_LIMIT_PER_HOUR", 2)
    fake = FakeLLM(text_reply("ok"), repeat_last=True)
    assert ask(client, alice_h, fake=fake, monkeypatch=monkeypatch).status_code == 200
    assert ask(client, alice_h).status_code == 200
    assert ask(client, alice_h).status_code == 429
    assert ask(client, bob_h).status_code == 200  # the limit is per user


def test_upstream_failure_does_not_leak_details(client, alice_h, monkeypatch):
    def broken(payload):
        raise assistant.AssistantError("secret internal detail")

    monkeypatch.setattr(assistant, "call_llm", broken)
    res = ask(client, alice_h)
    assert res.status_code == 502
    assert "secret" not in res.text


# --------------------------------------------------------------- the chat loop
def test_plain_reply_and_request_shape(client, alice_h, monkeypatch):
    fake = FakeLLM(text_reply("Вітаю! Чим допомогти?"))
    res = ask(client, alice_h, "Привіт", fake, monkeypatch)
    assert res.status_code == 200
    assert res.json() == {"reply": "Вітаю! Чим допомогти?", "proposal": None}

    payload = fake.payloads[0]
    assert payload["contents"] == [{"role": "user", "parts": [{"text": "Привіт"}]}]
    assert "Europe/Kyiv" in payload["system_instruction"]["parts"][0]["text"]
    declared = {f["name"] for f in payload["tools"][0]["function_declarations"]}
    assert declared == {"list_rooms", "find_available_rooms", "get_my_bookings", "get_load_forecast", "propose_booking"}


def test_tool_round_trip_returns_results_to_the_model(client, alice_h, seeded, monkeypatch):
    start, end = future(40, 10)
    fake = FakeLLM(
        tool_call("find_available_rooms", {"start": iso(start), "end": iso(end), "min_capacity": 5}, call_id="abc"),
        text_reply("Вільна кімната: Room A"),
    )
    res = ask(client, alice_h, "Яка кімната вільна?", fake, monkeypatch)
    assert res.status_code == 200
    assert res.json()["reply"] == "Вільна кімната: Room A"

    contents = fake.payloads[1]["contents"]
    assert contents[-2]["role"] == "model" and "functionCall" in contents[-2]["parts"][0]  # echoed unchanged
    response_part = contents[-1]["parts"][0]["functionResponse"]
    assert response_part["name"] == "find_available_rooms" and response_part["id"] == "abc"
    names = [r["name"] for r in response_part["response"]["result"]["available_rooms"]]
    assert "Room A" in names


def test_runaway_tool_loop_is_capped(client, alice_h, monkeypatch):
    fake = FakeLLM(tool_call("list_rooms", {}), repeat_last=True)
    res = ask(client, alice_h, fake=fake, monkeypatch=monkeypatch)
    assert res.status_code == 200
    assert res.json()["reply"] == assistant.FALLBACK_REPLY
    assert len(fake.payloads) == assistant.MAX_TOOL_ROUNDS


def test_unknown_tool_and_bad_arguments_are_handled(client, alice_h, monkeypatch):
    fake = FakeLLM(tool_call("delete_all_bookings", {}), text_reply("Не можу це зробити"))
    res = ask(client, alice_h, "Видали все", fake, monkeypatch)
    assert res.status_code == 200
    assert "unknown tool" in fake.last_tool_result()["error"]

    fake = FakeLLM(tool_call("find_available_rooms", {"start": "not a date", "end": "also not"}), text_reply("Уточніть дату"))
    assert ask(client, alice_h, "Вільні кімнати", fake, monkeypatch).status_code == 200
    assert "invalid arguments" in fake.last_tool_result()["error"]


# ------------------------------------------------------------ propose_booking
def test_proposal_is_returned_but_nothing_is_written(client, alice_h, seeded, db, monkeypatch):
    start, end = future(41, 14)
    args = {"room_id": seeded["room"], "start": iso(start), "end": iso(end), "title": "Планування",
            "participants_count": 4, "services": ["Проектор", "Кава", "Hacked"]}
    before = booking_count(db)
    fake = FakeLLM(tool_call("propose_booking", args), text_reply("Натисніть «Підтвердити»"))

    res = ask(client, alice_h, "Забронюй Room A", fake, monkeypatch)
    assert res.status_code == 200
    proposal = res.json()["proposal"]
    assert proposal["room_id"] == seeded["room"] and proposal["room_name"] == "Room A"
    assert proposal["participants_count"] == 4
    assert proposal["services"] == "Проектор, Кава"  # unknown services are dropped
    assert proposal["requires_approval"] is False

    db.expire_all()
    assert booking_count(db) == before  # the assistant never creates bookings


def test_long_booking_requires_approval(db, seeded):
    start, end = future(42, 8, hours=5)
    result = assistant.run_tool(
        "propose_booking",
        {"room_id": seeded["room"], "start": iso(start), "end": iso(end)},
        db, user_by_email(db, "alice@test.com"),
    )
    assert result["status"] == "ok" and result["proposal"]["requires_approval"] is True


def test_proposal_for_an_occupied_slot_is_rejected(client, alice_h, seeded, db):
    start, end = future(43, 10)
    created = client.post("/bookings/", headers=alice_h, json={
        "room_id": seeded["room"], "user_id": seeded["alice"],
        "start_time": start.isoformat(), "end_time": end.isoformat(),
    })
    assert created.status_code == 200
    result = assistant.run_tool(
        "propose_booking",
        {"room_id": seeded["room"], "start": iso(start), "end": iso(end)},
        db, user_by_email(db, "bob@test.com"),
    )
    assert result["status"] == "error" and "already booked" in result["reason"]


@pytest.mark.parametrize("override, expected", [
    ({"room_id": "no-such-room"}, "room not found"),
    ({"participants_count": 11}, "fits 10"),
    ({"participants_count": 0}, "at least 1"),
])
def test_proposal_validation(db, seeded, override, expected):
    start, end = future(44, 10)
    args = {"room_id": seeded["room"], "start": iso(start), "end": iso(end), **override}
    result = assistant.run_tool("propose_booking", args, db, user_by_email(db, "alice@test.com"))
    assert result["status"] == "error" and expected in result["reason"]


def test_proposal_time_validation(db, seeded):
    user = user_by_email(db, "alice@test.com")
    start, end = future(45, 10)
    past_start, past_end = future(-2, 10)
    assert "past" in assistant.run_tool("propose_booking", {"room_id": seeded["room"], "start": iso(past_start), "end": iso(past_end)}, db, user)["reason"]
    assert "later" in assistant.run_tool("propose_booking", {"room_id": seeded["room"], "start": iso(end), "end": iso(start)}, db, user)["reason"]
    long_start, long_end = future(45, 6, hours=13)
    assert "longer" in assistant.run_tool("propose_booking", {"room_id": seeded["room"], "start": iso(long_start), "end": iso(long_end)}, db, user)["reason"]


# -------------------------------------------------------- data isolation
def test_get_my_bookings_returns_only_the_callers_bookings(client, alice_h, bob_h, seeded, monkeypatch):
    start, end = future(46, 10)
    created = client.post("/bookings/", headers=alice_h, json={
        "room_id": seeded["room"], "user_id": seeded["alice"], "title": "Alice private meeting",
        "start_time": start.isoformat(), "end_time": end.isoformat(),
    })
    assert created.status_code == 200

    fake = FakeLLM(tool_call("get_my_bookings", {}), text_reply("Готово"))
    ask(client, alice_h, "Мої бронювання", fake, monkeypatch)
    assert "Alice private meeting" in [b["title"] for b in fake.last_tool_result()["bookings"]]

    fake = FakeLLM(tool_call("get_my_bookings", {}), text_reply("Готово"))
    ask(client, bob_h, "Мої бронювання", fake, monkeypatch)
    assert "Alice private meeting" not in str(fake.last_tool_result())


# ----------------------------------------------------------- forecast tool
def test_forecast_tool(db, monkeypatch):
    user = user_by_email(db, "alice@test.com")
    monkeypatch.setattr(ml_engine, "predict_load", lambda day, hour: 80)
    assert assistant.run_tool("get_load_forecast", {"day_of_week": 1, "hour": 10}, db, user)["load"] == "medium"
    assert "error" in assistant.run_tool("get_load_forecast", {"day_of_week": 9, "hour": 10}, db, user)

    def broken(day, hour):
        raise RuntimeError("model missing")

    monkeypatch.setattr(ml_engine, "predict_load", broken)
    assert "error" in assistant.run_tool("get_load_forecast", {"day_of_week": 1, "hour": 10}, db, user)


# ----------------------------------------------------------- HTTP client
def test_call_llm_sends_the_key_in_a_header(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    seen = {}

    def fake_post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, json=json)
        return httpx.Response(200, json={"candidates": []})

    monkeypatch.setattr(httpx, "post", fake_post)
    assert assistant.call_llm({"contents": []}) == {"candidates": []}
    assert "gemini-test-model:generateContent" in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == "test-key"
    assert "test-key" not in seen["url"]  # never put the key in the URL


def test_call_llm_error_handling(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429, text="quota exceeded"))
    with pytest.raises(assistant.AssistantError):
        assistant.call_llm({})

    def timeout(*a, **k):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(assistant.AssistantError):
        assistant.call_llm({})

    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(assistant.AssistantNotConfigured):
        assistant.call_llm({})
