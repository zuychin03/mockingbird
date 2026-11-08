"""Running without a GPU (V1.1_PLAN P3): what each mode downloads and starts, the hearing check,
the supervisor behind the setup page, and the first-run API."""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import download, hardware, lfm3, listen, servers, settings, supervisor  # noqa: E402

GPU6 = {"name": "NVIDIA GeForce RTX 3060 Laptop GPU", "memory_mib": 6144}
GPU4 = {"name": "NVIDIA GeForce GTX 1650", "memory_mib": 4096}
GPU2 = {"name": "NVIDIA GeForce MX250", "memory_mib": 2048}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    for var in ("MOCKINGBIRD_PROVIDER", "MOCKINGBIRD_MODEL", "MOCKINGBIRD_API_KEY",
                "MOCKINGBIRD_LLAMA_SERVER", "MOCKINGBIRD_FORCE_CPU"):
        monkeypatch.delenv(var, raising=False)
    hardware.nvidia.cache_clear()
    yield
    # Some tests replace `nvidia` with a plain function, still in place when this runs.
    getattr(hardware.nvidia, "cache_clear", lambda: None)()


# ------------------------------------------------------------------ hardware
def test_the_first_card_is_read_from_nvidia_smi():
    assert hardware.parse("NVIDIA GeForce RTX 3060 Laptop GPU, 6144\n") == GPU6
    assert hardware.parse("garbage\n") is None


def test_a_6_gb_card_runs_the_model_and_anything_smaller_does_not():
    assert hardware.can_run_local(GPU6)
    assert not hardware.can_run_local(GPU4) and not hardware.can_run_local(None)


def test_the_no_gpu_path_can_be_tried_on_a_machine_with_one(monkeypatch):
    monkeypatch.setenv("MOCKINGBIRD_FORCE_CPU", "1")
    assert hardware.nvidia() is None and hardware.describe()["forced_cpu"] is True


# ------------------------------------------------------------------ what each mode needs
def test_each_mode_downloads_only_what_it_runs():
    L, V, C, G, P = download.LOCAL, download.VOICE, download.CORE, download.CUDA, download.CPU
    assert download.groups_for("local") == [C, L, V, G]
    K = download.PIPER + "kristin"
    assert download.groups_for("cloud", True, None) == [C, P, V, K]
    assert download.groups_for("cloud", False, None) == [C, P]
    assert download.groups_for("cloud", False, GPU4) == [C, G, V], "a card that holds the voice speaks"
    assert download.groups_for("cloud", True, GPU2) == [C, P, V, K]


def test_cloud_without_a_gpu_skips_the_interviewer_and_the_cuda_build(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "ROOT", tmp_path)
    names = {i.name for i in download.missing(download.groups_for("cloud", False, None))}
    assert names == {"embedder", "pause detector", "llama.cpp %s, CPU build" % download.LLAMA_BUILD}
    typed = sum(i.size for i in download.missing(download.groups_for("cloud", False, None)))
    assert typed < 60_000_000, "a typed-answer cloud install downloads tens of MB, not gigabytes"
    assert "language model" in {i.name for i in download.missing()}, "the default is still 1.0's"


def _tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_a_voice_package_unpacks_and_a_hostile_one_is_refused(tmp_path):
    good = tmp_path / "voice.tar.bz2"
    good.write_bytes(_tar({"vits-piper-x/model.onnx": b"m", "vits-piper-x/tokens.txt": b"t"}))
    download.unpack(good, tmp_path / "out")
    assert (tmp_path / "out" / "vits-piper-x" / "tokens.txt").read_bytes() == b"t"
    bad = tmp_path / "bad.tar.bz2"
    bad.write_bytes(_tar({"../escaped.txt": b"x"}))
    with pytest.raises(tarfile.TarError):
        download.unpack(bad, tmp_path / "out2")
    assert not (tmp_path / "escaped.txt").exists()


# ------------------------------------------------------------------ what each mode starts
def test_cloud_mode_never_starts_the_interviewer():
    assert servers.plan("local") == servers.ALL
    assert servers.plan("cloud", True, None) == (servers.VOICE_CPU, servers.EMBEDDER)
    assert servers.plan("cloud", False, None) == (servers.EMBEDDER,)
    assert servers.plan("cloud", True, GPU4) == (servers.VOICE, servers.EMBEDDER)
    assert servers.LLM not in servers.plan("cloud", True, GPU4)


