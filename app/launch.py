"""Start Mockingbird from an install: fetch anything missing, start the model servers, serve the
app and open it. The Start-menu shortcut runs `python -m app.launch`.

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


def _open_when_ready() -> None:
    for _ in range(120):
        if _answers(URL + "api/storage"):
            webbrowser.open(URL)
            return
        time.sleep(0.5)


def _warm_voice() -> None:
    """The first render on a fresh voice server took 1.9 s to first audio against 0.5 s after;
    spend it now, while the candidate is still reading the plan."""
    from app import lfm3
    try:
        lfm3.Speaker().warm()
    except RuntimeError:
        pass


def _hold(message: str) -> int:
    """A double-clicked window closes on exit; keep it open long enough to be read."""
    print("\n" + message)
    try:
        input("Press Enter to close.")
    except EOFError:
        pass
    return 1


def main(argv: list[str] | None = None) -> int:
    browser = "--no-browser" not in (sys.argv[1:] if argv is None else argv)
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetConsoleTitleW("Mockingbird")
    if _answers(URL + "api/storage"):
        print("Mockingbird is already running at %s." % URL)
        if browser:
            webbrowser.open(URL)
        return 0

    from app import download, servers

    failures = download.fetch_all()
    if any(f.startswith(("language model", "llama.cpp", "CUDA")) for f in failures):
        return _hold("Mockingbird cannot start without its language model and runtime. "
                     "Check the connection and start it again; it fetches only what is missing.")

    LOGS.mkdir(parents=True, exist_ok=True)
    print("\nStarting the model servers (their output goes to %s)." % (LOGS / "servers.log"))
    with open(LOGS / "servers.log", "ab") as log:
        started, why = servers.start(log=log)
        try:
            if why:
                return _hold("%s\nThe log above says more. A 6 GB NVIDIA GPU is needed; another "
                             "program holding the GPU is the usual cause." % why)
            import uvicorn

            from api import main as api

            threading.Thread(target=_warm_voice, daemon=True).start()

            print("\nMockingbird is at %s. Close this window to stop it." % URL)
            if browser:
                threading.Thread(target=_open_when_ready, daemon=True).start()
            # 127.0.0.1, never localhost: localhost resolves to IPv6 first and costs ~2 s a call.
            uvicorn.run(api.app, host="127.0.0.1", port=PORT, log_level="warning")
            return 0
        except KeyboardInterrupt:
            return 0
        finally:
            servers.stop(started)


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
