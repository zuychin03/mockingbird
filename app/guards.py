"""The five guards. Plan section 6.4.

These run on every decision before a handler sees it, in this order. Each exists because
something went wrong in the reference project, not because it seemed prudent.

`probe` is the universal safe landing: an unrecognised action, a rejected `end` and a
self-contradictory `advance` all become `probe`, because it never advances past an
unanswered question and never ends the session.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from . import intent
from .contract import ACTIONS

_SENTENCE = re.compile(r"[^.!?]+[.!?]?")
# Stand-in for a dot that does not end a sentence. Private-use codepoint: it
# cannot appear in model output, so masking and unmasking are lossless.
_MASK = "\uE000"
# Dots that do not end a sentence.
# Share of `ask`'s content words that must come from the candidate's own utterance.
ASK_OVERLAP = 0.5
_ABBREV = re.compile(r"(?:e\.g\.|i\.e\.|etc\.|vs\.|approx\.|no\.|fig\.|cf\.|"
                     r"inc\.|ltd\.|dept\.|\b[A-Z]\.)", re.I)
_LABEL = re.compile(r"^\s*([A-Z][A-Z0-9 _/-]{2,})\s*[:\-—]")
_ALLOW_CAPS = {"API", "SQL", "HTTP", "JSON", "CI", "CD", "AWS", "GCP", "TDD", "SRE", "CPU",
               "GPU", "RAM", "ORM", "REST", "TLS", "DNS", "URL", "UI", "UX", "QA", "PR"}

# 0.60 is the near-duplicate line tier1_rec3.py uses with this exact metric, and the one
# 7.7 calls "comfortably below the 0.60 near-duplicate threshold". This shipped at 0.80 with
# nothing in the log justifying it, and 93 within-question pairs sat in the gap unremarked.
SIMILARITY_LIMIT = 0.60
ECHO_MIN_WORDS = 2        # below this, an overlap is a coincidence, not an echo
MAX_SAY_CHARS = 320
# advance, skip and end close a question, and none of them speaks the model's line (guard 4).
CLOSING_ACTIONS = frozenset({"advance", "skip", "end"})


@dataclass
class Guarded:
    act: str
    say: str
    ok: bool
    ask: str
    applied: list[str] = field(default_factory=list)
    needs_regeneration: bool = False


def _sentences(text: str) -> list[str]:
    # Abbreviations are masked before splitting rather than rejoined after: rejoining has to
    # guess the whitespace the split consumed, and got "e.g.load" wrong. Observed live: a
    # line ended "...and any other factors (e." because `e.g.` reads as a boundary (8.20).
    masked = _ABBREV.sub(lambda m: m.group(0).replace(".", _MASK), text or "")
    return [x.strip().replace(_MASK, ".")
            for x in _SENTENCE.findall(masked) if x.strip()]


def _is_question(s: str) -> bool:
    return s.rstrip().endswith("?")


def _truncate(text: str, limit: int = MAX_SAY_CHARS) -> str:
    """Cut at a sentence boundary. Never mid-word, never mid-clause."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    kept: list[str] = []
    for s in _sentences(text):
        if sum(len(k) + 1 for k in kept) + len(s) > limit:
            break
        kept.append(s)
    return " ".join(kept) if kept else text[:limit].rsplit(" ", 1)[0]


def strip_prompt_labels(say: str) -> tuple[str, bool]:
    """Guard 5. A prompt fragment leaking into speech is a known small-model failure."""
    kept, dropped = [], False
    for s in _sentences(say):
        m = _LABEL.match(s)
        if m and m.group(1).strip() not in _ALLOW_CAPS:
            dropped = True
            continue
        kept.append(s)
    return " ".join(kept), dropped


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower()).strip()


def is_echo(say: str, utterance: str) -> bool:
    """The line is a fragment of what the candidate just said, not speech of our own.

    Observed live: the candidate said "I'd rather not go into that one, if that's
    alright" and the agent replied "if that's alright".
    """
    a, b = _norm(say), _norm(utterance)
    return bool(a) and len(a.split()) >= ECHO_MIN_WORDS and a in b


