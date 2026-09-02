"""Keep the suite out of the real interview history.

`new_session` writes a session directory the moment it is called, so every test that built
one wrote into `data/sessions`, where real interviews live: 47 of them had accumulated
there. Autouse rather than opt-in, because the write is a side effect of construction and a
test need not look like it touches storage in order to pollute it.
"""

import pytest

from app import session as sess


@pytest.fixture(autouse=True)
def _sessions_in_tmp(tmp_path, monkeypatch):
    d = tmp_path / "sessions"
    d.mkdir()
    monkeypatch.setattr(sess, "SESSIONS", d)
    return d
