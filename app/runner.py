"""The session runner. Plan sections 5.1 and 5.2.1.

The runner owns the loop. It decides when a turn is committed, what to speak, and when to
give up; it calls into stateless per-turn functions and gets a decision back. In phase 2
the same runner owns the microphone, the endpointer and the playback thread -- which is the
whole reason it is shaped this way. If the graph owned the loop, barge-in and the silence
watchdog would have to be retrofitted into a construct that cannot express them.

`session_graph` is deliberately not a graph (section 5.2.1): one schema-constrained call and
a dispatch over pure functions.

The second structural rule is enforced here rather than at the UI: `live_view` is the ONLY
thing a participant may see. Judgement fields -- `ok`, the posterior, guard names -- go to
storage and the report and are never serialised onto the live channel. An interviewee who
can see the agent deciding their answer is weak will change their answer, and the assessment
stops measuring what it claims to (section 12.6.1).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from . import (budget, contract, direction, embed, focus, guards, intent,
               result_check, session)
from .history import History
from .provider import Completion, Provider

# `clarify` deliberately does not consume the follow-up budget (section 6.3), which leaves
# the loop with no way to terminate if the model keeps choosing it. Observed live: two
# clarifies in a row on one question. This is the liveness backstop, not a budget.
#
# Past the limit the runner no longer downgrades silently to `reask`. Re-asking a question
# somebody has just said they do not understand is the least useful thing available, so it
# OFFERS to skip instead, and only auto-skips if the offer is declined and one further
# explanation still does not land (log 8.16).
# Consecutive answers that add no new part before the question is closed. Plan 1c.5's number,
# and its reasoning is about the failure mode rather than conservatism: one no-gain turn
# misfires on a candidate who rambles for a turn and then delivers the result. Measured 14/16
# there, with both errors on the safe side.
STALL_LIMIT = 2

CLARIFY_LIMIT = 2
CLARIFY_EXTRA = 1          # further attempts granted when the candidate declines the offer

SKIP_OFFER = ("We've been round this one a couple of times. Would you like to skip it and "
              "move on, or keep going?")
SKIP_DECLINED = "No problem -- let me put it another way."
# No requeue exists -- `_close_question` appends and increments, and nothing revisits. The
# line used to promise "come back if there's time", which the runner cannot honour.
SKIP_ACK = "That one isn't landing, so let's leave it there and move on."

# Rec 2, approved: the stop-detector is symmetric. Guard 2 DOWNGRADES an `end` the
# candidate never asked for; this UPGRADES the reverse case -- their own words clearly ask
# to stop and the model chose something else. Observed live: "something's come up and I
# need to stop here" was read as `skip`.
#
# `confirm` is runner-side only and deliberately not a seventh enum value: adding one would
# invalidate the 6-action schema every Tier 1 number was measured on.
CONFIRM_LINE = ("Just to check -- do you want to stop the interview here, "
                "or skip this question and carry on?")
# The line above offers three outcomes, so a bare "yes" against it decides nothing. Rather
# than guess, narrow to a question a bare yes or no can actually answer -- once, and then
# ambiguity carries on. The old parser guessed, and guessed `end` (9.13).
CONFIRM_NARROW = ("Sorry, let me put that more simply -- would you like to stop the "
                  "interview? Yes or no.")

# A candidate question in the middle of an assessable question. It is not an answer, so it
# does not go to the extractor, does not consume a follow-up, and is not scored -- which is
# the whole defect: one was extracted as STAR evidence and closed the question it interrupted.
#
# The line promises nothing. `SKIP_ACK` used to say "come back if there's time" and the runner
# has no requeue, so the same mistake is not made twice here.
QUESTION_DEFERRED = "Good question. Let's finish this one first."
# Below this, the text before a question is throat-clearing ("Actually, can I ask -") rather
# than an answer, and recording it would put filler in front of the extractor.
ANSWER_PART_MIN_WORDS = 8
# The closing phase. There is no employer behind this interview, and inventing an answer about
# a real workplace would be the one thing a practice interviewer must not do.
QUESTION_NOTED = ("That's a good one to ask. I can't answer for a real employer, so rather "
                  "than invent something I've put it in your report. Anything else?")
CLOSING_ACK = "Thanks -- that's everything from me."
# Answer to "did you mean A or B?" when both are the candidate's own examples. The second
# clause covers the design question, where naming the assumption IS the answer.
CLARIFY_EITHER = "Your choice -- take whichever you can say most about, and tell me which."


# STAR pacing belongs to the phases that hold a story. Warmup and closing inherited
# `observation_shape: star` by default and were protected only by their probe budgets, so
# the stall counter was closing questions on the absence of parts they were never going to
# contain. Keyed on the phase's declared type now, which is the field that says what the
# phase is for.
STAR_PACED_TYPES = frozenset({"adaptive_discussion"})

# Below this, a question the focus regex cannot name is almost always a bare generic probe
# rather than a substantive one. Measured over two live sessions: every unnameable line worth
# keeping ran 10 words or more ("What was the colleague's reaction when you gave him
# feedback?"), and every generic probe ran 8 or fewer ("What was your approach?", "What
# happened next?"). Terse unnameable lines still go to the repair, which is where a generic
# probe has something to gain.
UNNAMED_FOCUS_MIN_WORDS = 10


# Llama's retained questions are normally concise. Twenty-five words leaves room for a
# detailed single-focus probe, while the independent compound and focus guards still reject
# unsuitable lines and the shortening retry remains a deterministic backstop.
#
# The prompt now asks for the same 25. It asked for 15 until 31/08, and the gap was measured
# before it was closed: the cap had never fired in production -- median 11 words, p90 16 and a
# longest-ever 22 across 437 stored questions -- so the instruction was what shaped the line,
# and raising it to 25 moved the median one word while DOUBLING the compound rate, 5.2% to
# 10.3%, classification flat. The model spends the extra budget on a second question joined
# with "and". That cost is absorbed by `compound-request-trimmed`, which is deterministic and
# free; it is a known trade, not an oversight.
MAX_SAY_WORDS = 25


# Distinguishes "caller said nothing" from "caller explicitly disabled semantic comparison",
# which None has to mean at the call site for `rewords` to fall back.
_DEFAULT = object()


def _raw_say(raw: dict | None) -> str | None:
    """Return the model's speech field without applying guard normalisation."""
    say = raw.get("say") if isinstance(raw, dict) else None
    return say if isinstance(say, str) else None


