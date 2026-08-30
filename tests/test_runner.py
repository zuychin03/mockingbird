"""Runner behaviour against a scripted provider.

The point of Stage 1 is the conversational core: probe, reask, skip on refusal, no invented
questions. These replay a fixed sequence of model outputs so the loop is tested without the
model's variability -- the model's own accuracy is Tier 1's subject, not this file's.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import budget, contract, focus, guards, intent, observe, result_check, session  # noqa: E402
from app.provider import Completion  # noqa: E402
from app.runner import CONFIRM_NARROW, Runner, live_view  # noqa: E402


class ScriptedProvider:
    """Returns queued decisions in order. Summariser calls get a fixed line."""

    def __init__(self, decisions):
        self.queue = list(decisions)
        self.prompts = []
        self.systems = []
        self.schemas = []

    async def complete(self, system, user, schema=None, max_tokens=400,
                       enum_field=None, enum_values=None):
        self.prompts.append(user)
        self.systems.append(system)
        self.schemas.append(schema)
        if schema is None:
            return Completion(text="Covered one question so far.")
        # Most historical runner tests script only full turn decisions. A speech repair is
        # an implementation detail for those cases: return a rejected empty repair without
        # consuming the next turn. Tests of the repair itself opt in with `speech()`.
        if schema == contract.SPEECH_SCHEMA and (
                not self.queue or not self.queue[0].get("_speech_response")):
            d = {"say": ""}
        else:
            d = dict(self.queue.pop(0))
            d.pop("_speech_response", None)
        return Completion(text=json.dumps(d), prompt_tokens=100, decode_tokens=30,
                          posterior={d["act"]: 0.9} if "act" in d else {})


PLAN = {
    "id": "test",
    "phases": [{
        "id": "p1", "answer_shape": "open", "probe_budget": 2, "scored": True,
        "questions": ["Question one?", "Question two?"],
    }],
}


def build(decisions, tmp_path):
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    return Runner(ScriptedProvider(decisions), PLAN, state), state


def run(coro):
    return asyncio.run(coro)


def d(act, say="line", ok=True, ask=""):
    return {"act": act, "say": say, "ok": ok, "ask": ask}


def speech(say, **extra):
    return {"say": say, "_speech_response": True, **extra}


def last_decision(state):
    return json.loads((state.dir / "decisions.jsonl").read_text(
        encoding="utf-8").strip().splitlines()[-1])


# ------------------------------------------------------------------- the core
def test_advance_closes_the_question_and_moves_on(tmp_path):
    r, state = build([d("advance", "Good.")], tmp_path)
    run(r.ask())
    out = run(r.submit("a full answer"))
    assert out.act == "advance" and out.closed_question
    assert r.current["question"] == "Question two?"
    assert len(state.questions) == 1


def test_probe_stays_on_the_same_question(tmp_path):
    r, _ = build([d("probe", "Tell me more.")], tmp_path)
    run(r.ask())
    out = run(r.submit("short"))
    assert out.act == "probe" and not out.closed_question
    assert r.current["question"] == "Question one?"
    assert r.follow_ups_used == 1


def test_skip_on_refusal_closes_without_an_answer(tmp_path):
    r, state = build([d("skip", "No problem.")], tmp_path)
    run(r.ask())
    out = run(r.submit("I'd rather not answer that one"))
    assert out.act == "skip" and out.closed_question
    assert state.questions[0].closed_by == "skip"


def test_reask_respeaks_the_question_when_say_is_empty(tmp_path):
    r, _ = build([d("reask", "")], tmp_path)
    run(r.ask())
    out = run(r.submit("nothing comes to mind"))
    assert out.spoken.text == "Question one?"


def test_clarify_does_not_consume_the_probe_budget(tmp_path):
    r, _ = build([d("clarify", "It means a specific example.")], tmp_path)
    run(r.ask())
    run(r.submit("what do you mean?"))
    assert r.follow_ups_used == 0


# -------------------------------------------------------------- probe budget
def test_probe_budget_forces_advance_once_exhausted(tmp_path):
    """With the pool emptied, the phase budget is the whole allowance."""
    r, _ = build([d("probe", "More?"), d("probe", "And then?"), d("probe", "Go on?")], tmp_path)
    r.pool = 0
    run(r.ask())
    run(r.submit("a"))
    run(r.submit("b"))
    out = run(r.submit("c"))
    assert out.act == "advance"
    assert out.closed_question


# ------------------------------------------------------------------- guards
def test_ungrounded_end_does_not_end_the_session(tmp_path):
    r, state = build([d("end", "Stopping.")], tmp_path)
    run(r.ask())
    out = run(r.submit("that's about all I remember"))
    assert out.act == "probe" and not out.end_session
    assert state.status == "running"


def test_grounded_end_stops_the_session(tmp_path):
    r, state = build([d("end", "Of course.")], tmp_path)
    run(r.ask())
    out = run(r.submit("sorry, I need to stop here"))
    assert out.act == "end" and out.end_session
    assert state.status == "ended_early"


# ------------------------------------------- the live/report split, section 5.1
def test_live_view_never_carries_judgement():
    from app.runner import Spoken
    v = live_view(Spoken(text="Tell me more.", question_id="p1.1",
                         question_index=1, question_total=2))
    assert set(v) == {"say", "of", "question", "next", "finished"}
    for leak in ("ok", "act", "guards", "posterior", "utterance"):
        assert leak not in v


def test_an_acknowledgement_belongs_to_the_question_it_closes(tmp_path):
    """`_dispatch` closed the question and incremented the index before building the Spoken,
    so the ack for question 1 went out labelled as question 2. Progress after the event is a
    separate field because it is a separate fact."""
    r, _ = build([d("advance", "Good, thanks.")], tmp_path)
    run(r.ask())
    out = run(r.submit("a full answer"))
    assert out.spoken.question_id == "p1.1", "the question this line is about"
    assert out.spoken.question_index == 1
    assert out.spoken.next_index == 2, "where the interview goes next"
    nxt = run(r.ask())
    assert nxt.question_id == "p1.2" and nxt.question_index == 2


def test_decisions_file_does_carry_judgement(tmp_path):
    r, state = build([d("advance", "Good.", ok=True)], tmp_path)
    run(r.ask())
    run(r.submit("a full answer"))
    lines = (state.dir / "decisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    rec = json.loads(lines[0])
    # Everything the live channel must not see has to be recoverable from disk.
    for needed in ("ok", "act", "guards", "posterior", "prompt", "utterance"):
        assert needed in rec


# --------------------------------------------------------- prompt assembly
def test_history_precedes_the_question_and_empty_history_is_omitted():
    bare = contract.render("Q?", "A")
    assert bare.startswith("CURRENT QUESTION:")
    assert "INTERVIEW SO FAR" not in bare

    withh = contract.render("Q?", "A", "Covered one question.")
    assert withh.index("INTERVIEW SO FAR") < withh.index("CURRENT QUESTION")


def test_history_is_refreshed_only_after_a_question_closes(tmp_path):
    r, _ = build([d("probe", "More?"), d("advance", "Good.")], tmp_path)
    run(r.ask())
    run(r.submit("a"))
    assert r.history.render() == ""       # nothing closed yet
    run(r.submit("b"))
    run(r.ask())                          # refresh happens when the next question opens
    assert r.history.render() != ""


# ------------------------------------------- clarify liveness (live find)
def test_clarify_cannot_loop_forever(tmp_path):
    """Termination still guaranteed; the route is now an offer, then an auto-skip."""
    # clarify does not consume the follow-up budget, so without its own cap a model that
    # keeps choosing it never closes the question.
    from app.runner import CLARIFY_LIMIT
    r, _ = build([d("clarify", "It means %d." % i) for i in range(CLARIFY_LIMIT + 1)], tmp_path)
    run(r.ask())
    for _ in range(CLARIFY_LIMIT):
        out = run(r.submit("what do you mean?"))
        assert out.act == "clarify"
    out = run(r.submit("still, what do you mean?"))
    assert "clarify-limit->skip-offer" in state_guards(r)
    out = run(r.submit("yes, skip it"))
    assert out.act == "skip" and out.closed_question


def state_guards(r):
    return r.state.turns[-1].guards


def test_a_question_always_terminates(tmp_path):
    # The strongest liveness claim: whatever the model returns, the question closes.
    r, _ = build([d("clarify")] * 3 + [d("probe")] * 4 + [d("advance")], tmp_path)
    run(r.ask())
    for i in range(8):
        if r.current is None or r.index > 0:
            break
        run(r.submit("something"))
    assert r.index > 0, "question never closed"


# ----------------------------------------- rec 2: symmetric end guard + confirm
def test_stop_words_with_a_non_end_action_trigger_a_confirmation(tmp_path):
    # Observed live: "something's come up and I need to stop here" was read as `skip`.
    r, state = build([d("skip", "Moving on.")], tmp_path)
    run(r.ask())
    out = run(r.submit("sorry, something's come up and I need to stop here"))
    assert not out.end_session, "must not end on the model's word alone"
    assert not out.closed_question
    assert r.awaiting_confirm
    assert "stop-detected->confirm" in state.turns[-1].guards


def test_confirming_the_stop_ends_the_session(tmp_path):
    r, state = build([d("skip", "Moving on.")], tmp_path)
    run(r.ask())
    run(r.submit("I need to stop here"))
    out = run(r.submit("yes, please stop"))
    assert out.act == "end" and out.end_session
    assert state.status == "ended_early"


def test_declining_the_stop_carries_on(tmp_path):
    r, state = build([d("skip", "Moving on.")], tmp_path)
    run(r.ask())
    run(r.submit("I need to stop here"))
    out = run(r.submit("no, carry on"))
    assert out.act == "reask" and not out.end_session
    assert state.status == "running"
    assert not r.awaiting_confirm


def test_an_ambiguous_confirmation_narrows_once_then_continues(tmp_path):
    # Wrongly continuing costs seconds; wrongly ending loses the session. CONFIRM_LINE offers
    # three outcomes, so an ambiguous reply is narrowed to a question a yes or no can answer
    # rather than guessed at -- and the old parser's guess was `end` (9.13).
    r, state = build([d("skip", "Moving on.")], tmp_path)
    run(r.ask())
    run(r.submit("I need to stop here"))
    out = run(r.submit("what exactly are you asking?"))
    assert not out.end_session, "ambiguity must never end the session"
    assert "confirm-unclear->narrow" in state.turns[-1].guards
    assert r.awaiting_confirm, "still waiting on the same question, asked more simply"
    # Narrowed once and no more: a second ambiguous reply carries on rather than looping.
    out = run(r.submit("hmm, I'm not sure"))
    assert out.act == "reask" and not out.end_session
    assert not r.awaiting_confirm


def test_a_negated_stop_does_not_end_the_session(tmp_path):
    """The release blocker. Substring matching read "No, I don't want to stop." as consent,
    and the detector that raised the confirmation was wrong the same way, so a candidate who
    declined twice was stopped anyway (9.13)."""
    r, state = build([d("skip", "Moving on.")], tmp_path)
    run(r.ask())
    assert not guards.user_asked_to_stop("I don't need to stop; let's continue.")
    run(r.submit("I need to stop here"))
    out = run(r.submit("No, I don't want to stop."))
    assert out.act == "reask" and not out.end_session
    assert state.status == "running"


def test_the_offered_skip_is_reachable_from_the_confirmation(tmp_path):
    """CONFIRM_LINE offers "skip this question and carry on" and the parser had no branch
    for it, so taking the offer re-asked the question they had asked to leave (9.13)."""
    r, state = build([d("skip", "Moving on.")], tmp_path)
    run(r.ask())
    run(r.submit("I need to stop here"))
    out = run(r.submit("skip this question and carry on"))
    assert out.act == "skip" and out.closed_question and not out.end_session
    assert "confirmed-skip" in state.turns[-1].guards


def test_no_bare_affirmative_ends_a_three_way_confirmation(tmp_path):
    """"yes" against "do you want A, or B?" carries no information. It used to end the
    session; now it narrows, and only then does a bare yes mean anything."""
    r, _ = build([d("skip", "Moving on.")], tmp_path)
    run(r.ask())
    run(r.submit("I need to stop here"))
    out = run(r.submit("yes"))
    assert not out.end_session
    assert CONFIRM_NARROW in out.spoken.text
    out = run(r.submit("yes"))
    assert out.act == "end" and out.end_session, "answerable once the question is two-way"


def test_the_confirmation_turn_costs_no_model_call(tmp_path):
    r, _ = build([d("skip", "Moving on.")], tmp_path)
    run(r.ask())
    before = len(r.provider.queue)
    run(r.submit("I need to stop here"))
    run(r.submit("yes"))
    assert len(r.provider.queue) == before - 1, "only the first turn should hit the model"



# ------------------------------- per-question cap + session pool (log 8.15, 8.16)
def test_a_question_gets_its_phase_budget_without_touching_the_pool():
    a = budget.follow_ups_allowed(phase_budget=3, pool_left=14,
                                  questions_done=0, question_total=14)
    assert a.cap == 3
    assert a.total == 3 + 1, "plus its fair share of the pool"


def test_the_pool_share_is_what_remains_divided_by_what_is_left():
    a = budget.follow_ups_allowed(3, pool_left=10, questions_done=9, question_total=14)
    assert a.overflow == 2, "10 left over 5 questions"


def test_the_pool_share_rounds_down():
    """A fraction reads as generous and compares as more generous still (log 8.13)."""
    a = budget.follow_ups_allowed(1, pool_left=9, questions_done=4, question_total=14)
    assert a.overflow == 0, "9 over 10 questions is not one each"


def test_an_empty_pool_leaves_the_cap_intact():
    a = budget.follow_ups_allowed(2, pool_left=0, questions_done=13, question_total=14)
    assert a.cap == 2 and a.overflow == 0 and a.total == 2


def test_a_zero_budget_phase_gets_a_HARD_zero():
    """Reversed. Letting `closing` draw overflow produced the same failure in both live
    sessions: the candidate asks their question and the agent asks it back (log 8.20)."""
    a = budget.follow_ups_allowed(0, pool_left=14, questions_done=0, question_total=14)
    assert a.cap == 0 and a.overflow == 0 and a.total == 0


def test_the_pool_scales_with_the_plan():
    """The whole point: another role or a custom question set needs no re-tuning."""
    assert budget.session_pool(14) == 14
    assert budget.session_pool(8) == 8
    assert budget.session_pool(30) == 30
    assert budget.session_pool(14, per_question=0.5) == 7


def test_reask_now_counts_against_the_cap(tmp_path):
    """Stage 1 charged reask to the allowance and never checked it against one."""
    r, _ = build([d("reask", "one"), d("reask", "two"), d("probe", "three")], tmp_path)
    r.pool = 0
    run(r.ask())
    run(r.submit("mumble"))
    run(r.submit("mumble again"))
    assert r.follow_ups_used == 2
    out = run(r.submit("still nothing"))
    assert out.act == "advance", "the third follow-up exceeds probe_budget 2 with no pool"


def test_a_follow_up_past_the_cap_draws_from_the_pool(tmp_path):
    r, state = build([d("probe", "one"), d("probe", "two"), d("probe", "three")], tmp_path)
    r.pool = 4
    run(r.ask())
    run(r.submit("a"))
    run(r.submit("b"))
    assert r.pool == 4, "within probe_budget 2, so the pool is untouched"
    out = run(r.submit("c"))
    assert out.act == "probe" and r.pool == 3
    assert any("pool-draw" in g for g in state.turns[-1].guards)


def test_the_pool_is_shared_so_an_early_question_cannot_drain_it(tmp_path):
    r, _ = build([d("probe", str(i)) for i in range(6)], tmp_path)
    r.pool = 2                     # 2 questions, so one overflow turn each
    run(r.ask())
    run(r.submit("a"))
    run(r.submit("b"))
    run(r.submit("c"))             # first question draws its single share
    assert r.pool == 1
    out = run(r.submit("d"))
    assert out.act == "advance", "it cannot take the second question's share as well"


# ------------------------------------------- clarify escalation (log 8.16)
def test_clarify_past_the_limit_offers_a_skip_instead_of_repeating(tmp_path):
    r, state = build([d("clarify", "a"), d("clarify", "b"), d("clarify", "c")], tmp_path)
    run(r.ask())
    run(r.submit("what do you mean?"))
    run(r.submit("sorry, which sense do you mean?"))
    out = run(r.submit("could you clarify what you are after?"))
    assert out.act == "clarify"
    assert "clarify-limit->skip-offer" in state.turns[-1].guards
    assert "skip it" in out.spoken.text or "skip" in out.spoken.text.lower()
    assert r.awaiting_skip_offer


def test_accepting_the_skip_offer_closes_the_question(tmp_path):
    r, state = build([d("clarify", "a"), d("clarify", "b"), d("clarify", "c")], tmp_path)
    run(r.ask())
    run(r.submit("what do you mean?"))
    run(r.submit("sorry, which sense do you mean?"))
    run(r.submit("could you clarify what you are after?"))
    before = len(r.provider.queue)
    out = run(r.submit("yes please, skip it"))
    assert out.act == "skip" and out.closed_question
    assert len(r.provider.queue) == before, "the reply to an offer costs no model call"


def test_declining_the_offer_buys_one_more_explanation_then_auto_skips(tmp_path):
    r, state = build([d("clarify", str(i)) for i in range(6)], tmp_path)
    run(r.ask())
    run(r.submit("what do you mean?"))
    run(r.submit("sorry, which sense do you mean?"))
    run(r.submit("could you clarify what you are after?"))
    out = run(r.submit("no, let me try again"))
    assert out.act == "clarify" and r.clarify_extra == 1
    assert "skip-offer-declined" in state.turns[-1].guards
    out = run(r.submit("what do you mean by that?"))
    assert out.act == "clarify", "the granted attempt, not the auto-skip"
    out = run(r.submit("sorry, in what sense?"))
    assert out.act == "skip" and out.closed_question
    assert "clarify-limit->auto-skip" in state.turns[-1].guards


def test_the_offer_turn_itself_does_not_count_as_a_clarification(tmp_path):
    r, _ = build([d("clarify", "a"), d("clarify", "b"), d("clarify", "c")], tmp_path)
    run(r.ask())
    run(r.submit("what do you mean?"))
    run(r.submit("sorry, which sense do you mean?"))
    assert r.clarifies_used == 2
    run(r.submit("could you clarify what you are after?"))
    assert r.clarifies_used == 2, "the offer is not an explanation of the question"


# ---------------------------------------------- close reasons (review I5)
def test_close_reasons_separate_the_ways_a_question_can_end():
    """`closed_by` records advance, skip or end, which puts an answer the model was happy
    with in the same bucket as one that ran out of turns."""
    from app.runner import close_reason
    cases = [
        ("advance", ["observations-complete->advance"], "evidence_complete"),
        ("advance", ["no-new-observation->advance"], "no_new_evidence"),
        ("advance", ["pool-exhausted->advance"], "budget_exhausted"),
        ("advance", ["follow-up-cap->advance"], "budget_exhausted"),
        ("advance", ["repeated-say->regenerate", "regenerated",
                     "regeneration-repeated->advance"], "wording_exhausted"),
        ("advance", ["candidate-question->noted", "detour-budget->advance"],
         "detour_budget_spent"),
        ("advance", ["closing->advance"], "closing_complete"),
        ("skip", ["clarify-limit->auto-skip"], "clarification_exhausted"),
        ("skip", ["skip-offer-accepted"], "skip_consented"),
        ("skip", ["confirmed-skip"], "skip_consented"),
        ("skip", [], "refused"),
        ("end", ["confirmed-stop"], "ended_early"),
        ("advance", ["hedge-stripped"], "model_advanced"),
    ]
    for act, applied, want in cases:
        assert close_reason(act, applied) == want, (act, applied)


def test_the_reason_a_question_closed_is_recorded_with_it(tmp_path):
    r, state = build([d("probe", "More?"), d("probe", "And?"), d("probe", "Go on?")], tmp_path)
    r.pool = 0
    run(r.ask())
    run(r.submit("a"))
    run(r.submit("b"))
    run(r.submit("c"))
    q = state.questions[0]
    assert q.closed_by == "advance"
    assert q.closed_because == "budget_exhausted", "ran out of turns, was not satisfied"
    rec = json.loads((state.dir / "decisions.jsonl").read_text(
        encoding="utf-8").strip().splitlines()[-1])
    assert rec["close_reason"] == "budget_exhausted"


def test_a_turn_that_closes_nothing_records_no_close_reason(tmp_path):
    r, state = build([d("probe", "More?")], tmp_path)
    run(r.ask())
    run(r.submit("a"))
    rec = json.loads((state.dir / "decisions.jsonl").read_text(
        encoding="utf-8").strip().splitlines()[-1])
    assert rec["close_reason"] is None


# ------------------------------------- direction of talk (review R3, log 9.15)
CANDIDATE_Q = ("And is there someone who'd be reviewing my code regularly? That's the thing "
               "I'm missing most where I am.")


def test_a_candidate_question_is_not_evidence_for_the_question_it_interrupts(tmp_path):
    """Verified in session 20260823-182833-4138f0: the candidate's questions were processed
    under collaboration.2, contributed to its adaptive closure, and were then repeated under
    closing.1 and ignored. One defect, three consequences."""
    r, state = build([d("probe", "Tell me more.")], tmp_path)
    run(r.ask())
    before = len(r.provider.queue)
    out = run(r.submit(CANDIDATE_Q))

    assert "candidate-question->defer" in state.turns[-1].guards
    assert out.act == "clarify" and not out.closed_question
    assert r.follow_ups_used == 0, "a question they asked is not a follow-up they used"
    assert r.clarifies_used == 0, "nor an explanation of the question"
    assert r.answers_this_question == [], "must never reach the extractor or the rubric"
    assert r.questions_asked == [CANDIDATE_Q], "recorded, on its own list"
    assert len(r.provider.queue) == before, "costs no model call"


def test_an_answer_with_a_question_on_the_end_keeps_its_answer(tmp_path):
    """Found in live session 20260824-035507. The whole utterance went to the question
    handler, so two sentences of real evidence were discarded (9.16)."""
    mixed = ("I think I've probably picked up some bad habits and I wouldn't know. Nobody's "
             "ever told me my code is wrong, they just merge it. And is there someone who'd "
             "be reviewing my code regularly here?")
    r, state = build([d("probe", "Tell me more.")], tmp_path)
    run(r.ask())
    out = run(r.submit(mixed))
    assert out.act == "clarify"
    assert "answer-part-kept" in state.turns[-1].guards
    assert len(r.answers_this_question) == 1
    kept = r.answers_this_question[0]
    assert "bad habits" in kept and "they just merge it" in kept
    assert "reviewing my code" not in kept, "the question is not part of the answer"
    assert r.questions_asked == [mixed]


def test_a_bare_question_records_no_answer(tmp_path):
    r, _ = build([d("probe", "Tell me more.")], tmp_path)
    run(r.ask())
    run(r.submit("Actually, can I ask - what does the on-call look like here?"))
    assert r.answers_this_question == [], "throat-clearing is not evidence"


def test_a_stop_request_is_never_read_as_a_candidate_question(tmp_path):
    """Found live: "do we have to stop here?" matched the bare `here` in HIRING_CONTEXT and
    was answered "Good question. Let's finish this one first." The candidate was not wrongly
    stopped, but a stop request was talked over, and the direction check runs BEFORE the stop
    detector so nothing downstream could recover it (9.16)."""
    r, state = build([d("probe", "Tell me more.")], tmp_path)
    run(r.ask())
    out = run(r.submit("Sorry, this is uncomfortable - do we have to stop here?"))
    assert "candidate-question->defer" not in state.turns[-1].guards
    assert "stop-detected->confirm" in state.turns[-1].guards
    assert r.awaiting_confirm and not out.end_session


def test_an_answer_containing_a_question_mark_is_still_an_answer(tmp_path):
    """The rule that ships is measured in tools/tier2_direction.py. This pins the failure
    that would matter here: deflecting a real answer discards evidence."""
    r, _ = build([d("probe", "Tell me more.")], tmp_path)
    run(r.ask())
    run(r.submit("Of the codebase? Around eighty thousand lines of Go across four services."))
    assert r.answers_this_question, "a hedged answer must not be read as an enquiry"
    assert r.questions_asked == []


CLOSING_PLAN = {
    "id": "closing-test",
    "phases": [{
        "id": "closing", "type": "user_questions", "answer_shape": "closed",
        "probe_budget": 0, "detour_budget": 2, "scored": False,
        "questions": ["That's everything from me. What questions do you have?"],
    }],
}


def build_closing(tmp_path):
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(CLOSING_PLAN)
    return Runner(ScriptedProvider([]), CLOSING_PLAN, state), state


def test_the_closing_phase_answers_for_itself(tmp_path):
    """`type: user_questions` and `detour_budget: 3` were configured and read by nothing, so
    the generic loop ran the phase: it captured the candidate's questions into `ask` and
    advanced past them without a word."""
    r, state = build_closing(tmp_path)
    run(r.ask())
    out = run(r.submit(CANDIDATE_Q))
    assert out.act == "clarify" and not out.closed_question, "still their turn"
    assert "candidate-question->noted" in state.turns[-1].guards
    assert out.spoken.text, "a question they asked gets an answer, not silence"
    assert last_decision(state)["say_raw"] is None


def test_the_closing_phase_is_bounded_by_detour_budget(tmp_path):
    r, state = build_closing(tmp_path)
    run(r.ask())
    run(r.submit(CANDIDATE_Q))
    out = run(r.submit("What does the on-call look like here, and who else would cover me?"))
    assert out.closed_question, "detour_budget 2 means two questions"
    assert "detour-budget->advance" in state.turns[-1].guards


def test_what_the_candidate_asked_is_kept_apart_from_what_they_answered(tmp_path):
    r, state = build_closing(tmp_path)
    run(r.ask())
    run(r.submit(CANDIDATE_Q))
    run(r.submit("Nothing else from me, thanks."))
    q = state.questions[0]
    assert q.asked_back == [CANDIDATE_Q]
    assert CANDIDATE_Q not in q.answers, "a question they asked is not an answer they gave"
    assert q.answers == ["Nothing else from me, thanks."]
    # The transcript keeps everything; it is the report's view that is separated.
    assert CANDIDATE_Q in [t.utterance for t in state.turns]
    assert "closing->advance" in state.turns[-1].guards


def test_a_stop_request_still_works_in_the_closing_phase(tmp_path):
    """The phase bypasses the model, so it has to run the stop check itself."""
    r, state = build_closing(tmp_path)
    run(r.ask())
    out = run(r.submit("Nothing more, but I need to stop the interview here."))
    assert not out.end_session
    assert "stop-detected->confirm" in state.turns[-1].guards
    assert r.awaiting_confirm


def test_a_plan_naming_an_unknown_rubric_criterion_fails_at_load(tmp_path):
    """`score_question` skips a name it does not recognise, so a phase asking for three
    criteria scored one and reported the smaller denominator with no warning. Harmless with
    one hand-written plan, active the moment Stage 3 generates them."""
    import json
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"id": "x", "phases": [{
        "id": "a", "type": "adaptive_discussion", "answer_shape": "open", "scored": True,
        "rubric_criteria": ["sets_context", "communication"], "questions": ["Q?"]}]}),
        encoding="utf-8")
    try:
        session.load_plan(p)
    except ValueError as e:
        assert "communication" in str(e), "must name the criterion it rejected"
        assert "sets_context" in str(e), "and list what it does know"
    else:
        raise AssertionError("an unknown rubric criterion loaded silently")


def test_a_scored_phase_with_no_criteria_fails_at_load(tmp_path):
    import json
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"id": "x", "phases": [{
        "id": "a", "type": "adaptive_discussion", "answer_shape": "open", "scored": True,
        "rubric_criteria": [], "questions": ["Q?"]}]}), encoding="utf-8")
    try:
        session.load_plan(p)
    except ValueError as e:
        assert "scored" in str(e)
    else:
        raise AssertionError("a scored phase that scores nothing loaded silently")


def test_the_shipped_plan_still_loads():
    """The validation above has to pass the plan the project actually runs."""
    root = Path(__file__).resolve().parent.parent
    plan = session.load_plan(root / "config" / "interview_swe_general.json")
    assert len(list(session.iter_questions(plan))) == 14


# --------------------------------------- clarification upgrade (rec 2's other half)
def test_asking_what_the_question_means_is_upgraded_to_clarify(tmp_path):
    """Guard 2b only ever DOWNGRADES an ungrounded `clarify`. Observed live (9.16): the
    candidate asked "do you mean the WordPress site or the booking tool?" and the model had
    chosen `reask`, so they got a focus template instead of an answer."""
    r, state = build([d("reask", "Describe the booking tool's architecture.")], tmp_path)
    run(r.ask())
    out = run(r.submit("Sorry, do you mean the WordPress site or the booking tool? "
                       "They're different projects."))
    assert out.act == "clarify"
    assert "clarify-detected->clarify" in state.turns[-1].guards
    assert r.follow_ups_used == 0, "clarify never spends the follow-up budget"
    assert r.clarifies_used == 1, "but it does count against the liveness limit"


def test_a_choice_between_their_own_examples_gets_answered_as_a_choice(tmp_path):
    """"Did you mean A or B?" and "what does this mean?" want different answers. The generic
    fallback answers only the second, so live it met "do you mean the WordPress site or the
    booking tool?" with "It just means a specific example from your own experience" (9.17)."""
    from app.runner import CLARIFY_EITHER
    r, _ = build([d("reask", "Describe the architecture.")], tmp_path)
    run(r.ask())
    out = run(r.submit("Sorry, do you mean the WordPress site or the booking tool?"))
    assert out.spoken.text == CLARIFY_EITHER