# Reading a control reply lives in `intent`, not here. Both vocabularies in this module used
# to be substring lists, which cannot see negation and read "No, I don't want to stop." as
# consent to stop (9.13).


# Asked OF the interviewer, not rhetorically. A question mark is the strong signal; these
# cover the speech-to-text case where punctuation is unreliable.
ASKS = ["what do you mean", "do you mean", "which do you mean", "sorry, do you",
        "could you clarify", "can you clarify", "what exactly", "are you asking",
        "can you repeat", "say that again", "not sure what you", "in what sense"]


# Granite opens 93% of its probes with this, and it will not stop being asked. Both a
# prohibition ("never open with Can you elaborate") and a positive instruction ("start with a
# question word") were measured: the first left it at 65%, the second at 93%, with 1 line in
# 41 complying. The length rule in the same prompt DID take, so this is not the model ignoring
# the prompt wholesale -- it is one phrase it cannot be talked out of. Section 7.10's rule
# applies: derive it deterministically instead of asking (log 8.17).
# Each hedge maps to the imperative an interviewer would have used instead. The mapping
# matters because stripping alone does not always leave a sentence: "an example of how X"
# opens on a question word but is a noun phrase, and shortcutting on that word produces
# "How working with more engineers would help?".
HEDGES = {
    "can you elaborate on ": "Tell me about ",
    "could you elaborate on ": "Tell me about ",
    "can you elaborate ": "Tell me about ",
    "can you describe ": "Describe ",
    "could you describe ": "Describe ",
    "can you explain ": "Explain ",
    "could you explain ": "Explain ",
    "can you clarify ": "Explain ",
    "could you clarify ": "Explain ",
    "can you tell me about ": "Tell me about ",
    "can you walk through ": "Walk me through ",
    "can you walk me through ": "Walk me through ",
    "could you walk me through ": "Walk me through ",
    "can you talk about ": "Tell me about ",
    "can you share ": "Tell me about ",
    # The `could you` mirrors that were missing, and the `more` variant. The table was built
    # from granite's phrasings, so a form granite never uses was never in it: seven of ten
    # exaone lines open "could you elaborate MORE on", one word off an entry that is present,
    # and it left an 18-word hedge in place of a 6-word imperative (9.50).
    "could you elaborate more on ": "Tell me about ",
    "can you elaborate more on ": "Tell me about ",
    "could you elaborate ": "Tell me about ",
    "could you tell me more about ": "Tell me about ",
    "can you tell me more about ": "Tell me about ",
    "could you tell me about ": "Tell me about ",
    "could you talk about ": "Tell me about ",
    "could you share ": "Tell me about ",
}
# Hedges whose remainder is always a complement, never a question clause.
COMPLEMENT_ONLY = {"can you give an example of ": "Give me an example of ",
                   "could you give an example of ": "Give me an example of "}
QUESTION_WORDS = ("what", "why", "how", "when", "who", "which", "where")


def _compare_form(say: str) -> str:
    """Normalise before comparing: rewritten, lowercase, letters and spaces only."""
    text, _ = direct(say)
    return re.sub(r"[^a-z ]", "", text.lower())


def direct(say: str) -> tuple[str, bool]:
    """Turn "Can you elaborate on what you measured?" into "What did you measure?"'s shape.

    A remainder that opens on a question word is already a question and only needs its
    capital back; anything else takes the hedge's imperative, which is how an interviewer
    would have said it in the first place.
    """
    low = say.lower()
    for table in (COMPLEMENT_ONLY, HEDGES):
        for h, imperative in table.items():
            if not low.startswith(h):
                continue
            rest = say[len(h):].strip().rstrip("?").rstrip()
            if not rest:
                return say, False
            # A question word here is NOT reliably the start of a question: "elaborate on
            # what you measured" is one, "explain why you thought that" is a subordinate
            # clause, and telling them apart needs syntax we do not have. "Tell me ..."
            # is grammatical in front of both, so it is used for both.
            if rest.split()[0].lower().strip(",'\"") in QUESTION_WORDS:
                imperative = "Tell me "
            if not rest.endswith("."):
                rest += "."
            return imperative + rest[0].lower() + rest[1:], True
    return say, False


