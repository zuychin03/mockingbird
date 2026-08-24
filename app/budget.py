"""Follow-up budgeting. Log sections 8.2, 8.13, 8.15, 8.16.

A turn is either a question's first answer or a follow-up, and the identity is exact:

    turns = questions + probes + reasks + clarifies

Stage 1 rationed `probe` against a session-wide turn budget and left the other two consumers
alone, so `reask` spent the same allowance without ever being asked to justify itself. In one
measured session reask and clarify took 12 of the 21 available follow-up turns -- more than
probe did -- which is why no question in either long session ever received a second probe
(8.15). The cap looked tight because something else had already spent the money.

The shape here is Duy's, and it inverts what came before. The per-question budget is the
primary control and it is a real allowance, not a ceiling that pacing erodes; a question that
wants more than its budget draws from a session pool, and only then. So:

  - a fluent candidate never reaches their cap and never touches the pool. Measured: session A
    overflowed its phase budgets by ZERO turns, so no adaptive rule is needed to "give good
    candidates a smaller allowance" -- demand-driven does it for free (8.16).
  - a hesitant candidate draws on the pool, at ~1 turn per question measured, and the pool is
    what stops that becoming unbounded.

There is no session turn budget any more. Session length is a CONSEQUENCE of the caps rather
than a configured constant, which is what makes the plan portable to another role or a custom
question set: everything scales from `len(questions)`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Pool turns per question, so a plan of any size gets a proportionate reserve without being
# re-tuned. Linear is right because the NUMBER of questions that exceed their cap grows with
# the question count -- it is a per-question property, not a fluctuation around a fixed mean.
# 1.0 covers the worst case measured (log 8.16: the hesitant session wanted 1.00/question);
# the fluent session wanted 0.00, and that gap is the whole argument for a shared pool.
POOL_PER_QUESTION = 1.0


@dataclass(frozen=True)
class Allowance:
    """What one question may spend on follow-ups, and where each part comes from."""

    cap: int              # from the question's own phase budget, never rationed
    overflow: int         # this question's fair share of what remains in the pool
    pool_left: int
    questions_left: int

    @property
    def total(self) -> int:
        return self.cap + self.overflow

    @property
    def reason(self) -> str:
        if not self.overflow:
            return "cap-only(%d)" % self.cap
        return "cap(%d)+pool(%d of %d)" % (self.cap, self.overflow, self.pool_left)


def session_pool(question_count: int, per_question: float = POOL_PER_QUESTION) -> int:
    """The whole session's overflow reserve. Derived at runtime from the actual plan."""
    return max(0, round(question_count * per_question))


def follow_ups_allowed(phase_budget: int, pool_left: int,
                       questions_done: int, question_total: int) -> Allowance:
    """How many follow-ups -- probe and reask together -- this question may still use.

    The overflow share is integer division and rounds DOWN, for the reason 8.13 records: a
    fractional allowance reads as generous and compares as more generous still, and the two
    failures are not symmetric. One follow-up too few costs a shallower answer; one too many
    is taken from a question that has not been asked yet.

    `phase_budget` is the floor of what a question gets, not the ceiling -- EXCEPT at zero,
    which is hard. See the note below.
    """
    questions_left = max(1, question_total - questions_done)
    pool_left = max(0, pool_left)
    # A declared 0 is now HARD. This module used to let `closing` draw overflow on the
    # reasoning that "do not routinely probe" is not "never speak twice" -- and in both live
    # sessions that produced the same failure: the candidate asks their question, the agent
    # spends a pool turn asking it back at them (log 8.20). Section 8.13 warned against a
    # rule that reopens a phase the config had closed; this is that warning, honoured.
    if phase_budget <= 0:
        return Allowance(0, 0, pool_left, questions_left)
    return Allowance(cap=phase_budget,
                     overflow=pool_left // questions_left,
                     pool_left=pool_left,
                     questions_left=questions_left)