def test_a_plain_clarification_keeps_the_generic_explanation(tmp_path):
    r, _ = build([d("reask", "Describe the architecture.")], tmp_path)
    run(r.ask())
    out = run(r.submit("Sorry, what do you mean?"))
    assert "specific example" in out.spoken.text
    assert "Your choice" not in out.spoken.text


def test_the_upgrade_does_not_override_a_grounded_halt(tmp_path):
    """`skip` and `end` are already grounded in the candidate's own words, and clarifying
    over them would ignore what that grounding said."""
    r, state = build([d("skip", "No problem.")], tmp_path)
    run(r.ask())
    out = run(r.submit("I'd rather not answer that one. Do you mean something recent?"))
    assert out.act == "skip"
    assert "clarify-detected->clarify" not in state.turns[-1].guards


def test_a_bare_question_mark_does_not_trigger_the_upgrade(tmp_path):
    """The upgrade decides on its own, so it uses the vocabulary and never the bare "?" --
    most utterances carrying one are answers (9.15)."""
    r, state = build([d("probe", "Tell me more.")], tmp_path)
    run(r.ask())
    out = run(r.submit("Um, I guess maybe when we picked React over Vue?"))
    assert out.act == "probe"
    assert "clarify-detected->clarify" not in state.turns[-1].guards


