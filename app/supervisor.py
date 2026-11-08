"""What the installed app does behind the page while it gets ready (V1.1_PLAN P3).

The launcher serves the app first and hands this the slow part: download what the chosen mode
needs, start its model servers, and on a computer that will hear answers on the CPU, check that
it is fast enough. The setup page reads `status()`; nothing here blocks a request.

Run from source (`uvicorn api.main:app`) there is no supervisor, and the page says how to fetch
and start things by hand instead.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from app import download, servers, settings

# A mode cannot work without these; anything else that fails leaves a warning, not a stop.
REQUIRED = {"local": {download.LOCAL, download.CUDA}, "cloud": set()}


def is_set_up(s: dict | None = None) -> bool:
    """First run has chosen a mode, or this is a 1.0 install whose local models are all in place
    and which should never be sent to a setup page it did not need."""
    s = s or settings.load()
    return bool(s["setup_done"]) or download.ready(download.groups_for("local"))


def option_sizes(gpu: dict | None) -> dict[str, int]:
    """Bytes still to download for each first-run choice, so the page can say before asking."""
    def todo(mode: str, hearing: bool) -> int:
        return sum(i.size for i in download.missing(download.groups_for(mode, hearing, gpu)))
    return {"local": todo("local", True), "cloud_spoken": todo("cloud", True),
            "cloud_typed": todo("cloud", False)}


class Supervisor:
    def __init__(self, log_path: Path, sources: list[Path] = (), say=print):
        self.log_path, self.sources, self.say_out = log_path, list(sources), say
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.started: servers.Started = []
        self.state: dict = {"phase": "idle", "mode": None, "items": [], "lines": [],
                            "warnings": [], "error": None, "hearing_speed": None,
                            "voice_download": None}
        self.voice_thread: threading.Thread | None = None

    # -------------------------------------------------------------- reading
    # The API holds this object but never imports this module, so the download manifest stays
    # out of everything the interview path loads (tests/test_nfr.py).
    def is_set_up(self) -> bool:
        return is_set_up()

    def option_sizes(self, gpu: dict | None) -> dict[str, int]:
        return option_sizes(gpu)

    def status(self) -> dict:
        with self.lock:
            return {**self.state, "items": [dict(i) for i in self.state["items"]],
                    "lines": list(self.state["lines"][-12:]),
                    "warnings": list(self.state["warnings"]),
                    "voice_download": dict(self.state["voice_download"] or {}) or None}

    def busy(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    # -------------------------------------------------------------- reporting
    def _say(self, line: str) -> None:
        self.say_out(line)
        with self.lock:
            self.state["lines"].append(line)

    def _tick(self, item: download.Item, got: int) -> None:
        with self.lock:
            for row in self.state["items"]:
                if row["name"] == item.name:
                    row["got"], row["state"] = got, "downloading"

    def _set(self, **kw) -> None:
        with self.lock:
            self.state.update(kw)

    # -------------------------------------------------------------- doing
    def begin(self, mode: str, hearing: bool, gpu: dict | None) -> bool:
        """Get `mode` ready in the background. False when a run is already going: the next
        change waits for it rather than racing it over the same files."""
        if self.busy():
            return False
        self.thread = threading.Thread(target=self._run, args=(mode, hearing, gpu), daemon=True)
        self.thread.start()
        return True

    def _run(self, mode: str, hearing: bool, gpu: dict | None) -> None:
        groups = download.groups_for(mode, hearing, gpu)
        todo = download.missing(groups)
        self._set(phase="downloading" if todo else "starting", mode=mode, error=None,
                  warnings=[], items=[{"name": i.name, "size": i.size, "got": 0,
                                       "state": "waiting", "group": i.group} for i in todo])
        failures = download.fetch(groups, self.sources, say=self._say, tick=self._tick)
        failed = {f.split(":", 1)[0] for f in failures}
        with self.lock:
            for row in self.state["items"]:
                row["state"] = "failed" if row["name"] in failed else "done"
                if row["state"] == "done":
                    row["got"] = row["size"]
        fatal = [i for i in todo if i.name in failed and i.group in REQUIRED.get(mode, set())]
        if fatal:
            self._set(phase="failed", error="%s did not download. Check the connection and start "
                      "Mockingbird again; it fetches only what is missing."
                      % ", ".join(i.name for i in fatal))
            return
        if failures:
            self._set(warnings=failures)

        self._set(phase="starting")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "ab") as log:
            started, why = servers.start(log=log, servers=servers.plan(mode, hearing, gpu))
        self.started += started
        if why:
            self._set(phase="failed", error="%s. A 6 GB NVIDIA GPU is needed for the model on "
                      "this computer; another program holding the GPU is the usual cause." % why)
            return

        speed = None
        if mode == "cloud" and hearing and not download.voice_on_gpu(gpu):
            self._set(phase="checking")
            speed = self._check_hearing()
        settings.save({"hearing_speed": speed})
        self._set(phase="ready", hearing_speed=speed)

    def _check_hearing(self) -> float | None:
        from app import lfm3
        if lfm3.health():
            self._say("hearing check: the voice server is not running, so answers are typed")
            return 0.0
        try:
            speed = lfm3.hearing_speed()
        except (OSError, RuntimeError, ValueError) as e:
            self._say("hearing check failed (%s), so answers are typed" % e)
            return 0.0
        verdict = ("fast enough to speak answers" if speed >= lfm3.HEARING_MIN_SPEED
                   else "too slow, so answers are typed")
        self._say("hearing check: %.1fx real time, %s" % (speed, verdict))
        return speed

    def fetch_voice(self, voice_id: str) -> bool:
        """Download one Piper voice in the background, for the picker (P4). One at a time, and
        independent of setup: a 67 MB voice should not wait behind a 5 GB model."""
        if self.voice_thread and self.voice_thread.is_alive():
            return False
        group = download.PIPER + voice_id.split(":", 1)[-1]
        todo = download.missing([group])
        if not todo:
            return True
        item = todo[0]
        self._set(voice_download={"id": voice_id, "got": 0, "size": item.size,
                                  "state": "downloading", "error": None})

        def run() -> None:
            def tick(_item, got):
                with self.lock:
                    self.state["voice_download"]["got"] = got
            failures = download.fetch([group], self.sources, say=self._say, tick=tick)
            with self.lock:
                vd = self.state["voice_download"]
                vd["state"] = "failed" if failures else "done"
                vd["error"] = failures[0] if failures else None
                if not failures:
                    vd["got"] = vd["size"]

        self.voice_thread = threading.Thread(target=run, daemon=True)
        self.voice_thread.start()
        return True

    def wait(self, timeout: float | None = None) -> None:
        if self.thread:
            self.thread.join(timeout)

    def stop(self) -> None:
        servers.stop(self.started)
        deadline = time.monotonic() + 5
        while any(p.poll() is None for _, p in self.started) and time.monotonic() < deadline:
            time.sleep(0.1)