@dataclass
class Spoken:
    """What the participant is allowed to receive. Nothing else crosses the live channel."""
    text: str
    question_id: str
    question_index: int
    question_total: int
    finished: bool = False
    # Progress AFTER this event. An acknowledgement belongs to the question it closes, so
    # the two cannot be the same field: `_dispatch` closed the question and incremented the
    # index before building this, and the ack went out carrying the NEXT question's identity.
    next_index: int = 0


@dataclass
class TurnOutcome:
    act: str
    spoken: Spoken
    closed_question: bool
    end_session: bool


# Why a question closed. `closed_by` records only `advance`, `skip` or `end`, which collapses
# an answer the model was satisfied with, a question that ran out of turns, one the candidate
# refused, and one the model could not find new words for -- and the report and every pacing
# analysis need to tell those apart. Section 9.9's headline number (11.6% of advances chosen
# by the model) had to be reconstructed by hand from guard strings for exactly this reason.
#
# Derived rather than decided: the guard names already carry it, and the rules that set them
# are mutually exclusive by construction -- each checks `g.act in ("probe", "reask")`, so the
# first to force `advance` stops the rest from firing.
CLOSE_REASONS = (
    ("observations-complete->advance", "evidence_complete"),
    ("no-new-observation->advance", "no_new_evidence"),
    ("regeneration-repeated->advance", "wording_exhausted"),
    ("detour-budget->advance", "detour_budget_spent"),
    ("closing->advance", "closing_complete"),
    ("clarify-limit->auto-skip", "clarification_exhausted"),
    ("skip-offer-accepted", "skip_consented"),
    ("confirmed-skip", "skip_consented"),
    ("confirmed-stop", "ended_early"),
    ("pool-exhausted->advance", "budget_exhausted"),
    ("follow-up-cap->advance", "budget_exhausted"),
)


def close_reason(act: str, applied: list[str]) -> str:
    for name, reason in CLOSE_REASONS:
        if name in applied:
            return reason
    if act == "end":
        return "ended_early"
    # Guard 2c downgrades an ungrounded `skip` to `reask`, so one that survives to here has
    # the refusal in the candidate's own words.
    if act == "skip":
        return "refused"
    return "model_advanced"


def live_view(spoken: Spoken) -> dict:
    return {"say": spoken.text, "question": spoken.question_index,
            "of": spoken.question_total, "next": spoken.next_index,
            "finished": spoken.finished}


