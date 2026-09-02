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
# A fresh interrogative after explicit clause punctuation is a second request even when the
# model puts both under one final question mark. Requiring both the punctuation and the new
# question word, or the captured auxiliary-led "did you" form, keeps ordinary noun
# coordination ("metrics or feedback") and either/or clarification intact.
_COORDINATED_REQUEST = re.compile(
    r"[,;]\s*(?:and|or)\s+(?=(?:(?:what|why|how|when|who|which|where)\b|did you\b))",
    re.I)
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


def _one_request(text: str) -> tuple[str, bool]:
    """Keep the first of two explicitly coordinated interrogative clauses."""
    match = _COORDINATED_REQUEST.search(text or "")
    if not match:
        return text, False
    first = text[:match.start()].rstrip()
    if first and first[-1] not in ".!?":
        first += "?" if (text or "").rstrip().endswith("?") else "."
    return first, True


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

# Elliptical speech puts the thing being narrowed before the question word: "Quickly
# meaning what, a few days?". The comma and non-empty text after it prove that this first
# question carries an alternative; the scope words alone also occur in ordinary answers.
_SEGMENTED_CHOICE_SCOPE = re.compile(
    r"\b(?:mean|means|meaning) (?:what|which|how)\b[^?,]*,\s*[^?]+\?\s*$", re.I)


# Polite filler persisted despite both negative and positive prompt instructions. Because the
# length rule in the same prompt did take, this is handled as a deterministic speech rewrite
# rather than as another prompt iteration (MODEL_EXPERIMENTING_LOG.md).
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
    # The `could you` mirrors and the `more` variant are separate forms in real output; they
    # must normalise to the same direct question as their `can you` equivalents.
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
    questions = [s for s in _sentences(utterance) if _is_question(s)]
    if any(re.search(r"\bor\b", s, re.I) for s in questions):
        return True
    # Speech can segment the alternatives: "meaning what, a few days? A sprint?".
    # The scope phrase grounds the first part as clarification, and the deliberately short
    # second question is the alternative rather than another independent request.
    return (len(questions) >= 2 and _SEGMENTED_CHOICE_SCOPE.search(questions[0]) is not None
            and any(len(_norm(s).split()) <= 4 for s in questions[1:]))


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
    # genuine blanks. Two broader candidates stay out of this expression: "didnt really
    # have" and "hard to say" both need the structural gates below to preserve real answers
    # that recover with "but", "so I", or a concrete result.
    r"not something i ve|(?:dont|didnt) think i ve"
    r")", re.I)

# Bare "not really" is a blank only where it ENDS the reply. The same endpoint reasoning
# `intent.STOP_REQUEST` takes, and for the same reason: unrestricted it caught "it's not
# really fair on whoever notices the email first", which is an answer about on-call load.
# `_norm` has already turned the punctuation into spaces, so the trailing particle is matched
# rather than a comma. This established rule reads the substantive lead, allowing a later
# sentence to reinforce the blank without hiding it.
_CANNOT_LEAD_TRAILING = re.compile(r"\bnot really(?:\s+(?:no|nope|nah))?\s*$", re.I)

# These weaker dependency phrases must end the complete reply. Unlike a bare "not really",
# a later sentence can turn "hard to say" into a concrete answer.
_CANNOT_TRAILING = re.compile(r"\b(?:hard|difficult|impossible) to say\s*$", re.I)

# A missing workplace process is the same no-experience case as "never had to", but the
# broad phrase also opens real answers: "we didn't really have a runbook, so I wrote one".
# Admit only a plain absence anchored to the workplace where it was absent, not any sentence
# that opens with the gap and then describes an action. This is deliberately separate from
# `_CANNOT`, where a substring cannot express the endpoint or recovery exclusion.
_CANNOT_ABSENT = re.compile(
    r"\b(?:i|we) (?:didnt|did not) really have\b.*"
    r"\b(?:where i worked|in that role|at that company|on that team)\s*$", re.I)
