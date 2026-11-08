"""The same interview lines in every voice that can speak here, for choosing by ear (P4).

    python tools/voice_audition.py

Writes data/voice/audition_1.1/<voice>/NN.wav and data/voice/audition_1.1/index.html (open it in
a browser). LFM3 voices need the voice server (`python -m app.servers`); Piper voices need
`python -m app.download --voice kristin norman hfc_female ryan`.
"""

from __future__ import annotations

import html
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import lfm3, piper, speech  # noqa: E402

OUT = ROOT / "data" / "voice" / "audition_1.1"
# Scripted questions, follow-ups and the fixed lines, as the interviewer actually says them.
LINES = [
    "To start, tell me a bit about yourself and what you're working on at the moment.",
    "Tell me about a time you disagreed with a technical decision on your team.",
    "What did you measure first?",
    "How did that land?",
    "What did you personally do to justify that choice to the team?",
    "Walk me through how you'd design a rate limiter for a public API. Take a minute first if "
    "you like, and tell me when you're ready to start.",
    "What breaks first when this is under real load?",
    "Noted. Let's finish this one first.",
    "Describe a failure that reached users before anyone on the team noticed it.",
    "That's everything I had. Do you have any questions for me?",
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rendered, skipped = [], []
    for v in speech.voices():
        if v["engine"] == "lfm3":
            if lfm3.health():
                skipped.append((v["label"], "the voice server is not running"))
                continue
            s = lfm3.Speaker(v["voice"])
        elif piper.installed(v["id"]):
            s = piper.Speaker(v["id"])
        else:
            skipped.append((v["label"], "not downloaded"))
            continue
        s.warm()
        d = OUT / v["id"].replace(":", "_")
        d.mkdir(exist_ok=True)
        times = []
        for n, line in enumerate(LINES, 1):
            t = time.perf_counter()
            samples = s.say(line)
            times.append(time.perf_counter() - t)
            (d / ("%02d.wav" % n)).write_bytes(lfm3.wav_bytes(samples, s.rate))
        rendered.append((v, d.name, sum(times) / len(times)))
        print("%-12s %d lines, %.0f ms a line" % (v["label"], len(LINES), 1000 * rendered[-1][2]))
    head = "".join("<th>%s<br><small>%s%s</small></th>" % (
        html.escape(v["label"]), html.escape(v["engine"]),
        ", non-commercial" if v.get("noncommercial") else "") for v, _, _ in rendered)
    rows = "".join("<tr><td>%s</td>%s</tr>" % (html.escape(line), "".join(
        '<td><audio controls preload="none" src="%s/%02d.wav"></audio></td>' % (d, n)
        for _, d, _ in rendered)) for n, line in enumerate(LINES, 1))
    (OUT / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Mockingbird voice audition</title>"
        "<style>body{font:15px system-ui;margin:2rem}td,th{padding:6px 10px;border-bottom:1px "
        "solid #ddd;text-align:left;vertical-align:middle}audio{width:150px}</style>"
        "<h1>Voice audition</h1><p>The same ten lines in each voice. Skipped: %s</p>"
        "<table><tr><th>Line</th>%s</tr>%s</table>"
        % (html.escape(json.dumps(skipped)) if skipped else "none", head, rows),
        encoding="utf-8")
    print("open %s" % (OUT / "index.html"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