class Runner:
    def __init__(self, provider: Provider, plan: dict, state: session.SessionState,
                 pool: int | None = None, pace: bool = True,
                 observe_fn: Callable[[str, str, str], Awaitable] | None = None,
                 max_say_words: int | None = MAX_SAY_WORDS,
                 similarity: Callable[[str, str], float | None] | None = _DEFAULT):
        self.max_say_words = max_say_words
        # `observe_fn` turns one answer into an Observation. Injected rather than imported so
        # the runner keeps no dependency on the Stage 2 extractor, and so a test can drive the
        # stop rule without a model. None disables the adaptive stop and leaves the cap alone,
        # which is what every pre-9.10 harness expects; the entry points supply a real one.
        self.observe_fn = observe_fn
        self.provider = provider
        self.plan = plan
        self.state = state
        self.questions = list(session.iter_questions(plan))
        self.history = History()
        self.index = 0
        self.follow_ups_used = 0        # probe and reask together
        self.clarifies_used = 0
        self.clarify_extra = 0
        self.skip_offered = False
        self.design_followed_up = False
        # Plan 1c.5's adaptive stop. `seen` is the accumulated situation/action/result triple
        # for the current question; `stalls` counts consecutive answers that added nothing to
        # it. Accumulated in PYTHON from per-answer extractions -- the model is asked what one
        # answer contains, never what the question as a whole is worth (7.10, 7.36).
        self.seen: set[str] = set()
        self.stalls = 0
        self._pending: asyncio.Task | None = None
        self.focus_used: set[str] = set()
        # What the CANDIDATE asked, kept apart from what they answered. Feeds the report and
        # bounds the closing phase; never reaches the extractor or the rubric.
        self.questions_asked: list[str] = []
        self.said_this_question: list[str] = []
        # Semantic probe comparison. Returns None whenever the optional embedding model is
        # absent, and `rewords` falls back to word overlap -- an interview must not depend on
        # it. Injectable so a test can pin the comparison instead of reaching for a server.
        self.similarity = embed.similarity if similarity is _DEFAULT else similarity
        # The previous probe on this question and the focus it was charged, for `rewords`.
        self.last_probe: tuple[str, tuple[str, ...]] | None = None
        # Survives a question boundary, unlike `said_this_question`. All four verbatim
        # repeats in 9.7 were on different questions, so a per-question record could not
        # have seen any of them.
        self.said_this_session: list[str] = []
        self.answers_this_question: list[str] = []
        self.awaiting_confirm = False
        self.awaiting_skip_offer = False
        # One narrowing re-ask per confirmation, then ambiguity carries on rather than
        # looping. Reset with each fresh confirmation, not per question.
        self.confirm_narrowed = False
        self.pace = pace
        # No session turn budget. Length follows from the caps; only the overflow reserve is
        # configured, and it scales with the plan so another role or a custom question set
        # needs no re-tuning (log 8.16).
        self.pool = budget.session_pool(len(self.questions)) if pool is None else pool

    # ---------------------------------------------------------------- properties
    @property
    def current(self) -> dict | None:
        return self.questions[self.index] if self.index < len(self.questions) else None

    @property
    def done(self) -> bool:
        return self.index >= len(self.questions) or self.state.status != "running"

    def _spoken(self, text: str, finished: bool = False,
                about: dict | None = None, at: int | None = None) -> Spoken:
        """`about` and `at` name the question this line BELONGS to. They default to the
        current one, which is right for `ask` and wrong for an acknowledgement -- by the time
        `_dispatch` builds one, the question it acknowledges has already been closed."""
        q = self.current if about is None else about
        i = self.index if at is None else at
        return Spoken(text=text,
                      question_id=q["question_id"] if q else "",
                      question_index=min(i + 1, len(self.questions)),
                      question_total=len(self.questions),
                      next_index=min(self.index + 1, len(self.questions)),
                      finished=finished)

    def _star_paced(self, q: dict | None) -> bool:
        """Does 1c.5's situation/action/result stop rule apply to this question?"""
        if not q:
            return False
        return (q.get("type", "adaptive_discussion") in STAR_PACED_TYPES
                and q.get("observation_shape", "star") == "star")

    # ---------------------------------------------------------------- the turn
    async def ask(self) -> Spoken:
        """Open the current question. Refreshes history first if a question just closed."""
        if self.history.stale:
            await self.history.refresh(self.provider)
        q = self.current
        if q is None:
            return self._spoken("That's everything. Thanks for your time.", finished=True)
        return self._spoken(q["question"])

    async def _decide(self, utterance: str, retry_of: list[str],
                      want: str | None = None,
                      too_long: int | None = None) -> tuple[Completion, dict | None]:
        q = self.current
        system = contract.SYSTEM
        if want:
            system += focus.instruction(want)
        if too_long:
            # The second retry reason, and deliberately not folded into `retry_of`: that one
            # asks for a DIFFERENT line, this asks for the SAME request in fewer words, and a
            # model told to do both at once does neither (9.52).
            system += ("\n\nYour last question was too long. Ask the same thing again in at "
                       "most %d words. One short question, no preamble." % too_long)
        if retry_of:
            system += ("\n\nYou have already said the following on this question. Say something "
                       "materially different:\n" + "\n".join("- " + s for s in retry_of))
        user = contract.render(q["question"], utterance, self.history.render())
        out = await self.provider.complete(
            system, user, schema=contract.TURN_SCHEMA, max_tokens=400,
            enum_field="act", enum_values=contract.ACTIONS)
        return out, out.json()

    async def _repair_speech(self, utterance: str, want: str, rejected: str,
                             trigger: str) -> tuple[str | None, dict, list[str]]:
        """Ask only for replacement speech, then accept it under the existing guards.

        The synthetic decision below is deliberately constructed by the harness. The model
        response cannot carry an action, `ok` judgement or candidate question through this
        boundary, even if a non-conforming provider returns extra JSON properties.
        """
        cap = self.max_say_words
        system = contract.SPEECH_SYSTEM
        system += ("\n\nRequired focus: %s. The question must ask only about that."
                   % focus.FOCUS[want])
        if cap:
            system += "\nUse at most %d words." % cap
        # Do not quote negative examples here. In the first live run Llama copied the
        # rejected line on two retries and copied a previous session question into an
        # unrelated scenario once. Repetition is cheaper and more reliable to reject below.

        q = self.current
        user = contract.render(q["question"], utterance, self.history.render())
        out = await self.provider.complete(
            system, user, schema=contract.SPEECH_SCHEMA, max_tokens=100)
        raw = out.json()
        raw_say = _raw_say(raw)
        valid = isinstance(raw, dict) and isinstance(raw_say, str)
        synthetic = ({"act": "probe", "say": raw_say, "ok": False, "ask": ""}
                     if valid else None)
        checked = guards.apply(
            synthetic, utterance,
            self.said_this_question + ([rejected] if rejected else []))
        got = sorted(focus.classify(checked.say))

        rejection: str | None = None
        if not valid:
            rejection = "invalid"
        elif not raw_say.strip() or not checked.say:
            rejection = "empty"
        elif (raw_say.count("?") != 1
              or "compound-request-trimmed" in checked.applied
              or "extra-sentences-dropped" in checked.applied):
            rejection = "multi_request"
        elif checked.needs_regeneration or checked.say in self.said_this_session:
            rejection = "repeated"
        elif cap and len(checked.say.split()) > cap:
            rejection = "over_length"
        elif want not in got:
            rejection = "off_focus"

        attempt = {
            "trigger": trigger,
            "say_raw": raw_say,
            "say": checked.say,
            "focus": got,
            "accepted": rejection is None,
            "rejection": rejection,
            "guards": checked.applied,
            "prompt_tokens": out.prompt_tokens,
            "decode_tokens": out.decode_tokens,
            "wall_ms": round(out.wall_ms, 1),
        }
        return (checked.say if rejection is None else None), attempt, checked.applied

    def _user_questions_turn(self, utterance: str, q: dict) -> TurnOutcome:
        """The closing phase. Costs no model call and produces no score.

        `detour_budget` bounds it, which is the first time that field has had a consumer:
        it was configured on every phase and read by nothing.
        """
        if direction.is_candidate_question(utterance):
            # Onto `questions_asked` and NOT onto `answers_this_question`. The transcript
            # still has the utterance verbatim; what the two lists separate is what the
            # report may treat as an answer.
            self.questions_asked.append(utterance)
            if len(self.questions_asked) >= q.get("detour_budget", 0):
                g = guards.Guarded("advance", QUESTION_NOTED + " " + CLOSING_ACK, False, "",
                                   ["candidate-question->noted", "detour-budget->advance"])
            else:
                g = guards.Guarded("clarify", QUESTION_NOTED, False, "",
                                   ["candidate-question->noted"])
            return self._dispatch(g, utterance, Completion(text=""))

        if guards.user_asked_to_stop(utterance):
            self.awaiting_confirm = True
            self.confirm_narrowed = False
            g = guards.Guarded("clarify", CONFIRM_LINE, False, "", ["stop-detected->confirm"])
        else:
            # Nothing they said reads as a question, so they are done.
            g = guards.Guarded("advance", CLOSING_ACK, False, "", ["closing->advance"])
        self.answers_this_question.append(utterance)
        return self._dispatch(g, utterance, Completion(text=""))

    def _observe_later(self, utterance: str) -> None:
        """Extract this answer's parts off the live path.

        Per ANSWER, not over the accumulated text. Two reasons, and the second is the one that
        matters: a single answer is cheaper to extract, and accumulated extraction fabricates
        a `result` from filler on 8% of answers (9.9), which 1c.5 predicted and which the plan
        says single-answer extraction at 10/10 does not do. Accumulating in Python instead
        keeps the model on the question it is reliable at.

        Fire-and-forget. It is awaited at the start of the next turn, so it runs while the
        candidate is composing their reply -- dead time that costs the turn nothing. NFR-1
        measures the decision path, and this is not on it.
        """
        q = self.current
        # S/A/R questions only. A design answer has no situation, action or result (9.6), so
        # extracting them yields nothing and `stalls` would close the question for a reason
        # that is not true of it. Design pacing is the gap check below plus the cap; a
        # completeness rule for hypotheticals has not been measured and is not invented here.
        if not self.observe_fn or not self._star_paced(q):
            return
        self._pending = asyncio.ensure_future(
            self.observe_fn(q["question_id"], q["question"], utterance))

    async def _settle(self) -> None:
        """Fold any finished extraction into the triple. Safe to call at any time."""
        task, self._pending = self._pending, None
        if task is None:
            return
        try:
            obs = await task
        except Exception:
            return              # an extraction failure must never end an interview
        gained = {k for k in ("situation", "action", "result") if getattr(obs, k, "")}
        # A `result` that names no change is the scale-and-filler failure of 9.9. Rejecting it
        # here can only cost one more probe; accepting it could end a question with no outcome
        # in it, and 1c.5 asks for the error to fall on the probing side.
        if "result" in gained and not result_check.states_change(obs.result):
            gained.discard("result")
        self.stalls = 0 if gained - self.seen else self.stalls + 1
        self.seen |= gained

    async def settle(self) -> None:
        """For a harness that ends the process between turns; the loop does this itself."""
        await self._settle()

    async def submit(self, utterance: str) -> TurnOutcome:
        """One committed utterance in, one decision out."""
        await self._settle()
        q = self.current
        if q is None:
            return TurnOutcome("end", self._spoken("", finished=True), False, True)

        # A confirmation turn is pending: this utterance answers it, and costs no model call.
        if self.awaiting_confirm:
            self.awaiting_confirm = False
            # A bare affirmative decides nothing against CONFIRM_LINE's three options, and
            # only becomes an answer once the question has been narrowed to a two-way one.
            reply = intent.read_control(
                utterance, bare_yes=intent.STOP if self.confirm_narrowed else None)
            if reply == intent.STOP:
                g = guards.Guarded("end", "Of course. We'll stop there.", False, "",
                                   ["confirmed-stop"])
            elif reply == intent.SKIP_QUESTION:
                # The middle option CONFIRM_LINE offers. It had no branch, so a candidate who
                # took the offer was re-asked the question they had just asked to leave.
                g = guards.Guarded("skip", SKIP_ACK, False, "", ["confirmed-skip"])
            elif reply == intent.UNCLEAR and not self.confirm_narrowed:
                self.confirm_narrowed = True
                self.awaiting_confirm = True
                g = guards.Guarded("clarify", CONFIRM_NARROW, False, "",
                                   ["confirm-unclear->narrow"])
            else:
                g = guards.Guarded("reask", "", False, "", ["confirmed-continue"])
            self.answers_this_question.append(utterance)
            return self._dispatch(g, utterance, Completion(text=""))

        # A skip offer is pending: this utterance answers it, and costs no model call.
        if self.awaiting_skip_offer:
            self.awaiting_skip_offer = False
            reply = intent.read_control(utterance, bare_yes=intent.SKIP_QUESTION)
            if reply == intent.STOP:
                # Offered a skip, asked to stop instead. Without this the request is consumed
                # by the offer and the detector never sees it, so it is dropped for a turn.
                self.awaiting_confirm = True
                self.confirm_narrowed = False
                g = guards.Guarded("clarify", CONFIRM_LINE, False, "",
                                   ["stop-in-skip-reply->confirm"])
            elif reply == intent.SKIP_QUESTION:
                g = guards.Guarded("skip", SKIP_ACK, False, "", ["skip-offer-accepted"])
            else:
                self.clarify_extra = CLARIFY_EXTRA
                g = guards.Guarded("clarify", SKIP_DECLINED, False, "",
                                   ["skip-offer-declined"])
            self.answers_this_question.append(utterance)
            return self._dispatch(g, utterance, Completion(text=""))

        # A user-questions phase is the candidate's turn to ask, so it does not go through
        # the model at all: there is no probe to write and nothing to score. The generic loop
        # used to run it, which captured their questions into `ask` and advanced past them.
        if q.get("type") == "user_questions":
            return self._user_questions_turn(utterance, q)

        # Direction of talk, before focus, extraction and budget -- all three of which
        # treated a candidate's question as evidence for the question it interrupted.
        if self.pace and direction.is_candidate_question(utterance):
            self.questions_asked.append(utterance)
            applied = ["candidate-question->defer"]
            # An answer with a question on the end is both things. Keeping only the question
            # threw away the evidence in front of it, which is the direction this check was
            # supposed to protect (9.16).
            answered = direction.answer_part(utterance)
            if len(answered.split()) >= ANSWER_PART_MIN_WORDS:
                self.answers_this_question.append(answered)
                applied.append("answer-part-kept")
            g = guards.Guarded("clarify", QUESTION_DEFERRED, False, "", applied)
            return self._dispatch(g, utterance, Completion(text=""))

        # Pick what to ASK ABOUT before asking. The model still writes the sentence; it no
        # longer chooses the sentence's purpose, which is where the repertoire ran out
        # (log 8.18).
        want = focus.next_focus(utterance, self.focus_used,
                                (self.current or {}).get("rubric_criteria") or [],
                                (self.current or {}).get("focus_ladder") or [],
                                self.seen)
        t0 = time.perf_counter()
        out, raw = await self._decide(utterance, [], want)
        say_raw = _raw_say(raw)
        g = guards.apply(raw, utterance, self.said_this_question)

        calls = 1
        speech_attempt: dict | None = None

        # Guard 3 asks for one regeneration with the previous lines fed back. One retry
        # only: a second identical answer is the model's position, not a slip.
        #
        # And it IS the model's position more often than not. Measured over 50 firings, 28%
        # tripped the string test again and 64% were still the same request semantically --
        # "say something materially different" is another instruction this model does not
        # take. So the retry's failure is now acted on rather than discarded: the question
        # has had this probe, and the follow-up is charged and converted (log 8.18).
        if calls == 1 and g.needs_regeneration:
            first = g.applied
            out, raw = await self._decide(utterance, self.said_this_question, want)
            say_raw = _raw_say(raw)
            g = guards.apply(raw, utterance, self.said_this_question)
            # The first pass's guard names would otherwise vanish from the record replay
            # depends on (section 8.1).
            g.applied = first + ["regenerated"] + g.applied
            calls = 2
            # Only a REPEAT converts. `needs_regeneration` has two causes and they want
            # opposite handling: an unparseable reply should keep probing with the fallback
            # line (NFR-6 degrades, it does not skip ahead), while a line the model will not
            # vary means this question has had this probe.
            if g.needs_regeneration and "repeated-say->regenerate" in g.applied:
                g.act = "advance"
                g.say = ""
                g.applied.append("regeneration-repeated->advance")

        # 9.52. The one lever that asks the MODEL to fix its line rather than overwriting it.
        # `max_say_words` alone hands an over-length line to the template; this offers one
        # retry first, so a model that can say the same thing shorter keeps its own words.
        #
        # The accept test is strict because spoken text enters `History`, so a nominally
        # speech-only change can alter later decisions. A retry with a DIFFERENT act is
        # refused outright: shortening must not become a route to re-deciding the turn.
        cap = self.max_say_words
        if (cap and calls == 1 and g.act in ("probe", "reask") and g.say
                and len(g.say.split()) > cap):
            out2, raw2 = await self._decide(utterance, [], want, too_long=cap)
            g2 = guards.apply(raw2, utterance, self.said_this_question)
            calls = 2
            if g2.act == g.act and g2.say and len(g2.say.split()) <= cap:
                first = g.applied
                out, g = out2, g2
                say_raw = _raw_say(raw2)
                g.applied = first + ["too-long->shortened"] + g.applied
            else:
                g.applied.append("too-long->retry-failed")

        # Budget backstop. The adaptive rule of section 1c.5 -- stop after two consecutive
        # turns with no new observation -- needs the Stage 2 extractor, so Stage 1 runs the
        # fixed cap alone and the adaptive layer slots in above it.
        # Rec 2's upgrade half. The detector says stop, the model did not: ask, do not guess.
        if g.act != "end" and guards.user_asked_to_stop(utterance):
            self.awaiting_confirm = True
            self.confirm_narrowed = False
            g = guards.Guarded("clarify", CONFIRM_LINE, False, "", ["stop-detected->confirm"])
            self.answers_this_question.append(utterance)
            return self._dispatch(g, utterance, out, say_raw=say_raw)

        # Rec 2's shape, one role later. Guard 2b only ever DOWNGRADES an ungrounded
        # `clarify`; nothing upgraded the reverse case, so a candidate who asked what the
        # question meant got whatever the model had picked instead. Observed live (9.16):
        # "Sorry, do you mean the WordPress site or the booking tool? They're different
        # projects" was answered with a CONTEXT template.
        #
        # `end` and `skip` are excluded because both are grounded in the candidate's own
        # words already, and clarifying over them would ignore what that grounding said.
        # `offers_a_choice` was only ever consulted to pick the REPLY once the turn was
        # already a clarify. As a detector it covers 9 of the 10 gold=clarify fixtures where
        # `asks_what_i_meant` covers 5, and the four it adds are the ones phrased without
        # "do you mean" -- "Quickly meaning what, a few days? A sprint?" (9.42).
        if g.act not in ("clarify", "end", "skip") and (guards.asks_what_i_meant(utterance)
                                                        or guards.offers_a_choice(utterance)):
            # "Did you mean A or B?" and "what does this mean?" want different answers, and
            # `_on_clarify`'s fallback only answers the second. The example is theirs to pick
            # either way, so the honest reply is to say so rather than explain the question.
            g.act = "clarify"
            g.say = ""
            g.applied.append("clarify-detected->clarify")

        # The either/or answer is owed whenever the turn IS a clarify, not only when the
        # harness was the one that routed it there. A captured model-routed clarification
        # otherwise answered "work or open source?" with "tell me more about the context".
        if g.act == "clarify" and guards.offers_a_choice(utterance):
            g.say = CLARIFY_EITHER
            g.applied.append("clarify-either")

        # Clarify past its limit offers an exit rather than repeating the question. The
        # offer costs no model call, exactly like rec 2's confirmation turn.
        if g.act == "clarify" and self.clarifies_used >= CLARIFY_LIMIT + self.clarify_extra:
            if self.skip_offered:
                g = guards.Guarded("skip", SKIP_ACK, False, "",
                                   g.applied + ["clarify-limit->auto-skip"])
            else:
                self.awaiting_skip_offer = True
                self.skip_offered = True
                g = guards.Guarded("clarify", SKIP_OFFER, False, "",
                                   g.applied + ["clarify-limit->skip-offer"])
            self.answers_this_question.append(utterance)
            return self._dispatch(g, utterance, out, say_raw=say_raw)

        # The per-question cap is the primary control and applies to probe and reask alike:
        # Stage 1 charged reask to the allowance without ever checking it against one, so a
        # reask spent a probe's turn for free (log 8.15).
        # Design's displayed cap is a hard pacing contract. Unlike ordinary scored
        # questions, it cannot borrow from the shared reserve: the live control otherwise
        # advertised two follow-ups and asked five.
        hard_cap = q.get("observation_shape") == "design"
        pool_left = 0 if hard_cap else self.pool
        allow = budget.follow_ups_allowed(
            q["probe_budget"], pool_left, self.index, len(self.questions))
        if g.act in ("probe", "reask"):
            if self.pace and self.follow_ups_used >= allow.total:
                g.act = "advance"
                g.say = ""
                g.applied.append("follow-up-cap->advance" if hard_cap or allow.overflow
                                 else "pool-exhausted->advance")

        # Plan 1c.5: the observations, not the budget, decide when a question is done.
        # `probe_budget` is demoted to a backstop and still caps the question above this.
        #
        # Measured before building: 74.7% of advances were forced by the cap and only 11.6%
        # chosen, because `ok` judges one reply against a whole-story standard while history
        # withholds the rest of the story, so completeness can never accumulate (9.9). This
        # accumulates it outside the model.
        if (self.pace and g.act in ("probe", "reask") and self.observe_fn
                and self._star_paced(q)):
            if len(self.seen) == 3:
                g.act, g.say = "advance", ""
                g.applied.append("observations-complete->advance")
            elif self.stalls >= STALL_LIMIT:
                g.act, g.say = "advance", ""
                g.applied.append("no-new-observation->advance")

        # Charge the reserve only after adaptive pacing has decided the follow-up will
        # actually be dispatched. Previously an over-cap model proposal spent a token before
        # `observations-complete` or `no-new-observation` silently converted it to advance.
        if g.act in ("probe", "reask") and self.follow_ups_used >= allow.cap:
            self.pool -= 1
            g.applied.append("pool-draw(%d left)" % self.pool)

        # A design question that is about to advance with a part missing and budget unspent.
        # Deterministic, like the focus rotation: the code decides that a follow-up is owed,
        # the wording is fixed, and no model call is made. Live, the design question drew
        # zero probes out of three because the answer was long and fluent and `ok` reads
        # fluency as completeness (log 9.7).
        #
        # Charged to the question's own cap and never to the pool: this is a question the
        # plan already budgeted for, not an overrun, and drawing on the shared reserve would
        # let one phase quietly spend another's.
        if (self.pace and g.act == "advance" and not self.design_followed_up
                and (q.get("observation_shape") == "design")
                and self.follow_ups_used < allow.cap
                and focus.design_gap(self.answers_this_question + [utterance])):
            self.design_followed_up = True
            g.act = "probe"
            g.say = focus.DESIGN_FOLLOW_UP
            g.applied.append("design-gap->probe")

        # A system-design question is hypothetical. Llama sometimes writes a useful probe
        # with a past-experience premise ("How did you handle...?"), which changes what the
        # candidate is being assessed on. Repair only the finite reviewed grammar here,
        # after action and pacing are final but before focus validation. The raw line, model
        # call count, action and budget remain untouched for auditability.
        if (hard_cap and g.act in ("probe", "reask") and g.say
                and focus.design_past_premise(g.say)):
            repaired = focus.rewrite_design_past_premise(g.say)
            repair_ok = bool(
                repaired
                and repaired.count("?") == 1
                and (not self.max_say_words
                     or len(repaired.split()) <= self.max_say_words)
                and repaired not in self.said_this_session
            )
            if repair_ok:
                g.say = repaired
                g.applied.append("hypothetical-tense->rewrite")
            else:
                g.say = (focus.design_template(want, set(self.said_this_session))
                         if want else focus.DESIGN_REASK)
                g.applied.append("hypothetical-tense->template")

        # Empty model speech is repaired late, after action and pacing gates are final. The
        # second call exposes only `say`, so it cannot change the probe decision. Reask keeps
        # its established behaviour: an empty line repeats the scripted question.
        say_model = None
        if (want and g.act == "probe" and not g.say and not g.needs_regeneration
                and calls == 1):
            say_model = ""
            repaired, speech_attempt, repair_guards = await self._repair_speech(
                utterance, want, "", "empty")
            calls = 2
            if repaired:
                g.say = repaired
                g.applied += ["empty-say->repaired"] + repair_guards
            else:
                g.applied.append("empty-say->repair-failed")

        # A rejected repair gets the reviewed focus line. It remains visibly
        # harness-authored in both the guard list and the structured attempt diagnostic.
        if (want and g.act == "probe" and not g.say
                and "empty-say->repair-failed" in g.applied):
            template_fn = focus.design_template if hard_cap else focus.template
            g.say = template_fn(want, set(self.said_this_session))
            g.applied.append("empty-say->template")

        asked: list[str] = []
        # Validate what came back against what was asked for, and record the focus either
        # way -- a question must not be able to spend two turns on one request type.
        # The deterministic design line needs no validation or substitution, but it still
        # spends CHALLENGE. Leaving it unrecorded let the very next model turn ask what breaks
        # again while the decision log incorrectly claimed that no focus had been delivered.
        if "design-gap->probe" in g.applied:
            self.focus_used.add("CHALLENGE")
            asked = ["CHALLENGE"]
        elif "empty-say->template" in g.applied:
            self.focus_used.add(want)
            asked = [want]
            say_model = ""
        elif want and g.act in ("probe", "reask") and g.say:
            # The objective is a DISTINCT request, not obedience. If the model ignored the
            # requested focus but asked about some other unused one, that is a good turn and
            # its own wording beats a template -- take it and record what it actually asked.
            # Substituting on strict compliance was measured first and put 70% of lines on
            # ten canned sentences, which trades repetition within a question for the same
            # template across questions (log 8.19).
            classified = focus.classify(g.say)
            fresh = classified - self.focus_used
            # A fresh request can still be too long to speak naturally. The live Llama control
            # produced one 22-word compound request; the cap sent it to a focused template.
            over_cap = bool(self.max_say_words
                            and len(g.say.split()) > self.max_say_words)
            if over_cap:
                fresh = set()
            if fresh:
                got = fresh
                self.focus_used |= fresh
            elif (not classified and not over_cap
                  and g.say.count("?") == 1
                  and len(g.say.split()) >= UNNAMED_FOCUS_MIN_WORDS
                  and g.say not in self.said_this_session):
                # An empty `fresh` has TWO causes and the code treated them alike. A line that
                # classifies to a SPENT type is the model repeating a request it has already
                # made, and must not stand. A line that classifies to NOTHING is one the regex
                # cannot NAME, which is a different thing from a bad question: over two live
                # sessions, 16 of the 20 discarded lines were single, in-cap, non-repeating
                # questions, among them "What was the colleague's reaction when you gave him
                # feedback?" and a volume-of-alerts question that IS about scale and simply
                # misses CONTEXT's wording. Their worst similarity to anything already spoken
                # was 0.59 against guard 3's 0.60 limit, so repetition is separately covered.
                #
                # Keep the model's words and charge the REQUESTED focus, so the ladder still
                # advances and the turn cannot silently ask the same kind of thing twice.
                got = {want}
                self.focus_used.add(want)
                g.applied.append("unnamed-focus->kept")
            else:
                say_model = g.say
                repaired = None
                if g.act == "probe" and calls == 1:
                    repaired, speech_attempt, repair_guards = await self._repair_speech(
                        utterance, want, g.say, "off_focus")
                    calls = 2
                    if repaired:
                        g.say = repaired
                        g.applied += ["off-focus->repaired"] + repair_guards
                    else:
                        g.applied.append("off-focus->repair-failed")
                if not repaired:
                    template_fn = focus.design_template if hard_cap else focus.template
                    g.say = template_fn(want, set(self.said_this_session))
                    g.applied.append("off-focus->%s" % want.lower())
                got = {want}
                self.focus_used.add(want)
            asked = sorted(got)

        # Rotation stops a focus being spent twice; it cannot stop two DIFFERENT focuses being
        # rendered as the same question. Checked here rather than before the pool draw because
        # the charged focus is the one that matters and it is not settled until now: the
        # unnamed-kept path charges the requested focus for a line that classifies to nothing,
        # so classifying the text again would miss exactly the lines this catches.
        if (g.act in ("probe", "reask") and g.say and self.last_probe
                and focus.rewords(self.last_probe[0], self.last_probe[1], g.say, asked,
                                  self.similarity)):
            g.act, g.say, asked = "advance", "", []
            g.applied.append("redundant-probe->advance")
        elif g.act in ("probe", "reask") and g.say and asked:
            self.last_probe = (g.say, tuple(asked))

        self.answers_this_question.append(utterance)
        outcome = self._dispatch(g, utterance, out,
                                 wall_ms=(time.perf_counter() - t0) * 1000, calls=calls,
                                 want=want, asked=asked, say_model=say_model,
                                 say_raw=say_raw, speech_attempt=speech_attempt)
        if not outcome.closed_question:
            self._observe_later(utterance)
        return outcome

    # ---------------------------------------------------------------- dispatch
    def _dispatch(self, g: guards.Guarded, utterance: str, out: Completion,
                  wall_ms: float | None = None, calls: int = 1,
                  want: str | None = None,
                  asked: list[str] | None = None,
                  say_model: str | None = None,
                  say_raw: str | None = None,
                  speech_attempt: dict | None = None) -> TurnOutcome:
        q = self.current
        # Captured before any handler runs: `_close_question` moves the index, and the line
        # this returns belongs to the question being closed, not to the one after it.
        event_index = self.index
        handler: Callable[[guards.Guarded], tuple[str, bool, bool]] = {
            "advance": self._on_advance,
            "probe": self._on_probe,
            "reask": self._on_reask,
            "clarify": self._on_clarify,
            "skip": self._on_skip,
            "end": self._on_end,
        }[g.act]
        text, closed, ended = handler(g)

        self.state.turns.append(session.Turn(
            index=len(self.state.turns), phase=q["phase"], question_id=q["question_id"],
            question=q["question"], utterance=utterance, act=g.act, say=text,
            ok=g.ok, ask=g.ask, guards=g.applied))

        session.append_decision(self.state, {
            "turn": len(self.state.turns) - 1,
            "question_id": q["question_id"],
            "utterance": utterance,
            "act": g.act, "say": text, "ok": g.ok, "ask": g.ask,
            "guards": g.applied,
            "close_reason": close_reason(g.act, g.applied) if closed else None,
            "focus_asked": want,
            "focus_got": asked or [],
            # The model's own line where a guard replaced it. Without this the record cannot
            # say what the model WANTED to ask, so a substitution rate would have no
            # diagnosis attached.
            "say_model": say_model,
            # Exact speech field from the model decision that fed the final guard pass.
            # Unlike `say_model`, this is present even when a non-focus guard rewrites or
            # drops the line. Deterministic turns make no model call and record null.
            "say_raw": say_raw,
            # A bounded second call that was allowed to supply speech only. Rejected output
            # and its precise reason remain available instead of disappearing behind the
            # focused template used as the final fallback.
            "speech_attempt": speech_attempt,
            "follow_ups_used": self.follow_ups_used,
            "pool_left": self.pool,
            # Logged every turn, never branched on. The threshold gets set from real data
            # once enough turns exist; criterion fixed in advance at >=60% of errors caught
            # while firing on <20% of turns (log 7.3).
            "posterior": out.posterior,
            "prompt_tokens": out.prompt_tokens,
            "decode_tokens": out.decode_tokens,
            # Both calls, when there were two: a regenerated turn spent two decodes and was
            # recorded as one, which biased every latency figure in section 8.17 low.
            "wall_ms": round(out.wall_ms if wall_ms is None else wall_ms, 1),
            "model_calls": calls,
            "prompt": contract.render(q["question"], utterance, self.history.render()),
            "at": session.now(),
        })

        if closed:
            self._close_question(g.act, close_reason(g.act, g.applied))
        if ended:
            self.state.status = "ended_early"
            self.state.ended_at = session.now()
        elif self.done:
            self.state.status = "complete"
            self.state.ended_at = session.now()
        session.checkpoint(self.state)

        return TurnOutcome(g.act,
                           self._spoken(text, finished=ended or self.done,
                                        about=q, at=event_index),
                           closed, ended)

    def _on_advance(self, g): return g.say, True, False
    def _on_skip(self, g):    return g.say or "Understood, let's move on.", True, False
    def _on_end(self, g):     return g.say or "Of course. We'll stop there.", True, True

    def _on_probe(self, g):
        self.follow_ups_used += 1
        say = g.say or "Could you say a bit more about that?"
        self.said_this_question.append(say)
        self.said_this_session.append(say)
        return say, False, False

    def _on_reask(self, g):
        self.follow_ups_used += 1
        # The literal question is re-spoken only if `say` came back empty (section 6.3).
        say = g.say or self.current["question"]
        self.said_this_question.append(say)
        self.said_this_session.append(say)
        return say, False, False

    def _on_clarify(self, g):
        # Does not consume the follow-up budget: they asked what the question means, which
        # is not a failure to answer it. CLARIFY_LIMIT stops that being unbounded.
        #
        # A runner-side offer or confirmation is not a clarification of the question, so it
        # does not count against the limit that produced it.
        # Three runner-side lines ride on `clarify` without being an explanation of the
        # question, so none of them counts against the limit that produced them. The
        # decline in particular: it exists to GRANT another attempt, and counting it spends
        # the very attempt it grants -- measured live, the candidate said "keep going" and
        # was auto-skipped one turn later (log 8.16).
        if not any(x in g.applied for x in ("stop-detected->confirm",
                                            "confirm-unclear->narrow",
                                            "stop-in-skip-reply->confirm",
                                            "candidate-question->defer",
                                            "candidate-question->noted",
                                            "clarify-limit->skip-offer",
                                            "skip-offer-declined")):
            self.clarifies_used += 1
        say = g.say or "It just means a specific example from your own experience."
        self.said_this_question.append(say)
        self.said_this_session.append(say)
        return say, False, False

    # ---------------------------------------------------------------- boundaries
    def _close_question(self, act: str, reason: str = "model_advanced") -> None:
        q = self.current
        self.state.questions.append(session.QuestionState(
            phase=q["phase"], question_id=q["question_id"], question=q["question"],
            probes_used=self.follow_ups_used, answers=list(self.answers_this_question),
            asked_back=list(self.questions_asked), closed_by=act, closed_because=reason))
        self.history.close_question(q["question"], self.answers_this_question)
        self.index += 1
        self.follow_ups_used = 0
        self.clarifies_used = 0
        self.clarify_extra = 0
        self.skip_offered = False
        self.awaiting_skip_offer = False
        self.confirm_narrowed = False
        self.design_followed_up = False
        self.seen = set()
        self.stalls = 0
        self._pending = None
        self.focus_used = set()
        self.questions_asked = []
        self.said_this_question = []
        self.last_probe = None
        self.answers_this_question = []
