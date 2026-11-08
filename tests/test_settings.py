"""Settings, the API key and the honesty around cloud mode (V1.1_PLAN P2)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import provider, secret, session, settings  # noqa: E402
from app.provider import CloudClient, Completion, Profile, ProviderError  # noqa: E402
from app.runner import Runner  # noqa: E402
from test_runner import PLAN, d  # noqa: E402

KEY = "gsk_0123456789abcdefghijklmnopqrstuvwxyz0123456789ABCD"
windows = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.setenv("MOCKINGBIRD_KEY_FILE", str(tmp_path / "provider.key"))
    for var in ("MOCKINGBIRD_PROVIDER", "MOCKINGBIRD_MODEL", "MOCKINGBIRD_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def _cloud_settings(ack=True):
    settings.save({"mode": "cloud", "vendor": "groq", "model": "qwen/qwen3.8-27b",
                   "ack_version": settings.ACK_VERSION if ack else 0})


# ------------------------------------------------------------------ settings
def test_no_file_is_exactly_1_0():
    s = settings.load()
    assert s["mode"] == "local" and not settings.acknowledged(s)
    assert isinstance(provider.current(), provider.LlamaServer)


def test_cloud_needs_a_vendor_and_a_model():
    with pytest.raises(settings.SettingsError, match="provider"):
        settings.save({"mode": "cloud"})
    with pytest.raises(settings.SettingsError, match="model"):
        settings.save({"mode": "cloud", "vendor": "groq", "model": "  "})
    with pytest.raises(settings.SettingsError, match="unknown setting"):
        settings.save({"api_key": KEY})
    s = settings.save({"mode": "cloud", "vendor": "groq", "model": " qwen/qwen3.8-27b "})
    assert s["model"] == "qwen/qwen3.8-27b"
    assert json.loads(settings.PATH.read_text())["vendor"] == "groq"


def test_the_settings_file_never_holds_the_key():
    _cloud_settings()
    assert "key" not in settings.PATH.read_text().lower().replace("ack_version", "")


# ------------------------------------------------------------------ the key
@windows
def test_the_key_is_stored_encrypted_and_shown_only_by_its_last_four():
    secret.save(KEY)
    raw = secret.path().read_bytes()
    assert KEY.encode() not in raw and KEY[-8:].encode() not in raw
    assert secret.load() == KEY
    assert secret.status() == {"set": True, "last4": KEY[-4:], "source": "stored"}
    secret.clear()
    assert secret.status() == {"set": False, "last4": None, "source": None}


def test_the_environment_key_wins_and_says_so(monkeypatch):
    monkeypatch.setenv("MOCKINGBIRD_API_KEY", KEY)
    assert secret.load() == KEY and secret.status()["source"] == "environment"


@pytest.mark.parametrize("bad", ["", "   ", "has a space in it", "x" * 600])
def test_something_that_is_not_a_key_is_refused(bad):
    with pytest.raises(secret.SecretError):
        secret.save(bad)


def test_a_checkout_inside_onedrive_keeps_the_key_out_of_it(monkeypatch, tmp_path):
    monkeypatch.delenv("MOCKINGBIRD_KEY_FILE")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("OneDrive", str(secret.ROOT.parent))
    assert secret.path() == tmp_path / "local" / "Mockingbird" / secret.NAME
    monkeypatch.setenv("OneDrive", str(tmp_path / "elsewhere"))
    for var in ("OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(var, raising=False)
    assert secret.path() == secret.ROOT / "secrets" / secret.NAME


# ------------------------------------------------------------------ choosing the provider
def test_cloud_from_settings_waits_for_the_acknowledgement_then_the_key(monkeypatch):
    _cloud_settings(ack=False)
    with pytest.raises(provider.SetupRequired, match="acknowledged"):
        provider.current()
    _cloud_settings(ack=True)
    with pytest.raises(provider.SetupRequired, match="API key"):
        provider.current()
    monkeypatch.setenv("MOCKINGBIRD_API_KEY", KEY)
    c = provider.current()
    assert isinstance(c, CloudClient) and c.profile.measured and c.profile.reasoning == "none"


def test_a_session_keeps_the_provider_it_started_on(monkeypatch):
    monkeypatch.setenv("MOCKINGBIRD_API_KEY", KEY)
    assert isinstance(provider.for_session(None), provider.LlamaServer)
    assert isinstance(provider.for_session({"mode": "local"}), provider.LlamaServer)
    c = provider.for_session({"mode": "cloud", "vendor": "groq", "model": "qwen/qwen3.8-27b"})
    assert isinstance(c, CloudClient) and c.model == "qwen/qwen3.8-27b"


def test_configured_describes_the_choice_without_reading_the_key():
    assert provider.configured()["mode"] == "local"
    _cloud_settings()
    got = provider.configured()
    assert got == {"mode": "cloud", "vendor": "groq", "label": "Groq", "host": "api.groq.com",
                   "model": "qwen/qwen3.8-27b", "measured": True}


class Billed:
    async def complete(self, *a, **k):
        return Completion(text="{}", prompt_tokens=700, decode_tokens=30, cost_usd=0.0001)


def test_metering_counts_every_call_into_the_session_record():
    usage = {}
    m = provider.Metered(Billed(), usage)
    for _ in range(3):
        asyncio.run(m.complete("s", "u"))
    assert usage == {"calls": 3, "prompt_tokens": 2100, "completion_tokens": 90,
                     "cost_usd": 0.0003}
    assert provider.is_local(m)
    c = provider.Metered(CloudClient(Profile("groq", "m"), KEY))
    assert not provider.is_local(c) and provider.describe(c)["vendor"] == "groq"


# ------------------------------------------------------------------ a failed vendor call
class Failing:
    """Fails every decision; summaries succeed, as they did in the P1 run that died."""

    def __init__(self):
        self.calls = 0

    async def complete(self, system, user, schema=None, **k):
        if schema is None:
            return Completion(text="a summary")
        self.calls += 1
        raise ProviderError("Groq did not answer (TimeoutError: timed out)")


def test_a_failed_vendor_call_degrades_to_the_scripted_line_instead_of_an_error(tmp_path):
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    p = Failing()
    r = Runner(p, PLAN, state)
    asyncio.run(r.ask())
    out = asyncio.run(r.submit("an answer"))
    assert out.act == "probe" and out.spoken.text.strip()
    assert p.calls == 2, "one retry, as for a malformed reply"
    rec = json.loads((state.dir / "decisions.jsonl").read_text().splitlines()[-1])
    assert "Groq did not answer" in rec["provider_error"]


def test_a_cloud_session_never_writes_the_key_anywhere(tmp_path, monkeypatch):
    class Reply:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.body).encode()

    def fake(req, timeout=None):
        wanted = json.loads(req.data)
        content = json.dumps(d("advance", "Thanks.")) if wanted.get("response_format") else "ok"
        return Reply({"choices": [{"message": {"content": content}}],
                      "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    monkeypatch.setattr(provider.urllib.request, "urlopen", fake)
    session.SESSIONS = tmp_path / "sessions"
    client = CloudClient(provider.profile_for("groq", "qwen/qwen3.8-27b"), KEY)
    state = session.new_session(PLAN, {"provider": provider.describe(client)})
    r = Runner(provider.Metered(client, state.usage), PLAN, state)
    asyncio.run(r.ask())
    asyncio.run(r.submit("the whole answer"))
    session.checkpoint(state)
    for f in state.dir.rglob("*"):
        if f.is_file():
            assert KEY not in f.read_text(encoding="utf-8", errors="replace"), f.name
    meta = json.loads((state.dir / "session.json").read_text())
    assert meta["usage"]["calls"] >= 1 and meta["provenance"]["provider"]["vendor"] == "groq"


# ------------------------------------------------------------------ the HTTP surface
@pytest.fixture()
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from api import main as api
    monkeypatch.setattr(api, "LIVE", tmp_path / "live.json")
    monkeypatch.setattr(api, "SESSIONS", tmp_path / "sessions")
    (tmp_path / "sessions").mkdir(exist_ok=True)
    return TestClient(api.app), api


HEADER = {"x-mockingbird": "1"}


@windows
def test_the_settings_page_sees_whether_a_key_is_set_and_never_the_key(client):
    c, _ = client
    assert c.put("/api/settings/key", json={"key": KEY}).status_code == 403
    got = c.put("/api/settings/key", json={"key": KEY}, headers=HEADER)
    assert got.status_code == 200 and KEY not in got.text
    assert got.json()["key"] == {"set": True, "last4": KEY[-4:], "source": "stored"}
    assert KEY not in c.get("/api/settings").text
    assert c.delete("/api/settings/key", headers=HEADER).json()["key"]["set"] is False


def test_settings_round_trip_and_show_what_cloud_mode_sends(client):
    c, _ = client
    view = c.get("/api/settings").json()
    assert view["settings"]["mode"] == "local" and "job description" in view["ack"]["text"]
    assert any(m["model"] == "qwen/qwen3.8-27b" for m in view["measured"])
    got = c.put("/api/settings", json={"mode": "cloud", "vendor": "groq",
                                        "model": "qwen/qwen3.8-27b",
                                        "ack_version": settings.ACK_VERSION})
    assert got.status_code == 200 and got.json()["ack"]["current"] is True
    assert c.put("/api/settings", json={"mode": "cloud", "vendor": "acme"}).status_code == 400


def test_nothing_changes_while_an_interview_is_running(client, tmp_path):
    c, api = client
    api.LIVE.write_text(json.dumps({"session_id": "x", "status": "running"}))
    assert c.put("/api/settings", json={"mode": "local"}).status_code == 409
    assert c.get("/api/settings").json()["locked"] is True
    api.LIVE.write_text(json.dumps({"session_id": "x", "status": "complete"}))
    assert c.put("/api/settings", json={"mode": "local"}).status_code == 200


@pytest.mark.parametrize("origin,allowed", [
    (None, True), ("http://127.0.0.1:8000", True), ("http://localhost:5173", True),
    ("https://evil.example", False), ("null", False)])
def test_another_site_cannot_change_anything(client, origin, allowed):
    c, _ = client
    headers = {} if origin is None else {"origin": origin}
    got = c.put("/api/settings", json={"mode": "local"}, headers=headers)
    assert (got.status_code != 403) is allowed
    assert c.get("/api/settings", headers=headers).status_code == 200


def test_cloud_mode_without_its_acknowledgement_is_a_settings_problem_not_an_outage(client):
    c, _ = client
    _cloud_settings(ack=False)
    got = c.post("/api/session/start", json={"plan_path": "config/interview_swe_general.json"})
    assert got.status_code == 409 and "Settings" in got.json()["detail"]


def test_a_local_interview_is_not_scored_in_the_cloud_without_asking(client, monkeypatch):
    c, api = client
    d_ = api.SESSIONS / "s1"
    d_.mkdir()
    (d_ / "session.json").write_text(json.dumps({
        "session_id": "s1", "plan_snapshot": {"phases": []}, "questions": [],
        "provenance": {"provider": {"mode": "local", "vendor": None}}}))
    _cloud_settings()
    monkeypatch.setenv("MOCKINGBIRD_API_KEY", KEY)
    got = c.get("/api/sessions/s1/report?provider=current")
    assert got.status_code == 409 and "Groq" in got.json()["detail"]
    assert c.get("/api/sessions/s1/report?provider=current&ack=true").status_code == 200


def test_cloud_mode_in_settings_changes_the_claim_and_names_the_vendor(client):
    c, _ = client
    assert c.get("/api/storage").json()["answers_leave"] is False
    _cloud_settings()
    got = c.get("/api/storage").json()
    assert got["answers_leave"] is True and got["leaves_machine"] is True
    assert got["provider"]["vendor"] == "Groq" and got["provider"]["host"] == "api.groq.com"