def ask_is_theirs(ask: str, utterance: str) -> bool:
    """Is `ask` the CANDIDATE's question, or one the model wrote itself?

    The contract says to copy their question verbatim, and guard 2b treats a populated `ask`
    as evidence a question was asked. Measured live: the model put its OWN clarifying question
    there -- "Can you explain what you mean by 'schema change on a live system'?" -- against an
    utterance containing no question at all, and walked straight through the gate (log 8.21).

    Verbatim is too strict for speech (the model tidies punctuation), so this asks whether the
    content words are the candidate's.
    """
    a = {w for w in _norm(ask).split() if len(w) > 3}
    if not a:
        return False
    u = {w for w in _norm(utterance).split() if len(w) > 3}
    return len(a & u) / len(a) >= ASK_OVERLAP


def asks_a_question(utterance: str) -> bool:
    """Did the CANDIDATE ask something? Guard 2b's evidence test."""
    low = _norm(utterance)
    return "?" in (utterance or "") or any(p in low for p in ASKS)


def offers_a_choice(utterance: str) -> bool:
    """Is the clarification "did you mean A or B?" rather than "what does this mean?"

    A fact about the text, not a judgement (7.36): a question sentence with a disjunction in
    it. The two want different answers, and the generic line answers only the second -- live,
    "do you mean the WordPress site or the booking tool?" was met with "It just means a
    specific example from your own experience", which is a non-sequitur (9.17).
    """
    return any(re.search(r"\bor\b", s, re.I)
               for s in _sentences(utterance) if _is_question(s))


def asks_what_i_meant(utterance: str) -> bool:
    """Did they ask what the QUESTION means? The vocabulary only, never the bare "?".

    Guard 2b uses `asks_a_question` to admit a `clarify` the model already chose, where a
    loose test is safe because the model has already committed. This is the upgrade path, so
    it decides on its own and a question mark is far too loose -- most utterances carrying
    one are answers (9.15).
    """
    low = _norm(utterance)
    return any(p in low for p in ASKS)


# `skip` is the other HALT action and it had no evidence test at all, while `end` has had
# one since guard 2. Observed live: a junior candidate said "I haven't done that, the seniors
# do migrations" and the session recorded a REFUSAL -- which is what the report will say
# about them. Section 6.3 is explicit that cannot-answer is `reask`, not `skip` (log 8.20).
REFUSES = ["rather not", "prefer not", "d rather skip", "pass on that", "pass on this",
           "skip this", "skip that", "skip it", "move on from that", "not comfortable",
           "don t want to answer", "dont want to answer", "not going to answer",
           "next question please", "rather move on"]

# The reverse: no experience to draw on. These belong to `reask`, which puts the question a
# different way, and several of them then produced a real answer live.
CANNOT = ["haven t done", "havent done", "have not done", "never done", "not done that",
          "no experience", "haven t had", "havent had", "never had to", "can t think of",
          "cant think of", "nothing comes to mind", "not really had", "don t have one",
          "dont have one", "never really"]


# A regex rather than the plain list, because an adverb slips into the middle and a substring
# list cannot see it: "I can't REALLY think of one" read as an answer and got probed (9.20).
_ADV = r"(?:really |honestly |quite |actually )?"
_CANNOT = re.compile(
    r"\b(?:"
    r"(?:cant|cannot|couldnt|dont|didnt) " + _ADV + r"think of|"
    r"(?:havent|hadnt|have not) " + _ADV + r"(?:done|had)|"
    r"never (?:really )?(?:done|had to)|not done that|no experience|"
    r"nothing comes to mind|not really had|(?:dont|do not) have one|never really|"
    # 9.42's reask family. Both priced over the 914 stored answers before adding: "not
    # something i ve" fires on none of them, "dont think i ve" on three and all three are
    # genuine blanks. Two more candidates were REJECTED on the same test -- "didnt really
    # have" caught "I didn't really have a good argument for it", which is an answer, and
    # "hard to say" caught nothing in the corpus but takes "it's hard to say exactly, but we
    # cut p95 to 300ms" adversarially.
    r"not something i ve|(?:dont|didnt) think i ve"
    r")", re.I)

