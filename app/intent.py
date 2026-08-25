"""Reading a control reply: stop, skip this question, or carry on. Log section 9.13.

Section 6.4's control checks asked "did the candidate say this" by substring, which cannot
see a token boundary, a negation, or which way the request points. Three of them were wrong
in the same way:

    confirms_stop("No, I don't want to stop.")   -> True    ended the session
    user_asked_to_stop("I don't need to stop.")  -> True     raised a confirmation
    wants_skip("No, let's skip it.")             -> False    refused an accepted skip

The first two compound. A false positive in the detector raises the confirmation turn, and a
negated reply to that turn reads as consent, so a candidate who says twice that they do not
want to stop is stopped.

`CONFIRM_LINE` offers three outcomes and the old parser had two branches, so "skip this
question and carry on" -- an option the prompt itself puts to the candidate -- re-asked the
question they had just asked to leave. The prompt and the parser were written against
different contracts.

Three rules, and the third is the one that changes behaviour rather than just correctness:

    match whole tokens          "stop" must not fire inside "stopped believing"
    scope negation to a clause  a negator reaches the end of its clause and no further
    answer UNCLEAR honestly     ambiguity is a fourth value, not a default into a branch

A leading "yes" or "no" is a response particle. It answers the question just asked and does
not scope over the rest of the sentence, which is why "No, I want to stop" is a stop request
and "No, I don't want to stop" is not.
"""

from __future__ import annotations

import re

STOP = "stop"
CONTINUE = "continue"
SKIP_QUESTION = "skip_question"
UNCLEAR = "unclear"

_YES = "yes"
_NO = "no"

# "don't" -> "do not", "can't" -> "ca not". Only the presence of `not` matters downstream,
# so the mangled stem is harmless and the special cases are not worth a table.
_NT = re.compile(r"n't\b", re.I)
# A negator reaches the end of its clause and no further. Coordinators end a clause for the
# same reason a comma does: "I can't stop now, but I'd like to skip this one".
_CLAUSE = re.compile(r"[,;:.!?]+|\b(?:but|however|although|though|instead|so)\b")
_NEGATORS = frozenset({"not", "no", "never", "nor", "neither"})

