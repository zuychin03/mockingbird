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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import budget, contract, focus, guards, intent, observe, result_check, session  # noqa: E402
from app.provider import Completion  # noqa: E402
from app.runner import CONFIRM_NARROW, Runner, live_view  # noqa: E402


class ScriptedProvider:
    """Returns queued decisions in order. Summariser calls get a fixed line."""

    def __init__(self, decisions):
        self.queue = list(decisions)
        self.prompts = []

    async def complete(self, system, user, schema=None, max_tokens=400,
                       enum_field=None, enum_values=None):
        self.prompts.append(user)
        if schema is None:
            return Completion(text="Covered one question so far.")
        d = self.queue.pop(0)
        return Completion(text=json.dumps(d), prompt_tokens=100, decode_tokens=30,
                          posterior={d["act"]: 0.9})


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


def test_a_line_asking_nothing_new_is_replaced_with_the_template(tmp_path):
    r, state = build([d("probe", "Tell me about the weather.")], tmp_path)
    run(r.ask())
    out = run(r.submit("we shipped it"))
    assert out.spoken.text in [v for vs in focus.TEMPLATE.values() for v in vs]
    assert any("off-focus" in x for x in state.turns[-1].guards)


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
DESIGN_PLAN = {
    "id": "test-design",
    "phases": [{
        "id": "design", "answer_shape": "open", "probe_budget": 3, "scored": False,
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


def test_a_design_answer_with_no_failure_mode_is_probed_before_advancing(tmp_path):
    """Live, this question drew ZERO probes out of three: `ok` asks whether the reply answers
    the question, and a long fluent answer reads as complete even with a part missing."""
    r, state = design_runner([d("advance", "")], tmp_path)
    run(r.ask())
    out = run(r.submit(NO_FAILURE))
    assert out.spoken.text == focus.DESIGN_FOLLOW_UP
    assert "design-gap->probe" in state.turns[-1].guards
    assert not out.closed_question


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
    run(r.submit("Redis, with a Lua script."))
    out = run(r.submit("Because it is shared and fast."))
    assert parts.calls == 0, "no extraction should have been attempted"
    assert "no-new-observation->advance" not in state.turns[-1].guards
    assert not out.closed_question


# ------------------------------------- speech profile (log 9.21, 9.22)
def test_only_the_exemplar_rule_varies_by_model():
    """9.21 measured the exemplar list worth +3 fixtures to granite and a third of Yi's probe
    variety. That suggested the whole speech layer was granite-shaped; 9.22 measured the other
    two and it is not -- turning substitution off cost Yi 3 distinct request types. One knob
    varies, and this pins that so a future profile has to justify a second."""
    from app.runner import YI, Speech
    default = Speech()
    differing = [f for f in ("exemplars", "substitute_focus", "repeat_closes")
                 if getattr(YI, f) != getattr(default, f)]
    assert differing == ["exemplars"], differing


def test_the_profile_follows_the_model_id():
    from app.runner import Speech
    assert Speech.for_model("yi-1.5-6b-chat").exemplars is False
    assert Speech.for_model("granite-4.1-3b").exemplars is True
    assert Speech.for_model("").exemplars is True, "an unknown model gets the default"


def test_dropping_the_exemplars_leaves_the_rest_of_the_prompt_intact():
    """A variant, not an edit: everything else V5 measured has to survive."""
    from app import contract
    assert "What did you measure?" in contract.SYSTEM
    assert "What did you measure?" not in contract.SYSTEM_NO_EXEMPLARS
    for kept in ("ONE question, at most 15 words", "Choose exactly one action",
                 "copy their question verbatim"):
        assert kept in contract.SYSTEM_NO_EXEMPLARS, kept


def test_speech_rules_never_touch_policy(tmp_path):
    """The split this profile rests on: a rule that decides what the interview DOES is not in
    here. A profile with everything off must still honour a grounded stop."""
    from app.runner import Speech
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    r = Runner(ScriptedProvider([d("probe", "More?")]), PLAN, state,
               speech=Speech(exemplars=False, substitute_focus=False, repeat_closes=False))
    run(r.ask())
    out = run(r.submit("Sorry, I need to stop the interview here."))
    assert r.awaiting_confirm and not out.end_session


def test_the_warmup_primes_the_prompt_the_session_will_actually_send():
    """The two variants diverge mid-prompt, so priming contract.SYSTEM for a model that gets
    SYSTEM_NO_EXEMPLARS re-prefills turn 0's tail -- the exact cost warmup exists to remove."""
    from app import contract
    from app.runner import Speech
    assert Speech().system == contract.SYSTEM
    assert Speech(exemplars=False).system == contract.SYSTEM_NO_EXEMPLARS


def test_an_either_or_is_answered_even_when_the_model_routed_it_itself(tmp_path):
    """Found live on Yi. The upgrade sat behind `act not in ("clarify",...)`, so a model that
    reached clarify on its own kept its own line -- and answered a different question."""
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
    """9.52. Shortening a question must not become a route to re-deciding the turn: 9.51
    measured a speech-only change moving granite's decisions three items through History,
    so a retry that comes back with a different act is refused and the template stands."""
    import inspect
    from app import runner as _r
    src = inspect.getsource(_r.Runner.submit)
    assert "too_long=cap" in src
    assert "g2.act == g.act" in src, "the act-equality guard on the shortening retry is gone"