def test_the_cpu_voice_stays_off_the_gpu_and_uses_the_cpu_build(tmp_path, monkeypatch):
    args = servers.VOICE_CPU.args
    assert args[args.index("-ngl") + 1] == "0" and "--no-mmproj-offload" in args
    assert "-t" not in args, "llama.cpp picks the physical cores; all logical ran 3.5x slower"
    cuda, cpu = tmp_path / "cuda" / "llama-server.exe", tmp_path / "cpu" / "llama-server.exe"
    for p in (cuda, cpu):
        p.parent.mkdir()
        p.write_bytes(b"")
    monkeypatch.setattr(servers, "CUDA_BINARY", cuda)
    monkeypatch.setattr(servers, "CPU_BINARY", cpu)
    assert servers.binary(servers.VOICE_CPU) == cpu and servers.binary(servers.EMBEDDER) == cpu
    assert servers.binary(servers.LLM) == cuda and servers.binary(servers.VOICE) == cuda
    cpu.unlink()
    assert servers.binary(servers.EMBEDDER) == cuda, "a 1.0 install has only the CUDA build"


# ------------------------------------------------------------------ the hearing check
class Hears:
    def __init__(self, text="I led the move", delay=0.0):
        self.text, self.delay, self.calls = text, delay, 0

    def transcribe(self, samples, rate):
        import time
        self.calls += 1
        time.sleep(self.delay)
        return self.text


def test_the_hearing_check_warms_up_then_times_the_shipped_clip():
    ears = Hears(delay=0.05)
    speed = lfm3.hearing_speed(ears)
    assert ears.calls == 2 and speed > 20, "8 s of clip read in ~0.05 s"
    assert lfm3.CHECK_CLIP.exists() and lfm3.CHECK_CLIP.stat().st_size < 400_000
    assert lfm3.hearing_speed(Hears(text="")) == 0.0, "nothing heard counts as too slow"


def test_spoken_answers_are_refused_with_the_reason_only_in_cloud_mode():
    assert settings.hearing_refused() is None
    settings.save({"mode": "cloud", "vendor": "groq", "model": "qwen/qwen3.8-27b",
                   "hearing_speed": 0.8})
    why = settings.hearing_refused()
    assert "0.8x" in why and "typed" in why
    assert isinstance(listen.engine(), listen.Refused) and listen.engine().available() == why
    settings.save({"hearing_speed": 2.4})
    assert settings.hearing_refused() is None
    settings.save({"hearing": False})
    assert "turned off" in settings.hearing_refused()
    settings.save({"mode": "local"})
    assert settings.hearing_refused() is None, "locally the voice runs on the GPU"


# ------------------------------------------------------------------ the supervisor
@pytest.fixture()
def quiet(monkeypatch, tmp_path):
    calls = {}

    def fake_fetch(groups, sources=(), say=print, tick=None):
        calls["groups"] = groups
        return calls.get("failures", [])

    def fake_start(log=None, servers=()):
        calls["servers"] = servers
        return [], calls.get("why")

    monkeypatch.setattr(download, "fetch", fake_fetch)
    monkeypatch.setattr(download, "missing", lambda groups=None: [])
    monkeypatch.setattr(servers, "start", fake_start)
    monkeypatch.setattr(lfm3, "health", lambda base=lfm3.BASE: None)
    monkeypatch.setattr(lfm3, "hearing_speed", lambda *a, **k: 2.4)
    return calls, supervisor.Supervisor(tmp_path / "logs" / "servers.log", say=lambda s: None)


def test_cloud_on_a_cpu_downloads_starts_checks_hearing_and_records_it(quiet):
    calls, sup = quiet
    assert sup.begin("cloud", True, None)
    sup.wait(10)
    assert sup.status()["phase"] == "ready" and sup.status()["hearing_speed"] == 2.4
    assert calls["groups"] == [download.CORE, download.CPU, download.VOICE,
                               download.PIPER + "kristin"]
    assert calls["servers"] == (servers.VOICE_CPU, servers.EMBEDDER)
    assert settings.load()["hearing_speed"] == 2.4


def test_a_voice_on_the_gpu_needs_no_hearing_check(quiet):
    calls, sup = quiet
    settings.save({"hearing_speed": 0.5})
    sup.begin("local", True, GPU6)
    sup.wait(10)
    assert sup.status()["phase"] == "ready" and settings.load()["hearing_speed"] is None