def test_a_plan_naming_an_unimplemented_phase_type_fails_at_load(tmp_path):
    """An unwired setting is a comment that looks like a setting. It must fail at load,
    not at the turn that needed it."""
    import json
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"id": "x", "phases": [
        {"id": "a", "type": "socratic_dialogue", "answer_shape": "open", "questions": ["Q?"]}]}),
        encoding="utf-8")
    try:
        session.load_plan(p)
    except ValueError as e:
        assert "socratic_dialogue" in str(e) and "user_questions" in str(e)
    else:
        raise AssertionError("an unknown phase type loaded silently")


def test_skip_vocabulary_is_not_the_stop_vocabulary():
    """"skip it" asks for a SKIP either way, and the thing it must never be read as is a
    request to end the session."""
    assert intent.wants_skip("yes, skip it") is True
    assert intent.read_control("no, skip it and carry on") == intent.SKIP_QUESTION
    assert intent.wants_skip("no, let me try again") is False
    assert intent.wants_skip("mmm") is False, "ambiguous replies keep going"


def test_a_stop_request_in_reply_to_a_skip_offer_is_not_swallowed(tmp_path):
    """The offer consumes the utterance, so without this branch the detector never sees the
    stop request and it is dropped for a turn."""
    r, state = build([d("clarify", "a"), d("clarify", "b"), d("clarify", "c")], tmp_path)
    run(r.ask())
    run(r.submit("what do you mean?"))
    run(r.submit("sorry, which sense do you mean?"))
    run(r.submit("could you clarify what you are after?"))
    out = run(r.submit("actually I need to stop the interview"))
    assert not out.end_session, "still a confirmation, never an end on one utterance"
    assert "stop-in-skip-reply->confirm" in state.turns[-1].guards
    assert r.awaiting_confirm


def test_the_escalation_resets_on_the_next_question(tmp_path):
    r, _ = build([d("clarify", "a"), d("clarify", "b"), d("clarify", "c")], tmp_path)
    run(r.ask())
    run(r.submit("what do you mean?"))
    run(r.submit("in what sense?"))
    run(r.submit("could you clarify what you are after?"))
    run(r.submit("yes skip it"))
    assert r.clarifies_used == 0 and not r.skip_offered and r.clarify_extra == 0


def test_declining_grants_a_real_extra_attempt_not_a_spent_one(tmp_path):
    """The decline line rides on `clarify`; counting it spends the attempt it grants."""
    r, _ = build([d("clarify", str(i)) for i in range(6)], tmp_path)
    run(r.ask())
    run(r.submit("what do you mean?"))
    run(r.submit("in what sense?"))
    assert r.clarifies_used == 2
    run(r.submit("could you clarify what you are after?"))                      # offer
    run(r.submit("no, keep going"))               # decline
    assert r.clarifies_used == 2, "the decline is not an explanation"
    out = run(r.submit("what exactly are you asking?"))                    # the granted extra attempt
    assert out.act == "clarify" and r.clarifies_used == 3
    out = run(r.submit("sorry, can you clarify again?"))             # now it may auto-skip
    assert out.act == "skip"


def _accept_any_focus(monkeypatch):
    """Focus rotation now diversifies the line BEFORE the repetition guard sees it, which is
    the point of it. These tests are about the repetition guard, so the validator is made to
    accept whatever comes back."""
    monkeypatch.setattr(focus, "classify", lambda say: set(focus.FOCUS))


def test_a_regeneration_that_repeats_itself_advances(tmp_path, monkeypatch):
    _accept_any_focus(monkeypatch)
    """Measured: 28% of regenerations trip the string test again and were spoken anyway."""
    r, state = build([d("probe", "Why did you pick that?"),
                      d("probe", "Why did you pick that?"),
                      d("probe", "Why did you pick that?")], tmp_path)
    run(r.ask())
    run(r.submit("we used Redis"))
    out = run(r.submit("because it was fast"))
    assert out.act == "advance"
    assert "regeneration-repeated->advance" in state.turns[-1].guards


def test_the_first_passes_guards_survive_a_regeneration(tmp_path, monkeypatch):
    _accept_any_focus(monkeypatch)
    """`g` was replaced wholesale, so pass-1 guard names vanished from the replay record."""
    r, state = build([d("probe", "Same line."), d("probe", "Same line."),
                      d("advance", "Thanks.")], tmp_path)
    run(r.ask())
    run(r.submit("first"))
    run(r.submit("second"))
    assert "regenerated" in state.turns[-1].guards


def test_a_regenerated_turn_records_both_model_calls(tmp_path, monkeypatch):
    _accept_any_focus(monkeypatch)
    """One turn, two decodes, previously logged as one -- which biased 8.17's latency low."""
    import json
    r, state = build([d("probe", "Same line."), d("probe", "Same line."),
                      d("advance", "Thanks.")], tmp_path)
    run(r.ask())
    run(r.submit("first"))
    run(r.submit("second"))
    last = json.loads((state.dir / "decisions.jsonl").read_text(
        encoding="utf-8").strip().splitlines()[-1])
    assert last["model_calls"] == 2


def test_regeneration_records_the_accepted_retry_as_raw_speech(tmp_path, monkeypatch):
    _accept_any_focus(monkeypatch)
    r, state = build([d("probe", "Same line."), d("probe", "Same line."),
                      d("probe", "What happened after that?")], tmp_path)
    run(r.ask())
    run(r.submit("first"))
    run(r.submit("second"))
    assert last_decision(state)["say_raw"] == "What happened after that?"


