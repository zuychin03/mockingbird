"""Contrast of the design tokens, read from the stylesheet itself.

Colour is the one design decision that can be wrong in a way nobody sees until someone
cannot read the screen, and it goes wrong by drift: a token is nudged for looks and the text
it carries quietly drops under the threshold. Parsing `theme.css` rather than restating the
values here means a nudge fails this test instead of shipping.

The pairs below are the ones that actually carry text. Rules, lamps and marks are not text
and are not checked against 4.5:1.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

THEME = ROOT / "ui" / "src" / "lib" / "theme.css"

# (what it is, foreground token, background token)
TEXT_PAIRS = [
    ("document body", "ink-900", "paper-100"),
    ("document quiet", "ink-500", "paper-100"),
    ("document faint", "ink-400", "paper-100"),
    ("document faint on raised", "ink-400", "paper-050"),
    ("document signal", "tally-ink", "paper-100"),
    ("document signal on raised", "tally-ink", "paper-050"),
    ("document pending", "cue-ink", "paper-100"),
    ("studio body", "lit-100", "studio-800"),
    ("studio quiet", "lit-300", "studio-800"),
    ("studio faint", "lit-500", "studio-800"),
    ("studio faint on raised", "lit-500", "studio-750"),
    ("studio signal", "tally-lit", "studio-800"),
    ("studio signal on raised", "tally-lit", "studio-750"),
    ("studio pending", "cue", "studio-800"),
]

MIN = 4.5


def _tokens() -> dict[str, str]:
    src = THEME.read_text(encoding="utf-8")
    return {n: v for n, v in re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", src)}


def _channel(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(value: str) -> float:
    h = value.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("label,fg,bg", TEXT_PAIRS, ids=[p[0] for p in TEXT_PAIRS])
def test_every_text_pair_is_readable(label, fg, bg):
    tok = _tokens()
    for name in (fg, bg):
        assert "--" + name in tok, "theme.css no longer defines --%s" % name
    got = contrast(tok["--" + fg], tok["--" + bg])
    assert got >= MIN, "%s: --%s on --%s is %.2f:1, below %.1f" % (label, fg, bg, got, MIN)


def test_the_check_can_actually_fail():
    """A threshold test that cannot fail is decoration. Mid grey on white is 3.54:1."""
    assert contrast("#808080", "#ffffff") < MIN


def test_both_rooms_define_every_role_token():
    """A role missing from one room falls back to the other room's value, which is how a
    page ends up painting one theme's text on the other theme's ground."""
    src = THEME.read_text(encoding="utf-8")
    roles = ("--bg", "--bg-raised", "--bg-sunk", "--fg", "--fg-quiet", "--fg-faint",
             "--rule", "--rule-strong", "--signal", "--signal-bright", "--pending",
             "--shadow", "--selection")
    blocks = {}
    for room in ("[data-room='document']", "[data-room='studio']"):
        start = src.index(room)
        blocks[room] = src[start:src.index("}", start)]
    for room, block in blocks.items():
        missing = [r for r in roles if re.search(re.escape(r) + r"\s*:", block) is None]
        assert not missing, "%s does not define %s" % (room, ", ".join(missing))
