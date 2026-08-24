"""Run a session one turn at a time, with a human (or Claude) as the candidate.

Every session measured so far replayed a FIXED list of candidate utterances. That is why
`--pin` exists: an adaptive interviewer and a fixed script desynchronise, and once they do,
every later answer addresses a question that was not asked. The drift is an artefact of the
fixture, and it has been contaminating the results it was meant to produce -- it inflates
`reask` and `clarify`, which then consume budget, which changes the pacing being measured.

Answering live removes the artefact at the source: the answer is a reply to the question the
interviewer actually asked, so there is nothing to drift.

The runner keeps its state in memory and each invocation is a new process, so the small
amount of state that matters is written to disk between turns. It is listed explicitly rather
than pickled: pickling a live object across a code change is how a harness starts lying.

    python tools/live_candidate.py --start
    python tools/live_candidate.py --answer "I'm a backend engineer, four years in."
    python tools/live_candidate.py --status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools._console import utf8  # noqa: E402

utf8()

from app import contract, observe, provenance, provider as prov, session as sess  # noqa: E402
from app.runner import Runner, Speech  # noqa: E402

STATE = ROOT / "data" / "live_session.json"


def save(r: Runner) -> None:
    STATE.write_text(json.dumps({
        "session_id": r.state.session_id,
        "index": r.index,
        "pool": r.pool,
        "follow_ups_used": r.follow_ups_used,
        "clarifies_used": r.clarifies_used,
        "focus_used": sorted(r.focus_used),
        "seen": sorted(r.seen),
        "stalls": r.stalls,
        "said_this_session": r.said_this_session,
        "design_followed_up": r.design_followed_up,
        "clarify_extra": r.clarify_extra,
        "skip_offered": r.skip_offered,
        "awaiting_confirm": r.awaiting_confirm,
        "confirm_narrowed": r.confirm_narrowed,
        "awaiting_skip_offer": r.awaiting_skip_offer,
        "questions_asked": r.questions_asked,
        "said_this_question": r.said_this_question,
        "answers_this_question": r.answers_this_question,
        "history_summary": r.history.summary,
        "history_completed": r.history._completed,
        "history_dirty": r.history._dirty,
        "status": r.state.status,
        "turns": [asdict(t) for t in r.state.turns],
        "questions": [asdict(q) for q in r.state.questions],
    }, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")


def extractor(p):
    """Plan 1c.5's per-answer extraction, as the runner wants it."""
    async def fn(question_id, question, utterance):
        return await observe.observe(p, question_id, question, [utterance])
    return fn


def restore(p, plan) -> Runner:
    d = json.loads(STATE.read_text(encoding="utf-8"))
    # Every field the Runner carries between turns has to be listed here. `focus_used` was
    # missed on the first pass, so each invocation began with an empty set and the rotation
    # silently did nothing across a live session while working in-process (log 8.19).
    state = sess.SessionState(session_id=d["session_id"], plan_id=plan.get("id", "?"),
                              started_at="", status=d["status"])
    state.turns = [sess.Turn(**t) for t in d["turns"]]
    state.questions = [sess.QuestionState(**q) for q in d["questions"]]
    try:
        live = prov.loaded_models()
    except Exception:
        live = []
    r = Runner(p, plan, state, pool=d["pool"], observe_fn=extractor(p),
               speech=Speech.for_model(prov.model_key(live[0]) if live else ""))
    r.index = d["index"]
    r.follow_ups_used = d["follow_ups_used"]
    r.clarifies_used = d["clarifies_used"]
    r.focus_used = set(d.get("focus_used", []))
    r.seen = set(d.get("seen", []))
    r.stalls = d.get("stalls", 0)
    r.said_this_session = d.get("said_this_session", [])
    r.design_followed_up = d.get("design_followed_up", False)
    r.clarify_extra = d["clarify_extra"]
    r.skip_offered = d["skip_offered"]
    r.awaiting_confirm = d["awaiting_confirm"]
    r.confirm_narrowed = d.get("confirm_narrowed", False)
    r.awaiting_skip_offer = d["awaiting_skip_offer"]
    r.questions_asked = d.get("questions_asked", [])
    r.said_this_question = d["said_this_question"]
    r.answers_this_question = d["answers_this_question"]
    r.history.summary = d["history_summary"]
    r.history._completed = [(q, a) for q, a in d["history_completed"]]
    r.history._dirty = d["history_dirty"]
    return r


def show(r: Runner, line: str) -> None:
    n = len(r.state.turns)
    print("\nINTERVIEWER: %s" % line)
    print("\n[q %d/%d | turn %d | pool %d | follow-ups %d/%d%s]" % (
        min(r.index + 1, len(r.questions)), len(r.questions), n, r.pool,
        r.follow_ups_used, (r.current or {}).get("probe_budget", 0),
        " | AWAITING YOUR REPLY TO AN OFFER" if r.awaiting_skip_offer or r.awaiting_confirm
        else ""))
    if r.state.turns:
        t = r.state.turns[-1]
        print("[hidden: act=%s guards=%s]" % (t.act, ",".join(t.guards) or "-"))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--answer")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--plan", default=str(ROOT / "config" / "interview_swe_general.json"))
    a = ap.parse_args()

    p = prov.LMStudio()
    plan = sess.load_plan(a.plan)

    if a.start:
        try:
            loaded = prov.loaded_models()
        except Exception:
            loaded = []
        # The resolved key, not the instance alias: it selects the profile AND is what a
        # stored session needs to be reproducible (9.24).
        key = prov.model_key(loaded[0]) if loaded else ""
        state = sess.new_session(plan, provenance.snapshot(
            dict(loaded[0], id=key) if loaded else None))
        speech = Speech.for_model(key)
        print("model %s   exemplars %s" % (key or "?", speech.exemplars))
        r = Runner(p, plan, state, observe_fn=extractor(p), speech=speech)
        await p.warmup(speech.system, contract.render(r.current["question"], "", ""))
        spoken = await r.ask()
        save(r)
        show(r, spoken.text)
        return 0

    r = restore(p, plan)

    if a.status:
        print("session %s  %s  q %d/%d  turns %d  pool %d" % (
            r.state.session_id, r.state.status, r.index + 1, len(r.questions),
            len(r.state.turns), r.pool))
        return 0

    if r.done:
        print("session already finished: %s" % r.state.status)
        return 0

    out = await r.submit(a.answer)
    line = out.spoken.text
    if out.closed_question and not r.done and not out.end_session:
        line = (line + "  " if line else "") + (await r.ask()).text
    elif r.done:
        line = line or "That's everything. Thanks for your time."
    save(r)
    show(r, line)
    await r.settle()
    save(r)
    if r.done or out.end_session:
        print("\n=== SESSION %s: %d/%d questions in %d turns ===" % (
            r.state.status.upper(), len(r.state.questions), len(r.questions),
            len(r.state.turns)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except prov.ProviderError as e:
        print("provider error: %s" % e)
        sys.exit(1)