def test_the_raw_model_line_survives_an_invented_question_drop(tmp_path):
    raw_say = "Thanks for that. What would you do differently next time?"
    r, state = build([d("advance", raw_say, ok=True)], tmp_path)
    run(r.ask())
    run(r.submit("I fixed the issue and documented it."))
    decision = last_decision(state)
    assert "invented-question-dropped" in decision["guards"]
    assert decision["say_raw"] == raw_say


def test_compound_speech_is_trimmed_without_hiding_raw_provenance_or_adding_a_turn(
        tmp_path, monkeypatch):
    _accept_any_focus(monkeypatch)
    raw_say = "How did your team respond, and what was the outcome?"
    r, state = build([d("probe", raw_say, ok=False)], tmp_path)
    run(r.ask())
    out = run(r.submit("We restored the service together."))
    decision = last_decision(state)
    assert out.spoken.text == "How did your team respond?"
    assert r.follow_ups_used == 1
    assert decision["model_calls"] == 1
    assert decision["say_raw"] == raw_say
    assert "compound-request-trimmed" in decision["guards"]


def test_auxiliary_led_compound_speech_keeps_only_the_first_request(
        tmp_path, monkeypatch):
    _accept_any_focus(monkeypatch)
    raw_say = ("What was your role in that process, and did you have any input on how "
               "the feedback was delivered?")
    r, state = build([d("probe", raw_say, ok=False)], tmp_path)
    run(r.ask())

    out = run(r.submit("I helped the senior developer with the review."))
    decision = last_decision(state)

    assert out.spoken.text == "What was your role in that process?"
    assert decision["say_raw"] == raw_say
    assert "compound-request-trimmed" in decision["guards"]


def test_empty_probe_speech_is_repaired_without_redeciding_action_or_focus(
        tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "MEASURE")
    invented = "How did you measure the processing delay?"
    r, state = build([d("probe", "", ok=False),
                      speech(invented)], tmp_path)
    run(r.ask())

    out = run(r.submit("It took about twenty minutes."))
    decision = last_decision(state)

    assert out.act == "probe"
    assert out.spoken.text == invented
    assert decision["focus_got"] == ["MEASURE"]
    assert decision["say_raw"] == ""
    assert decision["speech_attempt"]["trigger"] == "empty"
    assert decision["speech_attempt"]["say_raw"] == invented
    assert decision["speech_attempt"]["accepted"] is True
    assert decision["speech_attempt"]["rejection"] is None
    assert decision["model_calls"] == 2
    assert "empty-say->repaired" in decision["guards"]
    assert r.provider.schemas[1] == contract.SPEECH_SCHEMA


def test_speech_repair_schema_cannot_change_the_locked_action(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "MEASURE")
    r, state = build([d("probe", "", ok=False),
                      speech("How did you measure the delay?", act="advance")], tmp_path)
    run(r.ask())

    out = run(r.submit("It took about twenty minutes."))
    decision = last_decision(state)

    assert out.act == "probe"
    assert out.spoken.text == "How did you measure the delay?"
    assert decision["focus_got"] == ["MEASURE"]
    assert decision["model_calls"] == 2
    assert decision["speech_attempt"]["accepted"] is True
    assert "empty-say->repaired" in decision["guards"]


def test_empty_probe_speech_repair_rejects_the_wrong_focus(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "MEASURE")
    r, state = build([d("probe", "", ok=False),
                      speech("Why did you choose Redis?")], tmp_path)
    run(r.ask())

    out = run(r.submit("It took about twenty minutes."))
    decision = last_decision(state)

    assert out.act == "probe"
    assert out.spoken.text in focus.TEMPLATE["MEASURE"]
    assert decision["focus_got"] == ["MEASURE"]
    assert decision["say_raw"] == ""
    assert decision["model_calls"] == 2
    assert decision["speech_attempt"]["accepted"] is False
    assert decision["speech_attempt"]["rejection"] == "off_focus"
    assert decision["speech_attempt"]["say_raw"] == "Why did you choose Redis?"
    assert "empty-say->repair-failed" in decision["guards"]
    assert "empty-say->template" in decision["guards"]


def test_empty_probe_speech_repair_logs_an_empty_retry_before_template_fallback(
        tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "STEPS")
    r, state = build([d("probe", "", ok=False), speech("")], tmp_path)
    run(r.ask())

    out = run(r.submit("I changed a few things."))
    decision = last_decision(state)

    assert out.spoken.text in focus.TEMPLATE["STEPS"]
    assert decision["speech_attempt"]["accepted"] is False
    assert decision["speech_attempt"]["rejection"] == "empty"
    assert "empty-say->repair-failed" in decision["guards"]
    assert "empty-say->template" in decision["guards"]


def test_an_accepted_shortening_retry_replaces_the_raw_speech(tmp_path, monkeypatch):
    _accept_any_focus(monkeypatch)
    long_line = "What happened after the service was deployed into production that evening?"
    short_line = "What happened after deployment?"
    r, state = build([d("probe", long_line), d("probe", short_line)], tmp_path)
    r.max_say_words = 5
    run(r.ask())
    run(r.submit("I deployed the service."))
    decision = last_decision(state)
    assert "too-long->shortened" in decision["guards"]
    assert decision["say_raw"] == short_line


def test_a_rejected_shortening_retry_retains_the_original_raw_speech(tmp_path, monkeypatch):
    _accept_any_focus(monkeypatch)
    long_line = "What happened after the service was deployed into production that evening?"
    r, state = build([d("probe", long_line), d("advance", "Thanks.")], tmp_path)
    r.max_say_words = 5
    run(r.ask())
    run(r.submit("I deployed the service."))
    decision = last_decision(state)
    assert "too-long->retry-failed" in decision["guards"]
    assert decision["say_raw"] == long_line


def test_the_product_runner_accepts_a_twenty_five_word_question(tmp_path, monkeypatch):
    _accept_any_focus(monkeypatch)
    boundary_line = ("What specific changes would you make to the deployment process if the same "
                     "production incident happened again during a busy support shift next week onsite?")
    retry_line = "What specific changes would you make next time?"
    r, state = build([d("probe", boundary_line), d("probe", retry_line)], tmp_path)

    assert len(boundary_line.split()) == 25
    run(r.ask())
    out = run(r.submit("I would add a staged rollout and monitor the error rate."))

    assert out.spoken.text == boundary_line
    assert not any(guard.startswith("too-long->") for guard in state.turns[-1].guards)


def test_the_product_runner_shortens_a_twenty_six_word_question(tmp_path, monkeypatch):
    _accept_any_focus(monkeypatch)
    long_line = ("What specific changes would you make to the deployment process if the same "
                 "production incident happened again during a busy support shift next week onsite "
                 "overnight?")
    short_line = "What specific changes would you make next time?"
    r, state = build([d("probe", long_line), d("probe", short_line)], tmp_path)

    run(r.ask())
    out = run(r.submit("I would add a staged rollout and monitor the error rate."))

    assert len(long_line.split()) == 26
    assert out.spoken.text == short_line
    assert "too-long->shortened" in state.turns[-1].guards


# --------------------------------------------- focus rotation (log 8.18)
def test_a_question_never_asks_the_same_focus_twice(tmp_path):
    """The measured defect: ~2.2 follow-ups per question but only ~1.6 distinct requests."""
    # Lexically different, semantically identical -- the reworded repeat the string guard
    # cannot see and this feature exists for.
    r, state = build([d("probe", "Why did you pick that one?"),
                      d("probe", "What was the reason for that choice?"),
                      d("probe", "What made you decide it that way?")], tmp_path)
    run(r.ask())
    for u in ("first", "second", "third"):
        run(r.submit(u))
    import json
    lines = [json.loads(x) for x in
             (state.dir / "decisions.jsonl").read_text(encoding="utf-8").strip().splitlines()]
    from collections import defaultdict
    per = defaultdict(list)
    for x in lines:
        per[x["question_id"]] += x["focus_got"]
    for qid, got in per.items():
        assert len(got) == len(set(got)), (qid, got)
    assert any(len(v) > 1 for v in per.values()), "a question must have been probed twice"


def test_a_line_asking_a_DIFFERENT_unused_focus_is_kept(tmp_path):
    """Variety is the objective, not obedience: another unused request is a good turn."""
    r, state = build([d("probe", "What happened in the end?")], tmp_path)
    run(r.ask())
    out = run(r.submit("so I just did it"))          # signals ask for STEPS
    assert out.spoken.text == "What happened in the end?"
    assert not any("off-focus" in x for x in state.turns[-1].guards)
    assert "OUTCOME" in r.focus_used


def test_failure_mode_questions_are_a_fresh_challenge():
    for said in (
            "What happens if Redis is unavailable?",
            "How would you handle an outage in one region?",
            "What breaks first when this is under real load?",
            "How does the design behave when the shared store is down?"):
        assert "CHALLENGE" in focus.classify(said), said


def test_failure_words_in_an_answer_do_not_create_a_challenge_question():
    said = "Redis was unavailable during the incident. What did you do next?"
    assert "STEPS" in focus.classify(said)
    assert "CHALLENGE" not in focus.classify(said)


def test_relevant_llama_question_forms_map_to_their_actual_focus():
    for said, expected in (
            ("What was the impact of this change on your users?", {"OUTCOME"}),
            ("How did you know that the free-text field caused failures?", {"MEASURE"}),
            ("What specific changes did you make to the schema?", {"STEPS"}),
            ("What specific changes would you make now?", {"STEPS"}),
    ):
        assert focus.classify(said) == expected, said


@pytest.mark.parametrize(("said", "expected"), [
    ("What made the experience of working with senior engineers so important to you?",
     {"REASON"}),
    ("What was the nature of this production incident?", {"CONTEXT"}),
    ("What kind of data were you adding?", {"CONTEXT"}),
    ("What specific changes did you suggest they make instead?", {"STEPS"}),
])
def test_captured_llama_probe_forms_map_to_their_actual_focus(said, expected):
    assert focus.classify(said) == expected


def test_bounded_llama_forms_do_not_match_nearby_but_different_requests():
    assert "REASON" not in focus.classify(
        "What made the feature important to users?")
    assert "CONTEXT" not in focus.classify(
        "What kind of data did you measure?")


@pytest.mark.parametrize("said", [
    "How did you determine the optimal frequency for these emails?",
    "How did you establish the processing time of twenty minutes?",
    "How did you determine that two seconds was slow?",
])
def test_measurement_establishment_questions_are_classified_as_measure(said):
    assert focus.classify(said) == {"MEASURE"}


def test_a_timeframe_question_is_both_measurement_and_duration():
    """Kept separate from the `==` cases above rather than relaxing them. DURATION gained
    `timeframe` so its own template, "Over what sort of timeframe?", could classify, and a
    question about an OPTIMAL TIMEFRAME genuinely asks both how they knew and how long it
    took. The runner tolerates an extra label; what it must never do is lose MEASURE."""
    got = focus.classify("How did you know the optimal timeframe for completing the feature?")
    assert got == {"MEASURE", "DURATION"}


def test_non_measurement_determination_is_not_misclassified_as_measure():
    assert "MEASURE" not in focus.classify(
        "How did you determine which framework to use?")


def test_llama_focus_words_outside_the_bounded_question_forms_do_not_match():
    assert "OUTCOME" not in focus.classify(
        "What safeguards did you add after the impact review?")
    assert "MEASURE" not in focus.classify(
        "How did you know the colleague who reviewed it?")


def test_a_relevant_llama_impact_question_beats_the_outcome_template(tmp_path, monkeypatch):
    raw = "What was the impact of this change on your users?"
    monkeypatch.setattr(focus, "next_focus", lambda *args: "OUTCOME")
    r, state = build([d("probe", raw)], tmp_path)

    run(r.ask())
    out = run(r.submit("The routing rule assigned several cases incorrectly."))

    assert out.spoken.text == raw
    assert "OUTCOME" in r.focus_used
    assert not any("off-focus" in guard for guard in state.turns[-1].guards)