# Bare "not really" is a blank only where it ENDS the reply. The same endpoint reasoning
# `intent.STOP_REQUEST` takes, and for the same reason: unrestricted it caught "it's not
# really fair on whoever notices the email first", which is an answer about on-call load.
# `_norm` has already turned the punctuation into spaces, so the trailing particle is matched
# rather than a comma.
_CANNOT_TRAILING = re.compile(r"\bnot really(?:\s+(?:no|nope|nah))?\s*$", re.I)


# "Hmm." punctuates as a sentence of its own, which would hide the sentence that carries the
# reply. Same job as intent._split_particle: a particle is not the content.
_FILLER = frozenset({"hmm", "um", "uh", "oh", "well", "right", "ok", "okay", "so", "sure",
                     "sorry", "yeah", "yes", "no", "honestly", "hm", "erm"})


def _lead(utterance: str) -> str:
    """The first sentence that says something, fillers skipped."""
    for part in re.split(r"[.!?]", utterance or ""):
        words = _norm(part).split()
        if words and not set(words) <= _FILLER:
            return part
    return ""


def cannot_answer(utterance: str) -> bool:
    """No experience to draw on, as opposed to declining to share it.

    FIRST SENTENCE only. A cannot-answer OPENS with the inability; an answer that happens to
    name a gap reaches it after answering, and "I've made deploys fast; I've never had to
    make them provable" is one of the strongest replies in the corpus. Swept over 874 stored
    utterances this is the line that separates them: all 15 true positives put the phrase in
    sentence one and all 6 false positives put it later (9.23). The 3 it fires on in the
    60-fixture set are all sentence-one, so guarded accuracy cannot move.
    """
    # `_norm` strips the apostrophe and leaves "haven t"; rejoin so one spelling covers both.
    led = re.sub(r"(\w)n t\b", r"\1nt", _norm(_lead(utterance)))
    return bool(_CANNOT.search(led) or _CANNOT_TRAILING.search(led))


def refuses(utterance: str) -> bool:
    """Guard 2c's evidence test: the REFUSAL has to be in the candidate's own words."""
    low = _norm(utterance)
    # CANNOT beats REFUSES, so both tests have to read the same vocabulary or a phrasing one
    # of them recognises quietly changes what the other returns (section 6.3).
    if cannot_answer(utterance):
        return False
    return any(p in low for p in REFUSES)


def user_asked_to_stop(utterance: str) -> bool:
    """Guard 2's evidence test: the STOP has to be in the candidate's own words."""
    return intent.asked_to_stop(utterance)


def skip_requested(utterance: str) -> bool:
    """Guard 2c's evidence test, over both halves: a refusal, or a procedural request.

    `REFUSES` reads a candidate declining the question. It cannot reach one who declines
    nothing and simply asks for the next question, which is 9.39's surviving crossing.
    """
    # 6.3's ordering, and `refuses()` encodes the same rule internally: no experience to
    # draw on is `reask`, and must not be read as either kind of skip.
    if cannot_answer(utterance):
        return False
    return refuses(utterance) or intent.asked_to_skip(utterance)