_CANNOT_RECOVERY = re.compile(r"\b(?:but|except|other than|so i|so we|and i|and we)\b", re.I)


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

    The established inability vocabulary is read from the FIRST SENTENCE only. A
    cannot-answer OPENS with the inability; an answer that happens to name a gap reaches it
    after answering. The narrower endpoint rules are instead checked against the complete
    reply, so concrete recovery in a later sentence prevents a low-confidence reask.
    """
    # `_norm` strips the apostrophe and leaves "haven t"; rejoin so one spelling covers both.
    led = re.sub(r"(\w)n t\b", r"\1nt", _norm(_lead(utterance)))
    whole = re.sub(r"(\w)n t\b", r"\1nt", _norm(utterance))
    if _CANNOT.search(led) or _CANNOT_LEAD_TRAILING.search(led):
        return True

    # The new endpoint phrases are weaker evidence than an explicit refusal. Suppressing
    # only these rules preserves the established CANNOT-over-REFUSES ordering for direct
    # no-experience language while keeping consent/control language in the skip family.
    explicit_skip = (any(p in whole for p in REFUSES)
                     or intent.asked_to_skip(utterance))
    if explicit_skip:
        return False

    absent_only = (_CANNOT_ABSENT.search(whole) is not None
                   and _CANNOT_RECOVERY.search(whole) is None)
    return bool(_CANNOT_TRAILING.search(whole) or absent_only)


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


def apply(raw: dict | None, utterance: str, previous_says: list[str]) -> Guarded:
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
            # `ok` no longer decides this. It was read as self-contradiction on `advance`,
            # which is a llama-3.2-3b calibration: that model carries ok=true on all ten
            # gold=`advance` fixtures, so the rule never fired for it (9.42).
            #
            # qwen3-4b-instruct-2507 does not share the calibration. It acknowledges and then
            # bridges with a question ("That's a solid approach -- how did you ensure data
            # consistency?"), carrying ok=false on advances that are correct. Reading that as
            # contradiction cost 4 of its 5 misses. Its `act` needs no second opinion: over
            # the 60 fixtures it says `advance` exactly ten times and all ten are gold, which
            # is the precision the old rule assumed for llama and llama does not have (it
            # says `advance` twelve times for ten golds).
            #
            # So the question is always the decoration and the act always stands. The
            # acknowledgement in front of it is what the candidate hears.
            say = " ".join(s for s in _sentences(say) if not _is_question(s))
            applied.append("invented-question-dropped")

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
    # real turn in a captured live interview:
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
            # Keep the sentence that ASKS, not the first one. Otherwise an acknowledgement
            # before a question can survive while the actual question is discarded.
            #
            # `direct()` above can strip a question mark, but only off a line that STARTS
            # with a hedge, and such a line has no acknowledgement in front to be confused
            # with. So the question is still findable here.
            asks = [p for p in parts if _is_question(p)]
            say = asks[0] if asks else parts[0]
            applied.append("extra-sentences-dropped")
            # 3c ran BEFORE this and saw the acknowledgement, not the question, so a hedge on
            # the surviving sentence would never be rewritten. Rewrite the sentence that
            # actually survives. Cheap and idempotent: a line 3c already handled no longer
            # starts with a hedge, so this is a no-op on it.
            if act in ("probe", "reask", "clarify"):
                say, changed = direct(say)
                if changed and "hedge-stripped" not in applied:
                    applied.append("hedge-stripped")
        # Compound questions are KEPT. A two-part question is ordinary interviewer behaviour --
        # one of the scripted questions is itself double-barrelled -- and trimming cost more
        # than it bought: keeping only the first clause discarded the better half often enough
        # to notice ("What's your experience with Redis?" surviving while "how would you handle
        # rate limiting?" was cut), and it halved the text the focus classifier reads, so a line
        # that WOULD have named a focus stopped naming one and fell through to the repair.
        # Measured over 150 stored decisions, trimming was the only difference between 0 repairs
        # and 2. `_one_request` is kept because `direct()` and the tests still use the shape.
        cut = _truncate(say)
        if cut != say:
            applied.append("say-truncated")
        say = cut

    return Guarded(act, say, ok, ask, applied, needs_regeneration=regen)
