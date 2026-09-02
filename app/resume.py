"""Carry a live session across processes.

The terminal harness runs one command per process and the HTTP surface holds nothing between
requests, so both need the Runner's between-turn state written down and read back. It lives
here rather than in either caller, because the failure mode is specific and quiet: a field
that is not listed is silently reset on every turn. `focus_used` was missed once, and the
focus rotation did nothing for a whole live session while working perfectly in-process
(log 8.19) -- the interview looked fine and the rotation it depends on was simply absent.

`FIELDS` is the defence. `tests/test_resume.py` compares it against the Runner's actual
attributes, so a field added to the Runner and not to this list fails a test instead of
quietly resetting itself in production.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import session as sess
from .runner import Runner

# Plain attributes that survive a JSON round trip untouched.
FIELDS = ("index", "pool", "follow_ups_used", "clarifies_used", "stalls",
          "said_this_session", "design_followed_up", "clarify_extra", "skip_offered",
          "awaiting_confirm", "confirm_narrowed", "awaiting_skip_offer", "questions_asked",
          "said_this_question", "answers_this_question")

# Attributes that need converting in one or both directions, and why.
#   focus_used, seen   sets, which JSON has no notion of
#   last_probe         a tuple inside a tuple; `rewords` tests membership, so the shape matters
SET_FIELDS = ("focus_used", "seen")


def snapshot(r: Runner) -> dict[str, Any]:
    data: dict[str, Any] = {name: getattr(r, name) for name in FIELDS}
    data.update({
        "session_id": r.state.session_id,
        "status": r.state.status,
        "started_at": r.state.started_at,
        "focus_used": sorted(r.focus_used),
        "seen": sorted(r.seen),
        "last_probe": [r.last_probe[0], list(r.last_probe[1])] if r.last_probe else None,
        "history_summary": r.history.summary,
        "history_completed": [list(pair) for pair in r.history._completed],
        "history_dirty": r.history._dirty,
        "turns": [asdict(t) for t in r.state.turns],
        "questions": [asdict(q) for q in r.state.questions],
        # The plan travels WITH the session. A snapshot that needs the caller to supply the
        # right plan can be resumed against the wrong one, and the failure is silent: the
        # phases still load, the indices still resolve, and every question quietly becomes a
        # different question. Self-describing removes the possibility rather than guarding it.
        "plan": r.plan,
    })
    return data


def restore(provider, plan: dict | None, data: dict, *, observe_fn=None,
            similarity=None) -> Runner:
    """`plan` may be None for any snapshot that carries its own, which is all of them written
    since the plan was embedded. It is still accepted so a caller can resume an older file."""
    plan = plan if plan is not None else data["plan"]
    state = sess.SessionState(session_id=data["session_id"], plan_id=plan.get("id", "?"),
                              started_at=data.get("started_at", ""), status=data["status"])
    state.turns = [sess.Turn(**t) for t in data["turns"]]
    state.questions = [sess.QuestionState(**q) for q in data["questions"]]

    r = Runner(provider, plan, state, pool=data["pool"], observe_fn=observe_fn,
               similarity=similarity)
    for name in FIELDS:
        setattr(r, name, data[name])
    for name in SET_FIELDS:
        setattr(r, name, set(data.get(name, [])))
    lp = data.get("last_probe")
    r.last_probe = (lp[0], tuple(lp[1])) if lp else None
    r.history.summary = data["history_summary"]
    r.history._completed = [(q, a) for q, a in data["history_completed"]]
    r.history._dirty = data["history_dirty"]
    return r


def write(r: Runner, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snapshot(r), indent=1, ensure_ascii=False),
                 encoding="utf-8", newline="\n")


def read(provider, plan: dict | None, path: str | Path, *, observe_fn=None,
         similarity=None) -> Runner:
    return restore(provider, plan, json.loads(Path(path).read_text(encoding="utf-8")),
                   observe_fn=observe_fn, similarity=similarity)
