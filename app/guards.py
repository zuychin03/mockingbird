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


def cannot_answer(utterance: str) -> bool:
    """No experience to draw on, as opposed to declining to share it."""
    return any(p in _norm(utterance) for p in CANNOT)


def refuses(utterance: str) -> bool:
    """Guard 2c's evidence test: the REFUSAL has to be in the candidate's own words."""
    low = _norm(utterance)
    if any(p in low for p in CANNOT):
        return False
    return any(p in low for p in REFUSES)


def user_asked_to_stop(utterance: str) -> bool:
    """Guard 2's evidence test: the STOP has to be in the candidate's own words."""
    return intent.asked_to_stop(utterance)


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
            if not ok:
                # The model agrees it is not finished, so the question is the honest part.
                act, say, applied = "probe", say, applied + ["invented-question->probe"]
            else:
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
    if act == "skip" and not refuses(utterance):
        act, applied = "reask", applied + ["skip-ungrounded->reask"]

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
            say = parts[0]
            applied.append("extra-sentences-dropped")
        cut = _truncate(say)
        if cut != say:
            applied.append("say-truncated")
        say = cut

    return Guarded(act, say, ok, ask, applied, needs_regeneration=regen)
