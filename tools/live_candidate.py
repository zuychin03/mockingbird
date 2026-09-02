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

from app import (contract, embed, observe, provenance, provider as prov,
                 resume, session as sess)  # noqa: E402
from app.runner import Runner  # noqa: E402

STATE = ROOT / "data" / "live_session.json"


def save(r: Runner) -> None:
    resume.write(r, STATE)


def extractor(p):
    """Plan 1c.5's per-answer extraction, as the runner wants it."""
    async def fn(question_id, question, utterance):
        return await observe.observe(p, question_id, question, [utterance])
    return fn


def restore(p, plan) -> Runner:
    # `plan` is ignored for a snapshot that carries its own, which is what makes a session
    # started here resumable in the browser and the other way round.
    return resume.read(p, None, STATE, observe_fn=extractor(p), similarity=embed.similarity)


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
        model = prov.product_model(loaded)
        if model is None:
            print("Llama 3.2 is not loaded as %s" % prov.MODEL)
            return 1
        state = sess.new_session(plan, provenance.snapshot(model))
        print("model %s" % model["id"])
        r = Runner(p, plan, state, observe_fn=extractor(p), similarity=embed.similarity)
        await p.warmup(contract.SYSTEM, contract.render(r.current["question"], "", ""))
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