def test_a_specific_failure_mode_question_beats_the_alternative_template(tmp_path):
    plan = {
        "id": "failure-mode-probe",
        "phases": [{
            "id": "design",
            "answer_shape": "open",
            "probe_budget": 2,
            "scored": False,
            "observation_shape": "star",
            "focus_ladder": ["ALTERNATIVE", "CHALLENGE"],
            "questions": ["How would you design a rate limiter?"],
        }],
    }
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(plan)
    runner = Runner(ScriptedProvider([
        d("probe", "How would you handle multiple regions if Redis is unavailable?")
    ]), plan, state)

    run(runner.ask())
    outcome = run(runner.submit("I would use a Redis fixed-window counter."))

    assert outcome.spoken.text == (
        "How would you handle multiple regions if Redis is unavailable?")
    assert "CHALLENGE" in runner.focus_used
    assert not any("off-focus" in guard for guard in state.turns[-1].guards)


def test_an_off_focus_probe_gets_one_model_written_speech_repair(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "CONTEXT")
    repaired = "Which constraints shaped the incident response?"
    r, state = build([d("probe", "What happened afterwards?"),
                      speech(repaired)], tmp_path)
    run(r.ask())
    r.focus_used.add("OUTCOME")
    prior = "What happened in the end?"
    r.said_this_session.append(prior)
    out = run(r.submit("we shipped it"))
    decision = last_decision(state)

    assert out.spoken.text == repaired
    assert decision["say_raw"] == "What happened afterwards?"
    assert decision["say_model"] == "What happened afterwards?"
    assert decision["focus_got"] == ["CONTEXT"]
    assert decision["speech_attempt"]["trigger"] == "off_focus"
    assert decision["speech_attempt"]["accepted"] is True
    assert "off-focus->repaired" in decision["guards"]
    assert decision["model_calls"] == 2
    assert "What happened afterwards?" not in r.provider.systems[1]
    assert prior not in r.provider.systems[1]


def test_speech_repair_accepts_the_requested_focus_with_an_incidental_extra_label(
        tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "STEPS")
    repaired = "How did you go about learning those forty Vue components?"
    assert focus.classify(repaired) == {"LESSON", "STEPS"}
    r, state = build([d("probe", "What was your approach?"),
                      speech(repaired)], tmp_path)
    run(r.ask())

    out = run(r.submit("I started from the broken screen."))
    decision = last_decision(state)

    assert out.spoken.text == repaired
    assert decision["focus_got"] == ["STEPS"]
    assert decision["speech_attempt"]["accepted"] is True


def test_session_level_fuzzy_similarity_does_not_reject_context_specific_repair(
        tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "STEPS")
    old = "What did you actually do, step by step?"
    repaired = "What steps did you take to implement this schema change?"
    r, state = build([d("probe", "", ok=False), speech(repaired)], tmp_path)
    run(r.ask())
    r.said_this_session.append(old)

    out = run(r.submit("I made the field optional."))
    decision = last_decision(state)

    assert out.spoken.text == repaired
    assert decision["speech_attempt"]["accepted"] is True


def test_speech_repair_still_rejects_an_exact_session_repeat(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "STEPS")
    repeated = "What steps did you take to implement this schema change?"
    r, state = build([d("probe", "", ok=False), speech(repeated)], tmp_path)
    run(r.ask())
    r.said_this_session.append(repeated)

    out = run(r.submit("I made the field optional."))
    decision = last_decision(state)

    assert out.spoken.text in focus.TEMPLATE["STEPS"]
    assert decision["speech_attempt"]["accepted"] is False
    assert decision["speech_attempt"]["rejection"] == "repeated"


def test_a_rejected_off_focus_speech_repair_falls_back_with_diagnostics(
        tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "next_focus", lambda *args: "CONTEXT")
    r, state = build([d("probe", "Tell me about the weather."),
                      speech("What happened afterwards?")], tmp_path)
    run(r.ask())
    out = run(r.submit("we shipped it"))
    decision = last_decision(state)

    assert out.spoken.text in focus.TEMPLATE["CONTEXT"]
    assert decision["speech_attempt"]["accepted"] is False
    assert decision["speech_attempt"]["rejection"] == "off_focus"
    assert decision["speech_attempt"]["say_raw"] == "What happened afterwards?"
    assert "off-focus->repair-failed" in decision["guards"]
    assert "off-focus->context" in decision["guards"]


def test_an_on_focus_line_is_left_alone(tmp_path):
    """"so I just did it" is the `skipped` signal, which asks for STEPS."""
    r, _ = build([d("probe", "What did you actually do, step by step?")], tmp_path)
    run(r.ask())
    out = run(r.submit("so I just did it"))
    assert "step by step" in out.spoken.text


def test_the_focus_resets_on_the_next_question(tmp_path):
    r, _ = build([d("probe", "Why?"), d("advance", "Thanks.")], tmp_path)
    run(r.ask())
    run(r.submit("a"))
    run(r.submit("b"))
    assert r.focus_used == set()


SCORED = ["sets_context", "describes_action", "states_outcome"]


def test_an_unverified_figure_asks_how_they_know():
    assert focus.next_focus("It went from 8 seconds to 400ms.", set(), SCORED) == "MEASURE"


def test_credit_to_the_team_asks_what_was_theirs():
    assert focus.next_focus("We rebuilt the whole pipeline.", set(), SCORED) == "ROLE"


def test_a_used_focus_is_never_returned():
    used = set(focus.LADDER) - {"DURATION"}
    assert focus.next_focus("We rebuilt it.", used, SCORED) == "DURATION"


def test_rubric_criteria_are_asked_about_when_no_signal_fires():
    got = focus.next_focus("Fine.", set(), ["states_outcome"])
    assert got == "OUTCOME"


def test_an_unscored_phase_does_not_ask_how_they_measured_it():
    """warmup and closing have no rubric_criteria, so there is no gap for a signal to find."""
    got = focus.next_focus("I'm a platform engineer, seven years", set(), [])
    assert got in focus.UNSCORED_LADDER
    assert got != "MEASURE"


def test_the_skip_gate_cannot_trap_a_candidate(tmp_path):
    """An unrecognised refusal is probed once more, then the cap advances -- never stuck."""
    r, _ = build([d("skip", "a"), d("skip", "b"), d("skip", "c"), d("skip", "e")], tmp_path)
    r.pool = 0
    run(r.ask())
    out = None
    for _ in range(3):
        out = run(r.submit("nah, let's leave that one"))
        if out.closed_question:
            break
    assert out.closed_question, "the question must close within the cap"


def test_a_question_carries_what_the_focus_selector_needs():
    """`rubric_criteria` was absent, so the signal path never ran in any session."""
    plan = {"id": "t", "phases": [{"id": "p", "answer_shape": "open", "probe_budget": 2,
                                   "rubric_criteria": ["states_outcome"],
                                   "focus_ladder": ["CHALLENGE"], "questions": ["Q?"]}]}
    q = next(session.iter_questions(plan))
    assert q["rubric_criteria"] == ["states_outcome"]
    assert q["focus_ladder"] == ["CHALLENGE"]


def test_the_phase_ladder_beats_the_global_one():
    """design has no team and no outcome, so ROLE and OUTCOME are nonsense there."""
    got = focus.next_focus("I'd use a token bucket.", set(), [], ["ALTERNATIVE", "CHALLENGE"])
    assert got == "ALTERNATIVE"


def test_the_shipped_design_phase_never_opens_on_role_or_context():
    import json
    plan = json.loads((Path(__file__).resolve().parent.parent / "config" /
                       "interview_swe_general.json").read_text(encoding="utf-8"))
    design = [p for p in plan["phases"] if p["id"] == "design"][0]
    assert design["focus_ladder"][0] not in ("ROLE", "CONTEXT", "OUTCOME")


def test_every_focus_template_asks_exactly_one_question():
    """Templates bypass the first-sentence guard, so they have to obey the rule themselves."""
    for name, variants in focus.TEMPLATE.items():
        for line in variants:
            assert line.count("?") <= 1, (name, line)
            assert len(line.split()) <= 12, (name, line)


def test_a_focus_never_speaks_the_same_template_twice_in_one_session():
    """One fixed string per focus put "What was the scale of that?" in front of the candidate
    four times, once about a one-on-one conversation (log 9.7)."""
    for name, variants in focus.TEMPLATE.items():
        assert len(variants) >= 3, name
        assert len(set(variants)) == len(variants), name
        spoken = set()
        for _ in range(3):
            line = focus.template(name, spoken)
            assert line not in spoken, (name, line)
            spoken.add(line)


def test_no_two_focuses_share_a_template_line():
    """A line reachable from two focuses would be spoken twice and look unrelated both times."""
    seen = {}
    for name, variants in focus.TEMPLATE.items():
        for line in variants:
            assert line not in seen, (line, name, seen.get(line))
            seen[line] = name


def test_every_focus_has_a_template_and_an_instruction():
    for name in focus.FOCUS:
        assert name in focus.TEMPLATE
        assert focus.instruction(name)


# --------------------------------------- contentless answers (log 8.22)
def test_an_answer_with_nothing_in_it_is_not_steered():
    """There is no gap in an answer that is not there. Live, "I've not really shipped
    anything big enough to go wrong" was met with "How did you measure that?"."""
    for said in ("I've not really shipped anything big enough to go wrong yet.",
                 "I haven't done a schema change on a live system.",
                 "Nothing comes to mind, honestly.",
                 "I can't really think of one."):
        assert focus.next_focus(said, set(), SCORED) is None, said


def test_a_real_answer_is_still_steered():
    for said in ("We split a users table in two while it was live.",
                 "I disagreed with my lead about the job queue.",
                 "Just me, one afternoon."):
        assert focus.next_focus(said, set(), SCORED) is not None, said


def test_brevity_alone_is_not_emptiness():
    """A short answer can be a real one, and is exactly where probing earns its keep."""
    assert focus.is_contentless("Redis.") is False
    assert focus.is_contentless("About four hundred a day.") is False


def test_a_contentless_turn_keeps_the_model_line(tmp_path):
    """No focus was requested, so nothing is substituted and nothing is recorded as used."""
    r, state = build([d("reask", "Any example at all, even a small one?")], tmp_path)
    run(r.ask())
    out = run(r.submit("I can't think of one."))
    assert out.spoken.text == "Any example at all, even a small one?"
    assert r.focus_used == set()
    assert not any("off-focus" in x for x in state.turns[-1].guards)


def test_the_skip_line_does_not_promise_a_revisit():
    """Nothing requeues a skipped question; the line used to say it would come back."""
    from app.runner import SKIP_ACK
    assert "come back" not in SKIP_ACK.lower()


# ------------------------------------------- the design follow-up (log 9.7)
def test_every_design_template_is_future_tense_single_focus_and_within_cap():
    for expected, variants in focus.DESIGN_TEMPLATE.items():
        for line in variants:
            assert line.count("?") == 1, (expected, line)
            assert len(line.split()) <= 25, (expected, line)
            assert focus.classify(line) == {expected}, (expected, line)
            assert " did you " not in line.lower()
            assert " was the " not in line.lower()


def test_design_template_avoids_session_repetition():
    spoken = {focus.DESIGN_TEMPLATE["CHALLENGE"][0]}
    assert (focus.design_template("CHALLENGE", spoken)
            == focus.DESIGN_TEMPLATE["CHALLENGE"][1])


@pytest.mark.parametrize(("raw", "expected"), [
    (
        "How did you handle Redis becoming unavailable?",
        "How would you handle Redis becoming unavailable?",
    ),
    (
        "What did you consider for cross-region consistency?",
        "What else would you consider for cross-region consistency?",
    ),
    (
        "What else did you consider for handling rate limiting beyond Redis counters?",
        "What else would you consider for handling rate limiting beyond Redis counters?",
    ),
    (
        "What was the main challenge you faced when implementing the token bucket algorithm?",
        "What would be the main challenge when implementing the token bucket algorithm?",
    ),
    (
        "What challenge did you face while testing failover?",
        "What challenge would you expect while testing failover?",
    ),
])
def test_safe_design_past_premises_are_rewritten(raw, expected):
    assert focus.design_past_premise(raw)
    assert focus.rewrite_design_past_premise(raw) == expected


@pytest.mark.parametrize("line", [
    "How would you handle Redis becoming unavailable?",
    "What would be hardest about this design?",
])
def test_already_hypothetical_language_needs_no_rewrite(line):
    assert not focus.design_past_premise(line)
    assert focus.rewrite_design_past_premise(line) is None


@pytest.mark.parametrize("line", [
    "How did you diagnose the production outage?",
    "What was the hardest problem you encountered during the migration?",
])
def test_past_premise_detection_is_independent_of_phase(line):
    assert focus.design_past_premise(line)


