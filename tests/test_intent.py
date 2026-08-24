"""Control-intent parsing. Log section 9.13.

Every case below was wrong under the substring parser or is a boundary the new one has to
hold. The three named in the review are marked; the rest are the cases that made the fix
land where it did.
"""

from __future__ import annotations

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
