"""UTF-8 stdout for the command-line tools.

The Windows console defaults to cp1252 and the model emits typographic punctuation -- an
em dash, a non-breaking hyphen (U+2011) -- so `print` of a spoken line raises
UnicodeEncodeError and kills the harness mid-session. The turn is already saved by then, so
the crash loses no data, but it does end the run.
"""

from __future__ import annotations

import sys


def utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