def test_a_missing_interviewer_stops_local_mode_and_says_what_to_do(quiet, monkeypatch):
    calls, sup = quiet
    item = next(i for i in download.ITEMS if i.group == download.LOCAL)
    monkeypatch.setattr(download, "missing", lambda groups=None: [item])
    calls["failures"] = ["%s: download failed" % item.name]
    sup.begin("local", True, GPU6)
    sup.wait(10)
    st = sup.status()
    assert st["phase"] == "failed" and "start Mockingbird again" in st["error"]
    assert st["items"][0]["state"] == "failed"


def test_a_missing_embedder_only_warns(quiet, monkeypatch):
    calls, sup = quiet
    item = next(i for i in download.ITEMS if i.name == "embedder")
    monkeypatch.setattr(download, "missing", lambda groups=None: [item])
    calls["failures"] = ["embedder: download failed"]
    sup.begin("cloud", False, None)
    sup.wait(10)
    assert sup.status()["phase"] == "ready" and sup.status()["warnings"]


def test_a_1_0_install_with_its_models_is_already_set_up(monkeypatch):
    monkeypatch.setattr(download, "ready", lambda groups: True)
    assert supervisor.is_set_up()
    monkeypatch.setattr(download, "ready", lambda groups: False)
    assert not supervisor.is_set_up()
    settings.save({"setup_done": True})
    assert supervisor.is_set_up()


# ------------------------------------------------------------------ the first-run API
class FakeSupervisor:
    def __init__(self):
        self.began = []

    def is_set_up(self):
        return settings.load()["setup_done"]

    def option_sizes(self, gpu):
        return {"local": 5_000_000_000, "cloud_spoken": 2_440_000_000, "cloud_typed": 52_000_000}

    def status(self):
        return {"phase": "idle", "items": [], "lines": [], "warnings": []}

    def begin(self, mode, hearing, gpu):
        self.began.append((mode, hearing))
        return True


@pytest.fixture()
def api_client(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from api import main as api
    monkeypatch.setattr(api, "LIVE", tmp_path / "live.json")
    return TestClient(api.app), api


def test_a_copy_run_from_source_is_never_sent_to_setup(api_client):
    c, api = api_client
    assert api.SUPERVISOR is None
    got = c.get("/api/setup").json()
    assert got["managed"] is False and got["set_up"] is True
    assert c.post("/api/setup", json={"mode": "cloud"}).status_code == 409


def test_first_run_chooses_cloud_preselects_the_measured_model_and_starts(api_client,
                                                                         monkeypatch):
    c, api = api_client
    fake = FakeSupervisor()
    monkeypatch.setattr(api, "SUPERVISOR", fake)
    monkeypatch.setattr(hardware, "nvidia", lambda: None)
    view = c.get("/api/setup").json()
    assert view["managed"] and not view["set_up"] and view["sizes"]["cloud_typed"] < 10**8
    got = c.post("/api/setup", json={"mode": "cloud", "hearing": False}).json()
    s = settings.load()
    assert got["set_up"] and s["setup_done"] and s["mode"] == "cloud" and s["hearing"] is False
    assert (s["vendor"], s["model"]) == ("groq", "qwen/qwen3.8-27b")
    assert s["ack_version"] == 0, "the acknowledgement is still the person's to give"
    assert fake.began == [("cloud", False)]


def test_local_is_refused_without_a_card_that_can_hold_it(api_client, monkeypatch):
    c, api = api_client
    monkeypatch.setattr(api, "SUPERVISOR", FakeSupervisor())
    monkeypatch.setattr(hardware, "nvidia", lambda: GPU4)
    got = c.post("/api/setup", json={"mode": "local"})
    assert got.status_code == 400 and "6 GB" in got.json()["detail"]


def test_switching_mode_in_settings_gets_the_new_mode_ready(api_client, monkeypatch):
    c, api = api_client
    fake = FakeSupervisor()
    monkeypatch.setattr(api, "SUPERVISOR", fake)
    monkeypatch.setattr(hardware, "nvidia", lambda: None)
    c.put("/api/settings", json={"mode": "cloud", "vendor": "groq", "model": "qwen/qwen3.8-27b"})
    assert fake.began == [("cloud", True)]
    c.put("/api/settings", json={"model": "qwen/qwen3.8-27b"})
    assert fake.began == [("cloud", True)], "a model change needs no new downloads"
