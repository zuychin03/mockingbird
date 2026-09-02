"""Carrying a session across processes, and the guard against the way it failed before.

A field the snapshot does not list is silently reset on every turn. `focus_used` was missed
once and the focus rotation did nothing for a whole live session while working in-process
(log 8.19): the interview read correctly and the mechanism it depends on was simply gone.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import resume, session as sess  # noqa: E402
from app.runner import Runner  # noqa: E402
from test_runner import build, d, run  # noqa: E402


def _advanced(tmp_path):
    """A runner several turns in, so the snapshot has something to lose."""
    r, state = build([d("probe", "What did you measure there?", ok=False),
                      d("advance", "", ok=True)], tmp_path)
    run(r.ask())
    run(r.submit("We cut the nightly batch from six hours to nineteen minutes."))
    return r


def test_a_restored_runner_matches_the_one_it_came_from(tmp_path):
    before = _advanced(tmp_path)
    after = resume.restore(before.provider, before.plan, resume.snapshot(before))

    for name in resume.FIELDS:
        assert getattr(after, name) == getattr(before, name), name
    assert after.focus_used == before.focus_used
    assert after.seen == before.seen
    assert after.last_probe == before.last_probe
    assert [t.act for t in after.state.turns] == [t.act for t in before.state.turns]
    assert after.state.status == before.state.status


def test_every_field_the_runner_carries_between_turns_is_persisted(tmp_path):
    """The regression guard for 8.19. A Runner attribute that changes during a session and is
    not in the snapshot resets on the next turn, and nothing else in the suite would notice.

    A new attribute failing this test is the point: either it belongs in the snapshot, or it
    belongs in the exemption list with a reason someone can read.
    """
    exempt = {
        # Injected dependencies, supplied fresh on every restore.
        "provider", "plan", "state", "observe_fn", "similarity", "history",
        # Derived from the plan or the state, never independently mutated.
        "questions", "pace", "max_say_words",
        # A live asyncio task. It cannot cross a process and is re-created by the next turn.
        "_pending",
    }
    r = _advanced(tmp_path)
    persisted = set(resume.FIELDS) | set(resume.SET_FIELDS) | {"last_probe"}

    carried = {name for name, value in vars(r).items()
               if not name.startswith("__")
               and name not in exempt
               and not callable(value)}
    missing = carried - persisted
    assert not missing, (
        "these Runner attributes are not persisted and will reset every turn: %s. "
        "Add them to resume.FIELDS, or to this test's exemption list with a reason."
        % ", ".join(sorted(missing)))


def test_a_snapshot_round_trips_through_a_file(tmp_path):
    before = _advanced(tmp_path)
    path = tmp_path / "session.json"
    resume.write(before, path)
    after = resume.read(before.provider, before.plan, path)
    assert after.index == before.index
    assert after.focus_used == before.focus_used
    assert json.loads(path.read_text(encoding="utf-8"))["session_id"] == before.state.session_id


def test_focus_used_survives_specifically(tmp_path):
    """Named on its own because this is the one that actually broke, and a set that arrives
    back as an empty set still passes every other assertion in this file."""
    before = _advanced(tmp_path)
    before.focus_used = {"MEASURE", "STEPS"}
    after = resume.restore(before.provider, before.plan, resume.snapshot(before))
    assert after.focus_used == {"MEASURE", "STEPS"}
    assert isinstance(after.focus_used, set)


def test_the_start_time_survives_a_resume(tmp_path):
    """It lives on the state, not the Runner, so `FIELDS` does not cover it. A resumed
    session that lost its start time cannot say how long it has been running."""
    before = _advanced(tmp_path)
    assert before.state.started_at

    path = tmp_path / "live.json"
    resume.write(before, path)
    assert json.loads(path.read_text(encoding="utf-8"))["started_at"] == before.state.started_at

    after = resume.restore(before.provider, before.plan, resume.snapshot(before))
    assert after.state.started_at == before.state.started_at