_PARTICLE_YES = frozenset({"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "correct"})
_PARTICLE_NO = frozenset({"no", "nope", "nah"})

# Asking to end the whole interview, read inside an ORDINARY answer. Two lists, and the
# split is the point.
#
# The first names the interview itself, so it can fire alone. The second requires a REQUEST
# FRAME -- a subject and a modal pointing at now -- because the bare location phrases that
# used to live here are ordinary interview vocabulary and fired on plain answers (9.18):
#
#     "I work on the front end here"          matched `end here`
#     "I needed to finish up the migration"   matched `finish up`
#     "we had to wrap this up before the      matched `wrap this up`
#      quarter ended"
#     "the retry logic would stop here"       matched `stop here`
#
# A 719-utterance corpus sweep found only one of these, which is the trap: a corpus of
# recorded answers holds what candidates have already said, not what they might say. Seven
# adversarial sentences found seven.
STOP_EXPLICIT = [
    "stop the interview", "end the interview", "stop this interview", "end this interview",
    "stop the session", "end the session",
    # Naming the conversation by what it is rather than what it is for. "I'm going to have
    # to end the call here" is unambiguous and matched nothing: the object sits between the
    # verb and the endpoint, so neither the explicit list nor the request frame caught it.
    # A gold=end fixture that both the old vocabulary and the new one missed (9.19).
    "end the call", "stop the call", "end this call", "end the meeting", "stop the meeting",
]
STOP_REQUEST = [
    "need to stop", "have to stop", "want to stop", "like to stop", "got to stop",
    "need to end", "have to end", "want to end", "like to end",
    "need to go", "have to go", "got to go", "need to leave", "have to leave",
    "can we stop", "can we end", "can we finish", "can we wrap", "could we stop",
    "shall we stop", "let us stop", "lets stop", "we stop here", "we end here",
    "call it here", "cut this short", "cut it short", "stop it here", "end it here",
    "should stop", "should we stop", "wrap this up", "wrap it up", "we stop", "we end",
    # Moved out of STOP_EXPLICIT, which fires on its own. As bare substrings these matched
    # ordinary interview vocabulary -- "I rearrange my calendar every Monday" and "it was
    # not a good time to deploy, so we waited" both read as a request to END THE INTERVIEW,
    # and "it is not a good time to stop" read backwards into the very inversion 9.13 exists
    # to remove. Under the request frame they still catch "this isn't a good time, can we
    # rearrange?" because there the phrase ends its clause (9.38).
    "not a good time", "rearrange",
]
STOP_STRONG = STOP_EXPLICIT + STOP_REQUEST

# A request frame is still not enough on its own, because the verb can take an object:
# "I want to stop being the only front-end person" is an answer, not a request to leave.
# So a STOP_REQUEST phrase counts only where it ENDS its clause or is followed by a word
# meaning *this conversation, now*. Found live, one turn after the fix above (9.18).
_ENDPOINT = frozenset({"here", "now", "there", "today", "early", "soon", "then"})
# Only meaningful as a reply to a confirmation, where the question licenses the bare word.
# In an ordinary answer these are ordinary vocabulary: "the retries stopped" is not consent.
STOP_BARE = ["stop", "end", "quit", "finish", "done", "stopping"]

SKIP_CONTENT = [
    "skip this question", "skip the question", "skip this one", "skip this", "skip that",
    "skip it", "skip", "next question", "move on", "come back to it", "pass on this",
    "pass on that", "leave it", "leave this", "park it",
]

CONTINUE_CONTENT = [
    "carry on", "keep going", "continue", "go on", "keep at it", "stay on this",
    "i am fine", "im fine", "all good", "another go", "one more", "try again",
    "let me try", "give me a moment", "not yet", "keep trying",
]


def _tokens(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", text).split()


def _clauses(text: str) -> list[list[str]]:
    expanded = _NT.sub(" not", (text or "").lower())
    return [t for t in (_tokens(c) for c in _CLAUSE.split(expanded)) if t]


def _split_particle(clauses: list[list[str]]) -> tuple[str | None, list[list[str]]]:
    """Take a leading yes/no off the front. It answers the question, it does not negate."""
    if not clauses or not clauses[0]:
        return None, clauses
    head = clauses[0][0]
    if head not in _PARTICLE_YES and head not in _PARTICLE_NO:
        return None, clauses
    rest = [clauses[0][1:]] + clauses[1:]
    return (_YES if head in _PARTICLE_YES else _NO), [c for c in rest if c]


def _hits(clause: list[str], phrases: list[str]) -> tuple[bool, bool]:
    """(affirmed, negated) for one clause. A negator counts only if it precedes the phrase."""
    negs = [i for i, t in enumerate(clause) if t in _NEGATORS]
    affirmed = negated = False
    for phrase in phrases:
        want = phrase.split()
        n = len(want)
        for i in range(len(clause) - n + 1):
            if clause[i:i + n] != want:
                continue
            if any(j < i for j in negs):
                negated = True
            else:
                affirmed = True
    return affirmed, negated


def _endpoint_hit(clause: list[str], phrases: list[str]) -> bool:
    """Match, but only where the phrase ends the clause or points at now.

    "I want to stop." and "I want to stop here." are requests. "I want to stop being the only
    front-end person." is an answer to what drew them to the role.
    """
    negs = [i for i, t in enumerate(clause) if t in _NEGATORS]
    for phrase in phrases:
        want = phrase.split()
        n = len(want)
        for i in range(len(clause) - n + 1):
            if clause[i:i + n] != want or any(j < i for j in negs):
                continue
            tail = clause[i + n:]
            if not tail or tail[0] in _ENDPOINT:
                return True
    return False


def read_control(utterance: str, *, bare_yes: str | None = None) -> str:
    """Read a reply to a control question. One of STOP, CONTINUE, SKIP_QUESTION, UNCLEAR.

    `bare_yes` is what a lone affirmative resolves to, or None to leave it UNCLEAR. Both
    control prompts are disjunctive -- "do you want A, or B?" -- and a bare "yes" against a
    disjunction carries no information. The two callers differ because their costs differ:
    a wrong skip costs a question, a wrong stop costs the session, so only the skip offer
    lets a bare affirmative decide anything.
    """
    polarity, clauses = _split_particle(_clauses(utterance))

    stop_a = stop_n = skip_a = skip_n = continue_a = False
    for c in clauses:
        # Only the EXPLICIT phrases fire on their own here. The request frames and the bare
        # verbs take the endpoint rule, for the same reason `asked_to_stop` does: "we need to
        # finish the migration before Friday" is not consent, and "it is not a good time to
        # stop" is a REFUSAL that read as consent because the phrase begins with its own
        # negator -- `_hits` only counts a negator that PRECEDES the phrase, and index 2 is
        # not before index 2 (9.38).
        a, n = _hits(c, STOP_EXPLICIT)
        _, n_rest = _hits(c, STOP_REQUEST + STOP_BARE)
        a = a or _endpoint_hit(c, STOP_REQUEST + STOP_BARE)
        stop_a, stop_n = stop_a or a, stop_n or (n or n_rest)
        a, n = _hits(c, SKIP_CONTENT)
        skip_a, skip_n = skip_a or a, skip_n or n
        a, _ = _hits(c, CONTINUE_CONTENT)
        continue_a = continue_a or a

    # SKIP outranks STOP when both are affirmed, and the order is a safety property rather
    # than a preference: skipping keeps the session, stopping ends it. It also settles the
    # candidate who reads the offered option back verbatim -- "skip this question and carry
    # on" affirms both skip and continue, and the specific request is the one they made.
    if skip_a:
        return SKIP_QUESTION
    if stop_a:
        return STOP
    # A negated stop IS a request to carry on. It is the reply the old parser read backwards.
    if continue_a or stop_n or skip_n or polarity == _NO:
        return CONTINUE
    if polarity == _YES and bare_yes:
        return bare_yes
    return UNCLEAR


def asked_to_stop(utterance: str) -> bool:
    """Guard 2's evidence test, read over an ORDINARY answer rather than a control reply.

    Strong phrases only. The bare verbs are ordinary vocabulary in an interview answer --
    "we stopped the rollout", "the errors ended" -- and reading those as consent is the
    failure this whole module exists to remove.
    """
    _, clauses = _split_particle(_clauses(utterance))
    return any(_hits(c, STOP_EXPLICIT)[0] or _endpoint_hit(c, STOP_REQUEST)
               for c in clauses)


def wants_skip(utterance: str) -> bool:
    """Read a reply to the skip offer. Anything but a clear skip carries on.

    The asymmetry is milder than the stop check's: wrongly skipping discards a question the
    candidate wanted to attempt, while wrongly carrying on costs one more explanation and
    then auto-skips anyway, so the default converges either way.
    """
    return read_control(utterance, bare_yes=SKIP_QUESTION) == SKIP_QUESTION
