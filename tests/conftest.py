"""Keep the suite out of the real interview history.

`new_session` writes a session directory the moment it is called, so every test that built
one wrote into `data/sessions`, where real interviews live: 47 of them had accumulated
there. Autouse rather than opt-in, because the write is a side effect of construction and a
test need not look like it touches storage in order to pollute it.

The voice socket keeps its OWN paths and went the same way. `api/voice.py` resolves an
answer's directory through `data/live_session.json`, so tests that never mentioned storage
dropped 45 tone wavs into whichever interview was last run -- where a report would have
offered them back as the candidate's own answers. Same fix, one import further out.
"""

import pytest

from app import session as sess


@pytest.fixture(autouse=True)
def _sessions_in_tmp(tmp_path, monkeypatch):
    d = tmp_path / "sessions"
    d.mkdir()
    monkeypatch.setattr(sess, "SESSIONS", d)

    # `api/` needs the web extra and `app/` must stay importable without it, so this is a
    # try rather than a top-level import.
    try:
        from api import voice
    except ImportError:
        return d
    monkeypatch.setattr(voice, "SESSIONS", d)
    monkeypatch.setattr(voice, "LIVE", tmp_path / "no-live-session.json")
    monkeypatch.setattr(voice, "LOOSE", tmp_path / "voice")
    monkeypatch.setattr(voice, "ROOT", tmp_path)
    return d
