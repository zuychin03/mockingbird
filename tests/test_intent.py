"""Control-intent parsing. Log section 9.13.

Every case below was wrong under the substring parser or is a boundary the new one has to
hold. The three named in the review are marked; the rest are the cases that made the fix
land where it did.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import intent  # noqa: E402

STOP, CONTINUE, SKIP, UNCLEAR = (
    intent.STOP, intent.CONTINUE, intent.SKIP_QUESTION, intent.UNCLEAR)


def read(u, bare_yes=None):
    return intent.read_control(u, bare_yes=bare_yes)


# ------------------------------------------------------- the reported defects
def test_a_negated_stop_is_a_request_to_continue():
    """Reported. Ended the session on the reply that declined to end it."""
    assert read("No, I don't want to stop.") == CONTINUE
    assert read("I'd rather not stop") == CONTINUE
    assert read("not stop") == CONTINUE


def test_a_negated_stop_is_not_evidence_of_a_stop_request():
    """Reported. Raised the confirmation turn that the defect above then mis-read, so the
    two compounded into ending a session the candidate twice declined to end."""
    assert intent.asked_to_stop("I don't need to stop; let's continue.") is False
    assert intent.asked_to_stop("I never said I wanted to stop the interview") is False


def test_a_skip_is_read_as_a_skip_even_after_a_leading_no():
    """Reported. "No" answers the offer, it does not negate the request that follows."""
    assert intent.wants_skip("No, let's skip it.") is True


# ------------------------------------------------- the defect the review missed
def test_the_middle_option_of_a_three_way_prompt_resolves():
    """CONFIRM_LINE offers "skip this question and carry on". It affirms both skip and
    continue content, and the specific request is the one the candidate made."""
    assert read("skip this question and carry on") == SKIP
    assert read("skip this one and keep going") == SKIP
    assert read("no, skip it and carry on") == SKIP


def test_a_bare_affirmative_decides_nothing_against_a_disjunction():
    assert read("yes") == UNCLEAR
    assert read("yeah") == UNCLEAR
    assert read("sure") == UNCLEAR
    assert read("the second one") == UNCLEAR


def test_a_bare_affirmative_resolves_once_the_caller_says_what_it_means():
    assert read("yes", bare_yes=STOP) == STOP
    assert read("yes please", bare_yes=SKIP) == SKIP


# ------------------------------------------------------------- response particles
def test_a_leading_no_does_not_scope_over_the_sentence():
    """"No, I want to stop" is a stop request. Treating the particle as a clause negator
    inverted every reply that opened with one."""
    assert read("No, I want to stop.") == STOP
    assert read("no I need to stop") == STOP
    assert intent.asked_to_stop("no I need to stop") is True


def test_a_bare_negative_carries_on():
    assert read("no") == CONTINUE
    assert read("nope") == CONTINUE
    assert read("no thanks") == CONTINUE


# ------------------------------------------------------------- negation scope
def test_a_negator_reaches_the_end_of_its_clause_and_no_further():
    assert read("I can't stop, but I'd like to skip this") == SKIP
    assert read("I don't want to stop; let's continue") == CONTINUE


def test_a_negator_after_the_phrase_does_not_negate_it():
    assert read("stop the interview, I'm not well") == STOP


# --------------------------------------------------------------- token boundary
def test_ordinary_answer_vocabulary_is_not_consent():
    """The bare verbs are ordinary words in an interview answer. Substring matching read
    every one of these as a request to end the session."""
    for answer in ("we stopped the rollout and the errors ended",
                   "the retries finished quickly once the cache was warm",
                   "support stopped believing the dashboard",
                   "I'm done with that team now"):
        assert intent.asked_to_stop(answer) is False, answer


def test_stop_vocabulary_does_not_fire_on_ordinary_interview_talk():
    """Found live (9.18): "is there someone senior on the front end here" matched `end here`
    and raised a stop confirmation mid-answer.

    A 719-utterance corpus sweep found ONE of these, which is the trap -- a corpus of recorded
    answers holds what candidates have already said, not what they might say. These seven
    sentences were written in a minute and all seven fired. The bare location phrases are gone
    and what is left needs a request frame: a subject and a modal pointing at now.
    """
    for answer in (
            "I work on the front end here and the back end at my last place.",
            "I needed to finish up the migration before the freeze.",
            "We had to wrap this up before the quarter ended.",
            "The retry logic would stop here and fall through to the dead letter queue.",
            "That was the end here of the old pipeline.",
            "I want to wrap it up cleanly rather than leave it half done.",
            "We call it a day one deploy internally."):
        assert intent.asked_to_stop(answer) is False, answer


def test_a_stop_verb_with_an_object_is_not_a_request_to_leave():
    """The second half of 9.18, found one turn after the first fix shipped. A request frame
    is not enough on its own, because the verb takes an object: "I want to stop being the
    only front-end person" is an answer to what drew them to the role. A STOP_REQUEST phrase
    counts only where it ends its clause or is followed by a word meaning *now*."""
    for answer in (
            "I want to stop being the only front-end person.",
            "I need to stop doing manual deploys.",
            "I have to go through the logs first.",
            "We wanted to stop the retries flooding the queue.",
            "I want to stop guessing and start measuring.",
            "I want to wrap it up cleanly rather than leave it half done."):
        assert intent.asked_to_stop(answer) is False, answer

    for ask in ("I want to stop.", "I want to stop here.", "we should stop now"):
        assert intent.asked_to_stop(ask) is True, ask


def test_a_request_to_stop_still_fires_however_it_is_phrased():
    for ask in (
            "I need to stop here.",
            "Can we end here?",
            "I'd like to end here if that's ok",
            "something has come up and I have to go",
            "can we wrap this up, I have another call",
            "sorry, can we finish here",
            "Sorry, this is a bit uncomfortable - do we have to stop here?"):
        assert intent.asked_to_stop(ask) is True, ask


def test_a_strong_phrase_inside_an_answer_still_counts():
    assert intent.asked_to_stop("sorry, something's come up and I need to stop here") is True
    assert intent.asked_to_stop("can we rearrange? this isn't a good time") is True


# ------------------------------------------------------------------- precedence
def test_skip_outranks_stop_when_both_are_affirmed():
    """A safety property, not a preference: skipping keeps the session, stopping ends it."""
    assert read("I have to go, skip it") == SKIP


def test_a_negated_skip_keeps_trying_the_question():
    assert read("don't skip it") == CONTINUE
    assert intent.wants_skip("don't skip it") is False


# --------------------------------------------------------------- the skip offer
def test_the_skip_offer_keeps_going_on_anything_unclear():
    """The milder asymmetry: wrongly carrying on costs one more explanation and then
    auto-skips anyway, so the default converges either way."""
    assert intent.wants_skip("mmm") is False
    assert intent.wants_skip("no, let me try again") is False
    assert intent.wants_skip("give me a moment") is False


def test_the_skip_offer_accepts_a_bare_yes():
    """Unlike the stop check, and the difference is the cost: a wrong skip loses a question,
    a wrong stop loses the session."""
    assert intent.wants_skip("yes") is True
    assert intent.wants_skip("yes please, skip it") is True


def test_a_stop_request_to_the_skip_offer_is_not_converted_into_a_skip():
    """It reads as STOP so the runner can raise a confirmation. Reading it as a skip would
    swallow the request, and reading it as an end would skip the confirmation the whole
    stop path exists to require."""
    for reply in ("I have to go", "can we stop the interview", "I need to leave"):
        assert read(reply, bare_yes=SKIP) == STOP, reply
        assert intent.wants_skip(reply) is False, reply


def test_empty_and_punctuation_only_replies_are_unclear():
    for junk in ("", "   ", "...", "???", "\n"):
        assert read(junk) == UNCLEAR
        assert intent.asked_to_stop(junk) is False


# ------------------------------------- an independently authored corpus (log 9.38)
# 75 consent cases written against a PARALLEL implementation, by someone who had never seen
# this module. 9.15's lesson is that a hand-authored fixture set only measures whether a rule
# matches its own author's reading; this one measures whether it generalises. It found two
# real inversions on first contact.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "consent_cases.json"

# Cases where the two implementations genuinely disagree about the RIGHT answer and this one
# is deliberate. Each is a measured decision, not an oversight:
#   bare particles -- a lone "no" to "do you want to stop?" declines it; a lone "yes" to the
#     skip offer accepts, because a wrong skip costs a question and a wrong stop costs the
#     session, so only the cheaper prompt lets a bare affirmative decide (read_control).
#   "no, skip it and carry on" -- CONFIRM_LINE asks a THREE-way question and skip is one of
#     the options it offers; reading this as "continue" re-asks the question they just asked
#     to leave. That was the half of the release blocker the review missed (9.13).
DELIBERATE = {
    ("stop_confirmation", "no"),
    ("stop_confirmation", "no, skip it and carry on"),
    ("skip_offer", "yes"),
    ("skip_offer", "no"),
}

# Bare stop-verbs stay unmatched in an ORDINARY answer and that is not an oversight either:
# allowing them under the endpoint rule was tried and fired on 20 of 914 real stored
# utterances, including "Four years, full-stack on a logistics product..." (9.38).
CONSERVATIVE = {
    ("ordinary", "Please stop here."), ("ordinary", "Please stop."),
    ("ordinary", "STOP HERE"), ("ordinary", "stop-here"),
    ("ordinary", "we should finish here"),
    ("ordinary", "I need to finish here and leave."),
    ("skip_offer", "Pass."), ("skip_offer", "Next."),
}

_EXPECT = {"stop": intent.STOP, "continue": intent.CONTINUE, "keep_trying": intent.CONTINUE,
           "skip": intent.SKIP_QUESTION, "ambiguous": intent.UNCLEAR}


def _read(case):
    text, ctx = case["text"], case["context"]
    if ctx == "ordinary":
        return "stop" if intent.asked_to_stop(text) else "none", \
               ("stop" if case["expected"] == "stop" else "none")
    bare = intent.SKIP_QUESTION if ctx == "skip_offer" else None
    return intent.read_control(text, bare_yes=bare), _EXPECT[case["expected"]]


def test_the_independent_consent_corpus():
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    assert len(cases) == 75
    unexpected = []
    for case in cases:
        key = (case["context"], case["text"])
        got, want = _read(case)
        if got != want and key not in DELIBERATE and key not in CONSERVATIVE:
            unexpected.append((key, want, got))
    assert not unexpected, unexpected


def test_the_two_inversions_the_corpus_found_stay_fixed():
    """Both fired as a request to END THE INTERVIEW on ordinary interview vocabulary, and the
    second read a REFUSAL to stop as consent -- 9.13's inversion, reintroduced by a phrase
    that begins with its own negator so `_hits` could never negate it."""
    for said in ("I know how to rearrange the queue.",
                 "I rearrange my calendar every Monday.",
                 "It was not a good time to deploy, so we waited."):
        assert not intent.asked_to_stop(said), said
    assert intent.read_control("It is not a good time to stop.") == intent.CONTINUE
    assert intent.read_control("We need to finish the migration before Friday.") == intent.UNCLEAR
    # and the genuine request it was originally added for still lands
    assert intent.asked_to_stop("This isn't a good time, can we rearrange?")


def test_a_procedural_skip_needs_no_refusal_in_it():
    """9.39's surviving crossing. Every model read "Next one, please." as `reask`, because
    the only skip evidence guard 2c had was refusal vocabulary and there is none in it."""
    for said in ("Next one, please.", "Next question.", "Can we move on?",
                 "Let's move on.", "Could we skip this one?"):
        assert intent.asked_to_skip(said), said


def test_a_procedural_skip_does_not_fire_on_a_narrative():
    """The endpoint rule that makes STOP_REQUEST safe is not enough for these: they end a
    clause in ordinary answers too, so the phrase has to BE the clause."""
    for said in ("In the end we decided to move on.",
                 "We shipped the first one, then the next one.",
                 "I wanted to move on from that team.",
                 "The next one failed too.",
                 "We move on to Postgres in the second phase."):
        assert not intent.asked_to_skip(said), said


def test_no_experience_is_still_a_reask_not_a_skip():
    """6.3's ordering, which the procedural half must not reach around: CANNOT beats both
    kinds of skip, or a junior with nothing to draw on is recorded as having refused."""
    from app import guards
    assert not guards.skip_requested("I haven't done one of those.")
    assert not guards.skip_requested("I can't really think of one.")
