"""The interviewer's voices (V1.1_PLAN P4): the catalogue, which voice actually speaks on which
computer, Piper itself, and the picker's API."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import download, hardware, lfm3, piper, settings, speech, supervisor  # noqa: E402

PIPER_IDS = {"piper:kristin", "piper:norman", "piper:hfc_female", "piper:ryan"}


def _cloud_on_cpu(monkeypatch):
    settings.save({"mode": "cloud", "vendor": "groq", "model": "qwen/qwen3.8-27b"})
    monkeypatch.setattr(hardware, "voice_on_gpu", lambda gpu=None: False)


def _installed(monkeypatch, *ids):
    monkeypatch.setattr(piper, "installed", lambda voice_id: voice_id in ids)


# ------------------------------------------------------------------ the catalogue
def test_the_six_voices_are_pinned_and_labelled_by_licence():
    voices = {v["id"]: v for v in speech.voices()}
    assert set(voices) == PIPER_IDS | {"lfm3:female", "lfm3:male"}
    for vid in PIPER_IDS:
        v = voices[vid]
        assert re.fullmatch(r"[0-9a-f]{64}", v["sha256"]) and v["size"] > 60_000_000
        assert v["url"].startswith("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                                   "tts-models/") and v["url"].endswith(v["package"] + ".tar.bz2")
    assert {vid for vid, v in voices.items() if v["noncommercial"]} == {"piper:hfc_female",
                                                                         "piper:ryan"}
    assert all("CC BY-NC-SA" in voices[v]["licence"] for v in ("piper:hfc_female", "piper:ryan"))


def test_the_downloader_and_the_picker_read_one_manifest():
    items = {i.group: i for i in download.voice_items()}
    assert set(items) == {download.PIPER + vid.split(":")[1] for vid in PIPER_IDS}
    for vid in PIPER_IDS:
        item = items[download.PIPER + vid.split(":")[1]]
        assert item.dest == "models/piper" and item.archive
        assert piper.folder(vid) == download.ROOT / "models" / "piper" / \
            item.filename.removesuffix(".tar.bz2")


def test_an_unknown_voice_cannot_be_chosen():
    with pytest.raises(settings.SettingsError, match="unknown voice"):
        settings.save({"voice": "piper:nobody"})
    assert settings.save({"voice": "piper:norman"})["voice"] == "piper:norman"


# ------------------------------------------------------------------ which voice speaks
def test_locally_lfm3_female_speaks_and_1_0_names_still_resolve():
    assert speech.default_voice() == "lfm3:female"
    assert speech.resolve() == ("lfm3:female", None)
    assert speech.resolve("male") == ("lfm3:male", None)


def test_without_a_gpu_kristin_speaks_and_a_chosen_lfm3_voice_gives_way(monkeypatch):
    _cloud_on_cpu(monkeypatch)
    _installed(monkeypatch, "piper:kristin")
    assert speech.default_voice() == "piper:kristin"
    assert speech.resolve() == ("piper:kristin", None)
    chosen, why = speech.resolve("lfm3:male")
    assert chosen == "piper:kristin" and "processor" in why
    rec = speech.describe("lfm3:male")
    assert rec["id"] == "piper:kristin" and rec["asked"] == "lfm3:male" and rec["fallback"]


def test_a_voice_not_downloaded_falls_back_and_says_so(monkeypatch):
    _installed(monkeypatch)
    chosen, why = speech.resolve("piper:ryan")
    assert chosen == "lfm3:female" and "not downloaded" in why
    _cloud_on_cpu(monkeypatch)
    chosen, why = speech.resolve("piper:ryan")
    assert chosen is None and "not downloaded" in why
    assert isinstance(speech.engine("piper:ryan"), speech.Silent)
    assert speech.engine("piper:ryan").say("Hello").size == 0


def test_the_session_record_names_the_voice_and_its_licence(monkeypatch):
    _installed(monkeypatch, "piper:hfc_female")
    settings.save({"voice": "piper:hfc_female"})
    rec = speech.describe()
    assert rec["id"] == "piper:hfc_female" and rec["noncommercial"] is True
    assert rec["engine"] == "piper/sherpa-onnx" and "CC BY-NC-SA" in rec["licence"]


# ------------------------------------------------------------------ Piper itself
@pytest.mark.skipif(not piper.installed("piper:kristin"), reason="kristin is not downloaded")
def test_kristin_speaks_float_audio_at_her_own_rate():
    pytest.importorskip("sherpa_onnx")
    s = piper.Speaker("piper:kristin")
    out = s.say("What did you measure first?")
    assert out.dtype.name == "float32" and len(out) > s.rate // 2 and s.rate == 22050


def test_a_voice_that_is_not_here_cannot_be_constructed(monkeypatch):
    _installed(monkeypatch)
    with pytest.raises(RuntimeError, match="not downloaded"):
        piper.Speaker("piper:norman")


# ------------------------------------------------------------------ fetching a voice
def test_a_voice_downloads_in_the_background_with_its_own_progress(monkeypatch, tmp_path):
    item = next(i for i in download.voice_items() if i.group == download.PIPER + "norman")
    monkeypatch.setattr(download, "missing", lambda groups=None: [item])
    seen = {}

    def fake_fetch(groups, sources=(), say=print, tick=None):
        seen["groups"] = groups
        tick(item, item.size // 2)
        return []

    monkeypatch.setattr(download, "fetch", fake_fetch)
    sup = supervisor.Supervisor(tmp_path / "log", say=lambda s: None)
    assert sup.fetch_voice("piper:norman")
    sup.voice_thread.join(5)
    vd = sup.status()["voice_download"]
    assert seen["groups"] == [download.PIPER + "norman"]
    assert vd["state"] == "done" and vd["got"] == vd["size"] == item.size


# ------------------------------------------------------------------ the picker's API
class FakeSupervisor:
    def __init__(self):
        self.fetched = []

    def fetch_voice(self, voice_id):
        self.fetched.append(voice_id)
        return True

    def status(self):
        return {"voice_download": None}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from api import main as api
    monkeypatch.setattr(api, "LIVE", tmp_path / "live.json")
    return TestClient(api.app), api


def test_the_picker_says_which_voices_cannot_speak_here_and_why(client, monkeypatch):
    c, _ = client
    _cloud_on_cpu(monkeypatch)
    _installed(monkeypatch, "piper:kristin")
    got = c.get("/api/voices").json()
    rows = {v["id"]: v for v in got["voices"]}
    assert rows["lfm3:female"]["usable"] is False and "GPU" in rows["lfm3:female"]["why_not"]
    assert rows["piper:kristin"]["installed"] and not rows["piper:ryan"]["installed"]
    assert rows["piper:ryan"]["noncommercial"] is True
    assert got["speaking"] == "piper:kristin" and got["default"] == "piper:kristin"
    assert "url" not in rows["piper:ryan"] and "sha256" not in rows["piper:ryan"]


def test_a_voice_is_downloaded_through_the_launcher_or_by_hand(client, monkeypatch):
    c, api = client
    got = c.post("/api/voices/piper:norman/download")
    assert got.status_code == 409 and "--voice norman" in got.json()["detail"]
    assert c.post("/api/voices/lfm3:female/download").status_code == 400
    assert c.post("/api/voices/piper:nobody/download").status_code == 404
    fake = FakeSupervisor()
    monkeypatch.setattr(api, "SUPERVISOR", fake)
    assert c.post("/api/voices/piper:norman/download").status_code == 200
    assert fake.fetched == ["piper:norman"]


def test_a_preview_needs_the_voice_here(client, monkeypatch):
    c, _ = client
    _installed(monkeypatch)
    assert c.get("/api/voices/piper:ryan/preview").status_code == 409
    _cloud_on_cpu(monkeypatch)
    assert c.get("/api/voices/lfm3:male/preview").status_code == 409


@pytest.mark.skipif(not piper.installed("piper:kristin"), reason="kristin is not downloaded")
def test_a_preview_is_a_wav_of_an_interview_line(client):
    pytest.importorskip("sherpa_onnx")
    c, _ = client
    got = c.get("/api/voices/piper:kristin/preview")
    assert got.status_code == 200 and got.headers["content-type"] == "audio/wav"
    assert got.content[:4] == b"RIFF" and len(got.content) > 40_000


def test_a_voice_cannot_change_during_an_interview(client):
    c, api = client
    api.LIVE.write_text(json.dumps({"session_id": "x", "status": "running"}))
    assert c.put("/api/settings", json={"voice": "piper:kristin"}).status_code == 409


def test_lfm3_still_hears_on_a_cpu_even_though_it_cannot_speak_there(monkeypatch):
    _cloud_on_cpu(monkeypatch)
    from app import listen
    assert isinstance(listen.engine(), lfm3.Listener)
