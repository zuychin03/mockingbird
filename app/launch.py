"""Start Mockingbird from an install: serve the app, open it, and get the chosen mode ready
behind it. The Start-menu shortcut runs `python -m app.launch`.

The app comes up first (V1.1_PLAN P3). A fresh install opens on the setup page, which asks
whether the interviewer runs on this computer or in the cloud before anything is downloaded;
an install that has chosen, including any 1.0 install with its models in place, starts getting
ready at once. `app/supervisor.py` does the downloading and starting, and the page shows it.

The window it runs in is the off switch. The servers share its console, so closing it stops
them too instead of leaving four gigabytes of GPU memory held by processes nobody can see.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8000
URL = "http://127.0.0.1:%d/" % PORT
LOGS = ROOT / "data" / "logs"


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


def _open_when_ready(path: str = "") -> None:
    for _ in range(120):
        if _answers(URL + "api/storage"):
            webbrowser.open(URL + path)
            return
        time.sleep(0.5)


def _warm_voice(sup) -> None:
    """The first render took 1.9 s to first audio on a fresh LFM3 server and 3.7 s on an unloaded
    Piper voice, against 0.5 s and 0.2 s after; spend it once the servers are up, on whichever
    voice Settings chose, while the candidate is still reading the plan."""
    from app import speech
    sup.wait()
    if sup.status()["phase"] != "ready":
        return
    try:
        speech.engine().warm()
    except (RuntimeError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    browser = "--no-browser" not in (sys.argv[1:] if argv is None else argv)
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetConsoleTitleW("Mockingbird")
    if _answers(URL + "api/storage"):
        print("Mockingbird is already running at %s." % URL)
        if browser:
            webbrowser.open(URL)
        return 0

    from app import hardware, settings, supervisor

    LOGS.mkdir(parents=True, exist_ok=True)
    sup = supervisor.Supervisor(LOGS / "servers.log")
    s = settings.load()
    first = ""
    if supervisor.is_set_up(s):
        if not s["setup_done"]:
            # A 1.0 install: it chose the local model by installing it.
            s = settings.save({"setup_done": True, "mode": "local"})
        print("\nGetting ready (model server output goes to %s)." % (LOGS / "servers.log"))
        sup.begin(s["mode"], s["hearing"], hardware.nvidia())
    else:
        first = "setup"
        print("\nFirst start: choose how the interviewer runs on the page that opens.")
    try:
        import uvicorn

        from api import main as api

        api.SUPERVISOR = sup
        threading.Thread(target=_warm_voice, args=(sup,), daemon=True).start()
        print("\nMockingbird is at %s. Close this window to stop it." % URL)
        if browser:
            threading.Thread(target=_open_when_ready, args=(first,), daemon=True).start()
        # 127.0.0.1, never localhost: localhost resolves to IPv6 first and costs ~2 s a call.
        uvicorn.run(api.app, host="127.0.0.1", port=PORT, log_level="warning")
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        sup.stop()


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