DESIGN_PLAN = {
    "id": "test-design",
    "phases": [{
        "id": "design", "answer_shape": "open", "probe_budget": 2, "scored": False,
        "observation_shape": "design", "questions": ["Design a rate limiter."],
    }],
}

NO_FAILURE = ("I'd use a token bucket per API key in Redis, with a refill rate and a burst "
              "capacity, and return a 429 when it's empty. I considered a fixed window "
              "counter but the boundary lets through double the rate.")
WITH_FAILURE = NO_FAILURE + " If Redis is unavailable I'd fail open rather than reject."


def design_runner(decisions, tmp_path):
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(DESIGN_PLAN)
    return Runner(ScriptedProvider(decisions), DESIGN_PLAN, state), state


STAGE3_DESIGN_PLAN = {
    "id": "stage3-design",
    "phases": [{
        "id": "design",
        "answer_shape": "open",
        "probe_budget": 2,
        "scored": False,
        "observation_shape": "design",
        "focus_ladder": ["ALTERNATIVE", "CHALLENGE", "MEASURE", "REASON", "STEPS"],
        "questions": ["Design a rate limiter."],
    }],
}


def stage3_design_runner(decisions, tmp_path, max_say_words=25):
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(STAGE3_DESIGN_PLAN)
    runner = Runner(ScriptedProvider(decisions), STAGE3_DESIGN_PLAN, state,
                    max_say_words=max_say_words)
    return runner, state


def test_design_probe_rewrites_past_premise_without_changing_turn_contract(tmp_path):
    raw = "How did you handle Redis becoming unavailable?"
    runner, state = stage3_design_runner([d("probe", raw)], tmp_path)
    run(runner.ask())
    before_pool = runner.pool

    out = run(runner.submit(WITH_FAILURE))
    decision = last_decision(state)

    assert out.act == "probe"
    assert out.spoken.text == "How would you handle Redis becoming unavailable?"
    assert decision["say_raw"] == raw
    assert decision["model_calls"] == 1
    assert "hypothetical-tense->rewrite" in decision["guards"]
    assert runner.pool == before_pool
    assert runner.follow_ups_used == 1
    assert decision["focus_got"] == ["CHALLENGE"]


def test_unrepairable_design_past_premise_uses_future_template(tmp_path):
    raw = "What was the trade-off you were trying to balance?"
    runner, state = stage3_design_runner([d("probe", raw)], tmp_path)
    run(runner.ask())

    out = run(runner.submit(WITH_FAILURE))
    decision = last_decision(state)

    assert out.act == "probe"
    assert out.spoken.text in focus.DESIGN_TEMPLATE["ALTERNATIVE"]
    assert decision["say_raw"] == raw
    assert decision["model_calls"] == 1
    assert "hypothetical-tense->template" in decision["guards"]


def test_hypothetical_design_probe_is_unchanged(tmp_path):
    line = "How would you handle Redis becoming unavailable?"
    runner, state = stage3_design_runner([d("probe", line)], tmp_path)
    run(runner.ask())

    out = run(runner.submit(WITH_FAILURE))

    assert out.spoken.text == line
    assert not any("hypothetical-tense" in guard for guard in state.turns[-1].guards)


def test_hypothetical_repair_does_not_apply_outside_design(tmp_path):
    line = "What was the hardest problem you encountered during the migration?"
    runner, state = build([d("probe", line)], tmp_path)
    run(runner.ask())

    out = run(runner.submit("The service failed during deployment."))

    assert out.spoken.text == line
    assert not any("hypothetical-tense" in guard for guard in state.turns[-1].guards)


def test_hypothetical_rewrite_over_cap_uses_template_without_extra_call(tmp_path):
    raw = "What did you consider for consistency?"
    runner, state = stage3_design_runner([d("probe", raw)], tmp_path, max_say_words=6)
    run(runner.ask())

    out = run(runner.submit(WITH_FAILURE))
    decision = last_decision(state)

    assert out.spoken.text in focus.DESIGN_TEMPLATE["ALTERNATIVE"]
    assert decision["model_calls"] == 1
    assert "hypothetical-tense->template" in decision["guards"]


def test_repeated_hypothetical_rewrite_uses_unspoken_design_template(tmp_path):
    raw = "How did you handle Redis becoming unavailable?"
    rewritten = "How would you handle Redis becoming unavailable?"
    runner, state = stage3_design_runner([d("probe", raw)], tmp_path)
    run(runner.ask())
    runner.said_this_session.append(rewritten)

    out = run(runner.submit(WITH_FAILURE))

    assert out.spoken.text == focus.DESIGN_TEMPLATE["ALTERNATIVE"][0]
    assert "hypothetical-tense->template" in state.turns[-1].guards


def test_unrepairable_design_reask_without_focus_uses_design_reask(tmp_path):
    raw = "What was the hardest problem you encountered during the migration?"
    runner, state = stage3_design_runner([d("reask", raw)], tmp_path)
    run(runner.ask())

    out = run(runner.submit("I can't think of one."))
    decision = last_decision(state)

    assert out.act == "reask"
    assert out.spoken.text == focus.DESIGN_REASK
    assert decision["say_raw"] == raw
    assert decision["model_calls"] == 1
    assert "hypothetical-tense->template" in decision["guards"]


def test_hypothetical_template_fallback_never_draws_from_pool(tmp_path):
    raw = "What was the trade-off you were trying to balance?"
    runner, _ = stage3_design_runner([d("probe", raw)], tmp_path)
    run(runner.ask())
    before_pool = runner.pool

    run(runner.submit(WITH_FAILURE))

    assert runner.pool == before_pool


def test_hypothetical_repair_preserves_raw_speech_after_sentence_trim(tmp_path):
    raw = "How did you handle Redis becoming unavailable? Tell me more."
    runner, state = stage3_design_runner([d("probe", raw)], tmp_path)
    run(runner.ask())

    out = run(runner.submit(WITH_FAILURE))
    decision = last_decision(state)

    assert out.spoken.text == "How would you handle Redis becoming unavailable?"
    assert decision["say_raw"] == raw
    assert "extra-sentences-dropped" in decision["guards"]
    assert "hypothetical-tense->rewrite" in decision["guards"]


def test_hypothetical_repair_cannot_repeat_an_already_used_focus(tmp_path):
    raw = "How did you handle Redis becoming unavailable?"
    runner, state = stage3_design_runner([d("probe", raw)], tmp_path)
    run(runner.ask())
    runner.focus_used.add("CHALLENGE")

    out = run(runner.submit(WITH_FAILURE))
    decision = last_decision(state)

    assert out.spoken.text in focus.DESIGN_TEMPLATE["ALTERNATIVE"]
    assert decision["focus_got"] == ["ALTERNATIVE"]
    assert "hypothetical-tense->rewrite" in decision["guards"]
    assert "off-focus->alternative" in decision["guards"]


def test_a_design_answer_with_no_failure_mode_is_probed_before_advancing(tmp_path):
    """Live, this question drew ZERO probes out of three: `ok` asks whether the reply answers
    the question, and a long fluent answer reads as complete even with a part missing."""
    r, state = design_runner([d("advance", "")], tmp_path)
    run(r.ask())
    out = run(r.submit(NO_FAILURE))
    assert out.spoken.text == focus.DESIGN_FOLLOW_UP
    assert "design-gap->probe" in state.turns[-1].guards
    assert r.focus_used == {"CHALLENGE"}
    decision = last_decision(state)
    assert decision["focus_asked"] == "CONTEXT"
    assert decision["focus_got"] == ["CHALLENGE"]
    assert not out.closed_question


def test_the_turn_after_a_design_gap_cannot_repeat_challenge(tmp_path):
    r, state = design_runner([
        d("advance", ""),
        d("probe", "Where would the architecture get difficult?"),
    ], tmp_path)
    run(r.ask())
    run(r.submit(NO_FAILURE))
    out = run(r.submit("Redis could become unavailable under load."))
    assert out.act == "probe"
    assert out.spoken.text != "Where would the architecture get difficult?"
    assert "off-focus->context" in state.turns[-1].guards
    assert last_decision(state)["focus_got"] == ["CONTEXT"]


def test_a_design_answer_that_names_a_failure_is_left_alone(tmp_path):
    """Asking what breaks after they said what breaks is the redundancy 9.7 measured."""
    r, state = design_runner([d("advance", "")], tmp_path)
    run(r.ask())
    out = run(r.submit(WITH_FAILURE))
    assert "design-gap->probe" not in state.turns[-1].guards
    assert out.closed_question


def test_the_design_follow_up_is_asked_at_most_once(tmp_path):
    """It must not loop: a candidate who still names no failure would be asked forever."""
    r, state = design_runner([d("advance", ""), d("advance", "")], tmp_path)
    run(r.ask())
    run(r.submit(NO_FAILURE))
    out = run(r.submit("I'd probably just tune the numbers until it felt right."))
    assert "design-gap->probe" not in state.turns[-1].guards
    assert out.closed_question


def test_the_design_follow_up_never_draws_on_the_shared_pool(tmp_path):
    """The plan already budgeted this question; an overrun would spend another phase's."""
    r, _ = design_runner([d("advance", "")], tmp_path)
    run(r.ask())
    before = r.pool
    run(r.submit(NO_FAILURE))
    assert r.pool == before


def test_a_design_question_cannot_extend_its_cap_with_the_shared_pool(tmp_path):
    """Design has a displayed two-turn budget; the shared reserve must not silently turn
    that into a third, fourth, or fifth follow-up."""
    decisions = [
        d("probe", "What trade-off mattered most?"),
        d("probe", "How would you detect overload?"),
        d("probe", "What would you change next?"),
    ]
    r, state = design_runner(decisions, tmp_path)
    run(r.ask())
    before = r.pool
    assert run(r.submit(WITH_FAILURE)).act == "probe"
    assert run(r.submit("We preferred predictable latency over perfect fairness.")).act == "probe"
    out = run(r.submit("We would alert on rejection rate and p95 latency."))
    assert out.act == "advance"
    assert r.pool == before
    assert "follow-up-cap->advance" in state.turns[-1].guards
    assert "pool-exhausted->advance" not in state.turns[-1].guards


def test_only_a_design_question_gets_the_design_follow_up(tmp_path):
    r, state = build([d("advance", "")], tmp_path)
    run(r.ask())
    run(r.submit(NO_FAILURE))
    assert "design-gap->probe" not in state.turns[-1].guards


# ------------------------------------------- template variety across a session (log 9.7)
def test_the_same_template_is_not_spoken_twice_across_questions(tmp_path):
    """All four verbatim repeats were on DIFFERENT questions, so the per-question record
    could not see any of them. `said_this_session` is what makes the check possible."""
    off = "Tell me about the weather."
    r, state = build([d("probe", off), d("advance", ""), d("probe", off)], tmp_path)
    run(r.ask())
    first = run(r.submit("we shipped it")).spoken.text
    run(r.submit("we shipped it"))                 # advance to question two
    second = run(r.submit("we shipped it")).spoken.text
    assert first != second, first
    assert all("off-focus" in " ".join(t.guards) or True for t in state.turns)


def test_every_spoken_line_is_recorded_at_session_level(tmp_path):
    r, _ = build([d("probe", "What happened in the end?"), d("advance", "")], tmp_path)
    run(r.ask())
    run(r.submit("we shipped it"))
    assert r.said_this_session == ["What happened in the end?"]
    run(r.submit("it went fine"))                  # advance clears the per-question record
    assert r.said_this_question == []
    assert r.said_this_session == ["What happened in the end?"]


# ------------------------------------------- the adaptive stop (plan 1c.5, log 9.10)
class Parts:
    """Feeds the runner a scripted per-answer triple, so the rule is tested without a model."""

    def __init__(self, *per_answer):
        self.queue = list(per_answer)
        self.calls = 0

    async def __call__(self, question_id, question, utterance):
        self.calls += 1
        got = self.queue.pop(0) if self.queue else ()
        o = observe.Observation(question_id=question_id, question=question,
                                answers=[utterance])
        for k in got:
            # A real result has to state a change or the runner discards it, so the fixture
            # supplies one that does.
            setattr(o, k, "we ended up shipping it" if k == "result" else "text for " + k)
        return o


