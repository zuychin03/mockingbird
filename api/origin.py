"""Which requests come from Mockingbird's own page (V1.1_PLAN P2).

The app listens on 127.0.0.1, and any web page open in the same browser can still send it a
request: delete an interview, change the provider, store a key, or open the microphone socket.
A browser always says where such a request came from, so anything that changes state is refused
when that origin is another site. A request with no Origin at all is a tool, a test or the
launcher, never a cross-site page, and is let through.
"""

from __future__ import annotations

import urllib.parse

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def foreign(origin: str | None, host: str | None = None) -> bool:
    if origin is None:
        return False
    if origin == "null":
        # Sandboxed frames and file:// pages; never this app.
        return True
    parts = urllib.parse.urlsplit(origin)
    if parts.hostname in LOOPBACK:
        # The built page is served from here; the dev server proxies from another port.
        return False
    return not (host and parts.netloc == host)