def apply(raw: dict | None, utterance: str, previous_says: list[str],
          trust_ok: bool = True) -> Guarded:
    """Run the guards in order and return the decision a handler may act on."""
    applied: list[str] = []

    if not isinstance(raw, dict) or raw.get("act") not in ACTIONS:
        return Guarded("probe", "", False, "", ["invalid->probe"], needs_regeneration=True)

    act = raw["act"]
    say = (raw.get("say") or "").strip()
    ok = bool(raw.get("ok"))
    ask = (raw.get("ask") or "").strip()

    # 1. Invented-question strip.
    if act in ("advance", "end"):
        qs = [s for s in _sentences(say) if _is_question(s)]
        if qs:
            # `ok` decides this for `advance` only. On `advance` a false `ok` is the model
            # contradicting itself -- it says move on and writes a follow-up -- so the
            # question is the honest part.
            #
            # On `end` it means nothing: `ok` asks whether the reply answered the QUESTION,
            # and "I need to stop, sorry" never does. Reading that as self-contradiction
            # turned a grounded stop request into a probe, which is guard 2's call and not
            # this one's. Strip the question and let guard 2 decide whether the end stands
            # -- an ungrounded one still becomes `probe` two lines below (9.19).
            if not ok and act == "advance" and trust_ok:
                act, say, applied = "probe", say, applied + ["invented-question->probe"]
            else:
                say = " ".join(s for s in _sentences(say) if not _is_question(s))
                applied.append("invented-question-dropped")

    # 1b. The advance/ok contradiction, which is guard 1's rule with the question dropped.
    # `advance` claims the reply answers the question and `ok=false` says it does not, so the
    # model has contradicted itself and `ok` is the field it was asked to reason about.
    #
    # Measured on llama-3.2-3b over the 60 fixtures (9.42): it advanced 13 times, all ten
    # gold=`advance` carried ok=true, and both ok=false advances were gold=`probe`. Perfect
    # discrimination, so this costs nothing and recovers two.
    if act == "advance" and not ok and trust_ok:
        act, applied = "probe", applied + ["advance-not-ok->probe"]

    # 2. `end` gate. Wrongly continuing costs seconds; wrongly ending loses the session.
    if act == "end" and not user_asked_to_stop(utterance):
        act, applied = "probe", applied + ["end-ungrounded->probe"]

    # 2b. `clarify` gate, and it is the same shape as guard 2: an action that costs the
    # session something needs evidence in the candidate's own words. The contract defines
    # clarify as "they asked what the question means", with `ask` ALWAYS populated -- and
    # measured live it fired 18 times in 20 with an empty `ask` and no question asked
    # (log 8.17). That matters beyond tidiness: clarify is the one action that does not
    # consume the follow-up budget (section 6.3), so an unguarded clarify is an unbudgeted
    # probe, and the model had found it.
    if act == "clarify" and ask and not ask_is_theirs(ask, utterance):
        # The model authored the question it is citing as evidence. Discard it, then let the
        # gate below judge on the utterance alone.
        ask, applied = "", applied + ["ask-not-theirs-dropped"]
    if act == "clarify" and not ask and not asks_a_question(utterance):
        act, applied = "probe", applied + ["clarify-ungrounded->probe"]

    # 2c. `skip` gate, symmetric with guard 2 and guard 2b. Liveness does not depend on the
    # model getting this right: the follow-up cap forces `advance` once the allowance is
    # spent, so a refusal phrased outside the vocabulary is probed at most once more and the
    # interview moves on regardless. The gate cannot trap anyone.
    if act == "skip" and not skip_requested(utterance):
        act, applied = "reask", applied + ["skip-ungrounded->reask"]

    # 2d/2e. The other half of 2b and 2c, and the reason it exists is that every gate above
    # only ever DOWNGRADES. Rec 2 built the upgrade for `stop` and 9.17 built it for
    # `clarify`; `skip` and `reask` had an evidence test and no upgrade, so a candidate whose
    # words plainly said one of them got whatever the model had picked instead. Both cost a
    # real turn live on Yi (9.20):
    #
    #   "I'd rather not go into that one"  -> "Could you say a bit more about that?"
    #   "I can't really think of one"      -> "What did you measure?"
    #
    # Order matters and follows 6.3: CANNOT beats REFUSES, which `refuses()` already encodes
    # by returning False on the cannot-answer vocabulary. `end` is never touched -- a
    # grounded stop outranks both, and an ungrounded one guard 2 has already downgraded.
    if act in ("advance", "probe", "reask", "clarify") and skip_requested(utterance):
        act, applied = "skip", applied + ["refusal->skip"]
    elif act in ("advance", "probe", "clarify") and cannot_answer(utterance):
        act, applied = "reask", applied + ["cannot->reask"]

    # 3. Repetition guard. Both sides go through `direct()` first: `previous_says` holds
    # lines that were already rewritten, so comparing raw text against them measured the
    # hedge as much as the content, and a verbatim repeat of a hedged line scored 0.78 --
    # under the limit, and missed (log 8.18).
    regen = False
    if act in ("probe", "reask") and say:
        here = _compare_form(say)
        # A line with no letters normalises to "", and two empty strings compare as
        # identical -- which would make every such turn a repeat of every other.
        if here and any(
                difflib.SequenceMatcher(None, here, _compare_form(prev)).ratio()
                >= SIMILARITY_LIMIT
                for prev in previous_says if _compare_form(prev)):
            regen = True
            applied.append("repeated-say->regenerate")

    # 3b. Echo guard. A `say` lifted verbatim out of the candidate's own utterance is not
    # speech; drop it and let the handler substitute its fallback line.
    if say and is_echo(say, utterance):
        say = ""
        applied.append("echoed-utterance-dropped")

    # 5 before 4: dropping a label can leave the line short enough not to need truncating.
    if say:
        say, dropped = strip_prompt_labels(say)
        if dropped:
            applied.append("prompt-label-stripped")

    # 3c. Directness. Purely cosmetic -- it rewrites speech, never a decision -- so it runs
    # after every action guard and before truncation, since shortening the opener can leave
    # a line that no longer needs cutting.
    if act in ("probe", "reask", "clarify") and say:
        say, changed = direct(say)
        if changed:
            applied.append("hedge-stripped")

    # 4. The closing actions do not speak at all. Across 76 stored sessions, 50 surviving
    # `advance` lines held 14 distinct strings and not one was a sentence -- `ok` 29 times,
    # then topic labels ("project management experience", "Redis failure loss of
    # assignments."). `skip` and `end` were the same, including the JSON field name `ask`
    # spoken aloud. The handlers already have the right line for each, and on advance the
    # next question follows immediately, so there is nothing to say (log 8.18).
    #
    # This reverses section 8.5, which deferred it as "worth a prompt iteration rather than
    # a guard". Three prompt iterations have now failed on this model's phrasing habits
    # (7.10, 8.17, and the question-word rule V5 removes).
    if act in CLOSING_ACTIONS:
        if say:
            applied.append("closing-say-dropped")
        say = ""
    else:
        # One sentence, deterministically. The prompt asks for one question in at most 15
        # words and is ignored 53% of the time; and 7.13's objection to a cap -- that
        # `maxLength` closes the string mid-clause -- does not apply to a sentence boundary.
        # This also subsumes the two-questions-per-turn fault: the second one is a second
        # sentence (log 8.18).
        parts = _sentences(say)
        if len(parts) > 1:
            # Keep the sentence that ASKS, not the first one. For granite they are the same
            # sentence every time, which is why the assumption survived unexamined: 0 of its
            # 22 spoken probes lose their question. A model that acknowledges before asking
            # shipped the acknowledgement and dropped the question -- exaone-3.5 wrote "That
            # sounds interesting! Could you elaborate on the bottlenecks?" and spoke "That
            # sounds interesting!", in 52% of its probes (9.46).
            #
            # `direct()` above can strip a question mark, but only off a line that STARTS
            # with a hedge, and such a line has no acknowledgement in front to be confused
            # with. So the question is still findable here.
            asks = [p for p in parts if _is_question(p)]
            say = asks[0] if asks else parts[0]
            applied.append("extra-sentences-dropped")
            # 3c ran BEFORE this and saw the acknowledgement, not the question, so a hedge on
            # the surviving sentence was never rewritten: three of exaone's ten substituted
            # lines carried `extra-sentences-dropped` with no `hedge-stripped` (9.50). Rewrite
            # the sentence that actually survives. Cheap and idempotent -- a line 3c already
            # handled no longer starts with a hedge, so this is a no-op on it.
            if act in ("probe", "reask", "clarify"):
                say, changed = direct(say)
                if changed and "hedge-stripped" not in applied:
                    applied.append("hedge-stripped")
        cut = _truncate(say)
        if cut != say:
            applied.append("say-truncated")
        say = cut

    return Guarded(act, say, ok, ask, applied, needs_regeneration=regen)
