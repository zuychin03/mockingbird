"""Stage 1 entry point: a text interview in the terminal.

    python -m app.cli
    python -m app.cli --plan config/interview_swe_general.json --no-canary

Only what `live_view` returns is printed. Judgement fields go to
data/sessions/<id>/decisions.jsonl and are never shown during the session -- that split is
the whole point of section 5.1's second rule, not a UI detail.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from . import contract
from . import observe
from . import provenance
from . import provider as prov
from . import session
from .runner import Runner, live_view

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLAN = ROOT / "config" / "interview_swe_general.json"


def _say(text: str) -> None:
    print("\n  interviewer: %s" % text)


def _preflight(p: prov.LMStudio, skip: bool) -> dict | None:
    """The loaded model on success, None on a failure the session cannot start through."""
    try:
        loaded = prov.loaded_models()
    except Exception as e:
        print("cannot reach LM Studio: %s" % e)
        return None
    if not loaded:
        print("no model loaded. run: lms load granite-4.1-3b@q4_k_m "
              "--context-length 8192 --identifier mockingbird-llm -y")
        return None
    m = loaded[0]
    print("model: %s (%s, ctx %s)" % (m["id"], m.get("quantization"), m.get("loaded_context_length")))
    if skip:
        return m
    c = p.canary()
    print("canary: ttft %.0f ms, %.1f tok/s, transport %.0f ms" % (
        c["ttft_ms"], c["tokens_per_second"], c["transport_ms"]))
    if not c["clock_ok"]:
        print("  WARNING: the GPU memory clock has dropped to its idle P-state. Plug the "
              "laptop in -- that is the whole fix.")
    if not c["transport_ok"]:
        print("  WARNING: %.0f ms per call is being spent outside the server. Check that "
              "provider.BASE is 127.0.0.1 and not localhost." % c["transport_ms"])
    return m


async def run(plan_path: Path, skip_canary: bool) -> int:
    p = prov.LMStudio()
    model = _preflight(p, skip_canary)
    if model is None:
        return 1

    plan = session.load_plan(plan_path)
    # Before the first question, not after: this is what keeps turn 0 off the cold path.
    ms = await p.warmup(contract.SYSTEM, contract.render(
        next(session.iter_questions(plan))["question"], "", ""))
    print("warmed prompt cache in %.0f ms" % ms)
    state = session.new_session(plan, provenance.snapshot(model))

    async def observe_answer(question_id, question, utterance):
        """Plan 1c.5's per-answer extraction. Runs between turns, never inside one."""
        return await observe.observe(p, question_id, question, [utterance])

    r = Runner(p, plan, state, observe_fn=observe_answer)

    print("\nplan: %s   %d questions" % (plan.get("label", plan.get("id")), len(r.questions)))
    print("session: %s" % state.dir)
    print("(ctrl-c to abandon; say you want to stop and the agent will end properly)\n")

    spoken = await r.ask()
    _say(spoken.text)

    while not r.done:
        try:
            # Off the event loop on purpose: a blocking `input` here would also block the
            # background extraction 1c.5's stop rule depends on, and the seconds a candidate
            # spends composing are exactly the free window it is meant to run in.
            utterance = (await asyncio.to_thread(input, "\n  you: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nabandoned. transcript kept at %s" % state.dir)
            state.status = "abandoned"
            state.ended_at = session.now()
            session.checkpoint(state)
            return 130
        if not utterance:
            continue

        outcome = await r.submit(utterance)
        # A dropped `advance` ack is meant to go unnoticed; the next question follows.
        if outcome.spoken.text:
            _say(outcome.spoken.text)
        if outcome.end_session:
            break
        if outcome.closed_question and not r.done:
            nxt = await r.ask()
            _say(nxt.text)

    print("\n%s" % ("-" * 60))
    print("status: %s   turns: %d   questions closed: %d/%d" % (
        state.status, len(state.turns), len(state.questions), len(r.questions)))
    print("transcript:  %s" % (state.dir / "transcript.json"))
    print("decisions:   %s" % (state.dir / "decisions.jsonl"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=str(DEFAULT_PLAN))
    ap.add_argument("--no-canary", action="store_true")
    a = ap.parse_args()
    try:
        return asyncio.run(run(Path(a.plan), a.no_canary))
    except prov.ProviderError as e:
        print("\nprovider error: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