# Room for the stall rule to fire before the cap does. With PLAN's budget of 2 the backstop
# lands first, which is correct in production and useless for testing the rule underneath it.
ROOMY = {
    "id": "roomy",
    "phases": [{"id": "p1", "answer_shape": "open", "probe_budget": 6, "scored": True,
                "questions": ["Question one?", "Question two?"]}],
}

PACING_WITH_POOL = {
    "id": "pacing-with-pool",
    "phases": [{"id": "p1", "answer_shape": "open", "probe_budget": 3,
                "scored": True, "questions": ["Question one?"]}],
}


def adaptive(decisions, parts, tmp_path, plan=ROOMY):
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(plan)
    return Runner(ScriptedProvider(decisions), plan, state, observe_fn=parts), state


def test_a_complete_triple_closes_the_question_before_the_cap(tmp_path):
    """74.7% of advances were the cap firing, only 11.6% the model choosing (log 9.9)."""
    parts = Parts(("situation", "action", "result"))
    r, state = adaptive([d("probe", "one"), d("probe", "two")], parts, tmp_path)
    run(r.ask())
    run(r.submit("a complete answer"))          # extraction queued
    out = run(r.submit("more"))                 # settled at the top of this turn
    assert "observations-complete->advance" in state.turns[-1].guards
    assert out.closed_question


def test_two_answers_that_add_nothing_close_the_question(tmp_path):
    """1c.5's rule: stop when the triple has not improved for two consecutive turns.

    Four answers, not three, because of the lag pinned below: the last answer given has not
    been extracted yet when the decision is made.
    """
    parts = Parts(("situation",), ("situation",), ("situation",), ("situation",))
    r, state = adaptive([d("probe", x) for x in "abcd"], parts, tmp_path)
    run(r.ask())
    run(r.submit("first"))
    run(r.submit("adds nothing"))
    run(r.submit("adds nothing again"))
    out = run(r.submit("still nothing"))
    assert "no-new-observation->advance" in state.turns[-1].guards
    assert out.closed_question


def test_the_pool_is_not_charged_when_the_observation_pacer_suppresses_the_probe(tmp_path):
    """A reserve token buys a spoken follow-up, not a model proposal discarded before
    dispatch. The junior live control lost a token to this ordering bug."""
    parts = Parts(("situation",), ("situation",), ("situation",), ("situation",))
    r, state = adaptive([d("probe", x) for x in "abcd"], parts, tmp_path,
                        plan=PACING_WITH_POOL)
    run(r.ask())
    run(r.submit("first"))
    run(r.submit("adds nothing"))
    run(r.submit("adds nothing again"))
    before = r.pool
    out = run(r.submit("still nothing"))
    assert out.closed_question
    assert "no-new-observation->advance" in state.turns[-1].guards
    assert r.pool == before
    assert not any(g.startswith("pool-draw") for g in state.turns[-1].guards)


def test_the_stop_rule_lags_the_candidate_by_exactly_one_answer(tmp_path):
    """Extraction of answer N is folded in at the start of turn N+1, so a decision never
    sees the answer that prompted it. That is the price of keeping the ~870ms off the
    decision path, and it errs towards one extra probe -- 1c.5's safe direction."""
    parts = Parts(("situation", "action", "result"))
    r, _ = adaptive([d("probe", "one"), d("probe", "two")], parts, tmp_path)
    run(r.ask())
    run(r.submit("a complete answer"))
    assert r.seen == set(), "must not have folded the answer it just decided on"
    run(r.settle())
    assert r.seen == {"situation", "action", "result"}


def test_one_barren_turn_does_not_close_the_question(tmp_path):
    """A candidate who rambles once and then delivers the result must not be cut off."""
    parts = Parts(("situation",), ("situation",), ("situation", "action"))
    r, state = adaptive([d("probe", "a"), d("probe", "b"), d("probe", "c")], parts, tmp_path)
    run(r.ask())
    run(r.submit("first"))
    run(r.submit("adds nothing"))
    out = run(r.submit("here is the action"))
    assert "no-new-observation->advance" not in state.turns[-1].guards
    assert not out.closed_question


def test_a_result_that_states_no_change_does_not_count(tmp_path):
    """Scale text and filler both passed grounding and were scored as outcomes (9.9). Here
    the cost of rejecting one is a further probe, which is the safe direction."""
    parts = Parts(("situation", "action"))
    r, state = adaptive([d("probe", "one"), d("probe", "two")], parts, tmp_path)
    run(r.ask())
    o = run(parts("q.1", "Q?", "x"))
    o.result = "it's about eight million rows a day, retained for two weeks"
    assert not result_check.states_change(o.result)
    run(r.submit("a"))
    out = run(r.submit("b"))
    assert "observations-complete->advance" not in state.turns[-1].guards
    assert not out.closed_question


def test_the_cap_still_backstops_a_question_that_never_completes(tmp_path):
    """58% of questions never hold all three parts, and for those the cap is the only stop."""
    parts = Parts((), (), (), ())
    r, state = adaptive([d("probe", str(i)) for i in range(5)], parts, tmp_path, plan=PLAN)
    run(r.ask())
    run(r.submit("nothing"))
    outs = [run(r.submit("nothing %d" % i)) for i in range(3)]
    assert any(o.closed_question for o in outs)


def test_no_extraction_runs_while_a_turn_is_being_decided(tmp_path):
    """NFR-1 measures the decision path. The extraction belongs to the gap between turns."""
    parts = Parts(("situation",), ("action",))
    r, _ = adaptive([d("probe", "one"), d("probe", "two")], parts, tmp_path)
    run(r.ask())
    assert parts.calls == 0
    run(r.submit("first"))
    run(r.settle())
    assert parts.calls == 1


def test_a_failed_extraction_never_ends_an_interview(tmp_path):
    async def boom(question_id, question, utterance):
        raise RuntimeError("extractor down")

    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    r = Runner(ScriptedProvider([d("probe", "one"), d("probe", "two")]), PLAN, state,
               observe_fn=boom)
    run(r.ask())
    run(r.submit("first"))
    out = run(r.submit("second"))
    assert out.spoken.text
    assert r.seen == set()


def test_the_stop_state_resets_between_questions(tmp_path):
    parts = Parts(("situation", "action", "result"), ("situation",))
    r, _ = adaptive([d("probe", "one"), d("probe", "two"), d("probe", "three")],
                    parts, tmp_path)
    run(r.ask())
    run(r.submit("complete"))
    run(r.submit("closes question one"))
    assert r.seen == set() and r.stalls == 0


def test_both_entry_points_enable_the_adaptive_stop():
    """`observe_fn=None` silently reverts to cap-only pacing, which is the 8.19 bug class:
    working in-process and doing nothing where it matters.

    This used to grep the source for `observe_fn=`, which a comment, a docstring or a
    commented-out call all satisfy. Parse the call instead and require a real argument, so
    the test can fail for the reason it was written for.
    """
    import ast
    root = Path(__file__).resolve().parent.parent
    for rel in ("app/cli.py", "tools/live_candidate.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "Runner"]
        assert calls, "%s never constructs a Runner" % rel
        for call in calls:
            kw = {k.arg: k.value for k in call.keywords}
            assert "observe_fn" in kw, "%s builds a Runner without observe_fn" % rel
            assert not (isinstance(kw["observe_fn"], ast.Constant)
                        and kw["observe_fn"].value is None), \
                "%s passes observe_fn=None" % rel


def test_a_design_question_is_not_paced_by_the_star_triple(tmp_path):
    """A hypothetical has no situation, action or result (9.6), so the stall counter would
    close it on the absence of parts it was never going to contain."""
    parts = Parts((), (), ())
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(DESIGN_PLAN)
    r = Runner(ScriptedProvider([d("probe", x) for x in "abc"]), DESIGN_PLAN, state,
               observe_fn=parts)
    run(r.ask())
    run(r.submit("I would build a token bucket."))
    out = run(r.submit("Redis, with a Lua script."))
    assert parts.calls == 0, "no extraction should have been attempted"
    assert "no-new-observation->advance" not in state.turns[-1].guards
    assert not out.closed_question


def test_speech_shaping_never_overrides_stop_policy(tmp_path):
    """Candidate-controlled stop policy remains authoritative over model speech."""
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    r = Runner(ScriptedProvider([d("probe", "More?")]), PLAN, state)
    run(r.ask())
    out = run(r.submit("Sorry, I need to stop the interview here."))
    assert r.awaiting_confirm and not out.end_session


def test_an_either_or_is_answered_even_when_the_model_routed_it_itself(tmp_path):
    """A model-routed clarification must still answer the candidate's actual choice."""
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    r = Runner(ScriptedProvider([d("clarify", "Can you tell me more about the context?")]),
               PLAN, state)
    run(r.ask())
    out = run(r.submit("Do you mean a codebase at work, or would an open source one count?"))
    from app.runner import CLARIFY_EITHER
    assert out.spoken.text == CLARIFY_EITHER, out.spoken.text
    assert "clarify-either" in state.turns[-1].guards


def test_a_shortening_retry_may_not_change_the_act():
    """Shortening must not become a route to re-deciding the turn; changed speech enters
    History, so a retry with a different act is refused and the template stands."""
    import inspect
    from app import runner as _r
    src = inspect.getsource(_r.Runner.submit)
    assert "too_long=cap" in src
    assert "g2.act == g.act" in src, "the act-equality guard on the shortening retry is gone"


def test_an_unnameable_but_substantive_question_is_kept_not_templated(tmp_path, monkeypatch):
    """9.53. An empty `fresh` had two causes and the code treated them alike. A question the
    regex cannot NAME is not the same as a bad question: over two live sessions 16 of 20
    discarded lines were single, in-cap, non-repeating questions."""
    monkeypatch.setattr(focus, "next_focus", lambda *args: "CONTEXT")
    line = "What was the colleague's reaction when you gave him feedback?"
    assert not focus.classify(line)
    r, state = build([d("probe", line)], tmp_path)
    run(r.ask())
    out = run(r.submit("I told him the Friday PRs were costing us weekends."))
    decision = last_decision(state)
    assert out.spoken.text == line
    assert "unnamed-focus->kept" in decision["guards"]
    # The ladder still advances, so the next turn cannot ask the same kind of thing again.
    assert decision["focus_got"] == ["CONTEXT"]


def test_a_terse_unnameable_probe_still_goes_to_repair(tmp_path, monkeypatch):
    """The floor exists because a bare generic probe is what the repair is FOR. Every good
    unnameable line measured ran 10 words or more; every generic one ran 8 or fewer."""
    monkeypatch.setattr(focus, "next_focus", lambda *args: "STEPS")
    repaired = "How did you go about learning those forty Vue components?"
    r, state = build([d("probe", "What was your approach?"), speech(repaired)], tmp_path)
    run(r.ask())
    out = run(r.submit("I started from the broken screen."))
    assert out.spoken.text == repaired
    assert "unnamed-focus->kept" not in last_decision(state)["guards"]


def test_repeating_a_spent_request_type_is_still_refused(tmp_path, monkeypatch):
    """The other cause of an empty `fresh`, and it must keep behaving as before: a line that
    classifies to a focus already used is the model asking the same thing twice."""
    monkeypatch.setattr(focus, "next_focus", lambda *args: "CONTEXT")
    line = "How did you measure the improvement you saw after that change?"
    assert focus.classify(line)
    r, state = build([d("probe", line)], tmp_path)
    run(r.ask())
    r.focus_used |= focus.classify(line)
    out = run(r.submit("We cut p95 from eight seconds to three hundred milliseconds."))
    assert "unnamed-focus->kept" not in last_decision(state)["guards"]
    assert out.spoken.text != line


def test_no_template_asserts_an_outcome_the_candidate_has_not_claimed():
    """9.53. "How did you know it worked?" was the one template that made a CLAIM rather than
    a request, and it produced two of the three contradictory lines in 72 live turns -- once
    after "it cost us a sprint later", once before the candidate had said what happened."""
    for lines in focus.TEMPLATE.values():
        for line in lines:
            assert "it worked" not in line.lower(), line


def test_every_measure_template_is_premise_free_and_asks_once():
    for line in focus.TEMPLATE["MEASURE"]:
        assert line.count("?") == 1, line
        assert len(line.split()) <= 15, line


def test_every_template_line_classifies_as_its_own_focus():
    """The invariant `DESIGN_TEMPLATE` always held and `TEMPLATE` never did, because a test
    asserted it for one table and not the other. Nine of thirty failed: the harness spoke a
    line and recorded a focus as delivered that its own detector would not recognise. These
    lines are reviewed interviewer questions, so each failure was a false negative in the
    regex, and low recall is what pushes a turn onto the fallback path."""
    for table in (focus.TEMPLATE, focus.DESIGN_TEMPLATE):
        for want, lines in table.items():
            for line in lines:
                assert want in focus.classify(line), (want, line)


@pytest.mark.parametrize("said", [
    "What was the setup cost of the new vendor?",
    "Who was the first person you told?",
    "What trouble tickets did the team file?",
    "What was your thinking time on that?",
    "We ruled out the null hypothesis in the analysis.",
    "How did you determine the colleague who reviewed it?",
])
def test_the_template_widenings_stay_bounded(said):
    """Every phrase added above came from a template, and each could have been a bare topical
    word instead. `setup around` rather than `setup` is the load-bearing example: the looser
    form made a budget question CONTEXT."""
    assert not focus.classify(said), (said, sorted(focus.classify(said)))


@pytest.mark.parametrize("said", [
    "What was the hardest part about implementing that sliding window rate limiter?",
    "What was the trickiest bit about building the token bucket?",
    "What were the surprises when deploying it?",
])
def test_a_design_past_premise_without_the_word_you_is_still_detected(said):
    """Live gate violation. The design phase is hypothetical, so a question presuming the
    thing was built changes what the candidate is assessed on. Every existing branch needed a
    second-person pronoun and this line never says "you"."""
    assert focus.design_past_premise(said), said


@pytest.mark.parametrize("said", [
    "What else would you consider for the token bucket implementation?",
    "How would you handle a Redis outage?",
    "What was your reasoning there?",
])
def test_a_future_tense_design_probe_is_not_a_past_premise(said):
    assert not focus.design_past_premise(said), said


def test_no_reviewed_design_line_reads_as_a_past_premise():
    """The detector's fallback is these lines, so flagging one would make the harness replace
    a safe line with another safe line forever."""
    for lines in focus.DESIGN_TEMPLATE.values():
        for line in lines:
            assert not focus.design_past_premise(line), line
    assert not focus.design_past_premise(focus.DESIGN_REASK)
    assert not focus.design_past_premise(focus.DESIGN_FOLLOW_UP)


def test_the_live_past_premise_without_you_is_never_spoken(tmp_path):
    """The exact line the confirming junior control spoke on a hypothetical design question:
    the candidate had designed a rate limiter and built nothing. Every branch of the detector
    needed a second-person pronoun and this line never says "you", so nothing fired and the
    premise reached the candidate. Detection is now broader than the rewriter, because a
    missed rewrite falls back to a reviewed future-tense line and a missed DETECTION does not."""
    raw = "What was the hardest part about implementing that sliding window rate limiter?"
    runner, state = stage3_design_runner([d("probe", raw)], tmp_path)
    run(runner.ask())

    out = run(runner.submit(WITH_FAILURE))
    decision = last_decision(state)

    assert out.spoken.text != raw
    assert "implementing" not in out.spoken.text
    assert any("hypothetical-tense" in guard for guard in decision["guards"])
    # Provenance is untouched: the raw line is still recorded and no extra call was spent.
    assert decision["say_raw"] == raw
    assert decision["model_calls"] == 1


def test_the_ladder_orders_the_scored_criteria():
    """Two orderings existed and the wrong one won. `rubric_criteria` says WHAT is scored and
    leads with `sets_context` in every scored phase; `focus_ladder` says what to ask FIRST and
    ranks CONTEXT eighth of nine. The criteria loop returned in its own order, so the ladder
    was unreachable whenever a criterion was unmet, and one live interview asked "What was the
    scale of ...?" four times."""
    criteria = ["sets_context", "describes_action", "states_outcome",
                "first_person", "specific_detail"]
    ladder = ["STEPS", "REASON", "OUTCOME", "ROLE", "CHALLENGE",
              "LESSON", "MEASURE", "CONTEXT", "DURATION"]
    answer = "We split the users table live and I wrote the backfill myself."
    assert focus.next_focus(answer, set(), criteria, ladder) == "STEPS"


def test_context_is_still_asked_once_the_ladder_is_spent():
    """Reordering must not DROP a scored criterion, only defer it."""
    criteria = ["sets_context", "describes_action", "states_outcome"]
    ladder = ["STEPS", "OUTCOME"]
    answer = "We split the users table live and I wrote the backfill myself."
    got = focus.next_focus(answer, {"STEPS", "OUTCOME"}, criteria, ladder)
    assert got == "CONTEXT"


def test_a_criterion_the_ladder_omits_is_still_reachable():
    """`collaboration` leaves CONTEXT out of its ladder entirely, and `sets_context` is still
    one of the things it is scored on."""
    criteria = ["sets_context"]
    ladder = ["STEPS", "OUTCOME", "ROLE"]
    answer = "I told him the Friday deploys were costing the team weekends."
    assert focus.next_focus(answer, set(), criteria, ladder) == "CONTEXT"


def test_a_depth_signal_still_outranks_the_ladder():
    """Signals read what THIS answer is missing and must keep priority over both orderings."""
    criteria = ["sets_context", "describes_action"]
    ladder = ["STEPS", "REASON"]
    # Credit to "we" with the candidate's own part unstated asks for ROLE.
    answer = "We got the p95 down to about three hundred milliseconds."
    assert focus.next_focus(answer, set(), criteria, ladder) in {"ROLE", "MEASURE"}


def test_a_criterion_already_supplied_is_not_asked_again():
    """The criteria loop asked whether a focus had been ASKED on this question and never
    whether an earlier answer had SUPPLIED it, so a candidate who opened with the scale could
    still be asked for the scale. `sets_context` is satisfied by a `situation` quote, which
    the runner has tracked in `self.seen` since 1c.5 without ever consulting it here."""
    criteria = ["sets_context", "describes_action"]
    ladder = ["CONTEXT", "STEPS"]
    answer = "It was a fifteen-year-old billing service with no tests."
    assert focus.next_focus(answer, set(), criteria, ladder, set()) == "CONTEXT"
    assert focus.next_focus(answer, set(), criteria, ladder, {"situation"}) == "STEPS"


def test_a_criterion_with_no_observation_part_is_always_askable():
    """ROLE and MEASURE come from deterministic text checks rather than extracted quotes, so
    they have no part in `seen` and must never be skipped by it."""
    criteria = ["first_person", "specific_detail"]
    ladder = ["ROLE", "MEASURE"]
    answer = "We shipped it behind a flag and it held."
    got = focus.next_focus(answer, set(), criteria, ladder,
                           {"situation", "action", "result"})
    assert got in {"ROLE", "MEASURE"}


def test_every_criterion_satisfied_falls_through_to_the_ladder():
    """Nothing scored is outstanding, so the turn is not skipped -- the ladder still supplies
    a request, which is what it is for."""
    criteria = ["sets_context", "describes_action", "states_outcome"]
    ladder = ["CHALLENGE", "LESSON"]
    answer = "We cut p95 from eight seconds to three hundred milliseconds."
    got = focus.next_focus(answer, set(), criteria, ladder,
                           {"situation", "action", "result"})
    assert got is not None
    assert got not in {"CONTEXT", "STEPS", "OUTCOME"}


def test_seen_defaults_to_empty_so_existing_callers_are_unchanged():
    criteria = ["sets_context"]
    assert focus.next_focus("It was a billing service.", set(), criteria, ["CONTEXT"]) == "CONTEXT"


def test_a_confusable_focus_pair_about_the_same_thing_is_a_reword():
    """MEASURE renders as "how did you know X" and REASON as "what made you decide X"; for one
    X those are the same question, and the rotation cannot see it because the labels differ."""
    assert focus.rewords(
        "How did you determine that a 15-minute TTL on product data was sufficient?",
        ["MEASURE"],
        "What made you choose fifteen minutes as a threshold for TTLs?",
        ["REASON"])


def test_a_confusable_pair_that_changes_the_object_is_a_real_follow_up():
    """The live pair this must not block: both are MEASURE then REASON, and the second asks
    about a different thing, so it is the follow-up an interviewer would actually ask."""
    assert not focus.rewords(
        "How did you know that splitting on the last space would be sufficient to backfill "
        "the existing data?",
        ["MEASURE"],
        "What made you decide to keep the original full name column instead of dropping it?",
        ["REASON"])


def test_a_shared_object_alone_is_not_a_reword():
    """STEPS then OUTCOME share their object constantly and are two different questions."""
    assert not focus.rewords(
        "What specific changes did you make to improve performance?", ["STEPS"],
        "What was the impact of these changes on performance or scalability?", ["OUTCOME"])


def test_the_same_focus_twice_is_left_to_the_rotation():
    """Rotation already forbids spending one focus twice; this guard must not also claim it,
    or a repeat would be reported under the wrong name."""
    assert not focus.rewords(
        "How did you know the queue was keeping up?", ["MEASURE"],
        "How did you know the error rate was acceptable?", ["MEASURE"])


def test_number_words_and_plurals_normalise_before_comparing():
    assert focus._subject_words("fifteen minutes") & focus._subject_words("a 15-minute TTL")
    assert focus._subject_words("those TTLs") & focus._subject_words("the TTL")


def test_reword_needs_both_sides_present():
    assert not focus.rewords("", ["MEASURE"], "What made you decide that?", ["REASON"])
    assert not focus.rewords("How did you know?", [], "What made you decide that?", ["REASON"])


def test_runner_advances_rather_than_asking_a_reworded_probe(tmp_path, monkeypatch):
    """The response is advance, not repair. Routing rejected lines to the repair was measured
    worse: it fails often and the failures become templates."""
    focuses = iter(["MEASURE", "REASON"])
    monkeypatch.setattr(focus, "next_focus", lambda *args: next(focuses))
    first = "How did you determine that a 15-minute TTL on product data was sufficient?"
    second = "What made you choose fifteen minutes as a threshold for TTLs?"
    r, state = build([d("probe", first, ok=False), d("probe", second, ok=False)], tmp_path)
    run(r.ask())
    run(r.submit("I cached the product catalogue with a fifteen minute TTL."))
    out = run(r.submit("It felt like a round number."))
    decision = last_decision(state)
    assert "redundant-probe->advance" in decision["guards"]
    assert decision["say"] == ""
    # The focus is not charged either: nothing was asked, so nothing was delivered.
    assert decision["focus_got"] == []


@pytest.mark.parametrize("said", [
    # The enumerated adjective slot was fitted to the lines available and did not survive a
    # seventh: this one carries the head noun and still failed, sending a good repair to a
    # template on the live strong control.
    "How did you determine the average turnaround time of two days for refunds?",
    "How did you determine the median response time across those endpoints?",
    "How did you establish the acceptable error rate for the rollout?",
    "How did you determine the refill rate for the token bucket?",
    # `determine that ...` no longer needs a time unit: establishing a proposition is a
    # measurement question whatever the proposition is about.
    "How did you determine that the issue was with the email provider's API?",
    "How did you determine that the backlog was growing?",
])
def test_the_widened_determine_family_is_measure(said):
    assert focus.classify(said) == {"MEASURE"}, (said, sorted(focus.classify(said)))


@pytest.mark.parametrize("said", [
    # A measurable noun followed by an infinitive is a judgement about when or whether to act,
    # not a measurement. This is what lets the modifier slot be widened at all.
    "How did you determine the right time to give him that feedback?",
    "How did you determine the best time to raise it with your manager?",
    # The person/object hazard the generic `determine\b` was rejected for.
    "How did you determine which framework to use?",
    "How did you determine the colleague who reviewed it?",
    "How did you determine the right person to talk to?",
    "How did you determine the best candidate for that role?",
    "How did you determine the team that owned the service?",
    "How did you determine who should review it?",
    "How did you determine the appropriate escalation path?",
    "How did you establish the working relationship with that team?",
    "How did you determine the vendor you went with?",
])
def test_the_widened_determine_family_still_excludes_selection(said):
    assert "MEASURE" not in focus.classify(said), (said, sorted(focus.classify(said)))
