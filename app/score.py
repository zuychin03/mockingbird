"""Rubric scoring. Plan section 6, log section 8.23.

Pure Python. No model call, no judgement that is not arithmetic over what `observe.py` found.
That is the whole point of extract-then-score: the model reports what the candidate said, and
the scoring is something you can read, argue with and re-run without a GPU.

Two properties this buys, both of which the plan asks for:

  traceable   NFR-5 -- every criterion names the observation behind it, so a score can be
              disputed by pointing at the quote it rests on rather than at the model
  stable      the same transcript scores the same way every time. Section 8.7 measured
              session-level model output moving run to run; a report that moved with it would
              be worthless as feedback
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .observe import Observation

# A criterion met this often or less is a habit worth naming. Above it, the misses are more
# likely to be questions where it did not apply. One definition, because every report path
# has to name the same criteria as the candidate's weakest.
WEAK = 0.6
STRONG = 0.8

# Which observation satisfies which criterion. Every entry is a fact about text, never an
# opinion -- that is the constraint 7.10 established and every probe design that ignored it
# failed (1c.10).
CRITERIA = {
    "sets_context": ("situation", "said where, what system, or what the constraint was"),
    "describes_action": ("action", "said what was actually done"),
    "states_outcome": ("result", "said how it turned out"),
    "first_person": ("first_person", "spoke about their own part, not only the team's"),
    "specific_detail": ("specific_detail", "gave a concrete figure or quantity"),
    "measurement_stated": ("measurement_stated", "said how they know -- measured, not asserted"),
    # Design questions. Same kind of entry: a fact about text, never an opinion (log 9.6).
    "names_approach": ("approach", "named something concrete they would build"),
    "considers_alternatives": ("alternative", "weighed another approach, not just the first one"),
    "names_tradeoff": ("tradeoff", "named what their choice costs"),
    "anticipates_failure": ("failure_mode", "said what would break, and under what conditions"),
}


@dataclass
class QuestionScore:
    question_id: str
    question: str
    met: dict[str, bool] = field(default_factory=dict)
    # A verbatim quote where one exists. `quoted` says which entries are real quotes: the
    # deterministic criteria have no quote behind them, and printing their placeholder inside
    # quotation marks presents our words as the candidate's (log 9.5).
    evidence: dict[str, str] = field(default_factory=dict)
    quoted: set = field(default_factory=set)
    answer: str = ""
    addresses_question: str = "no"
    unanswered: bool = False

    @property
    def score(self) -> tuple[int, int]:
        return sum(self.met.values()), len(self.met)


def score_question(obs: Observation, criteria: list[str]) -> QuestionScore:
    """Score one question against the criteria its phase declares.

    A phase with no `rubric_criteria` is not scored at all -- warmup and closing exist to open
    and close the conversation, and scoring them would put a number on small talk.
    """
    qs = QuestionScore(question_id=obs.question_id, question=obs.question,
                       answer=obs.text, addresses_question=obs.addresses_question,
                       unanswered=not obs.text.strip())
    for name in criteria:
        source, _ = CRITERIA.get(name, (None, None))
        if source is None:
            continue
        value = getattr(obs, source)
        qs.met[name] = bool(value)
        if isinstance(value, str) and value:
            qs.evidence[name] = value
            qs.quoted.add(name)
        else:
            qs.evidence[name] = "found in the answer" if value else "not found"
    return qs


@dataclass
class Report:
    session_id: str
    scores: list[QuestionScore] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, tuple[int, int]]:
        """Per criterion, across every scored question. The report's headline numbers."""
        out: dict[str, list[int]] = {}
        for qs in self.scores:
            for name, met in qs.met.items():
                got, n = out.setdefault(name, [0, 0])
                out[name] = [got + int(met), n + 1]
        return {k: (v[0], v[1]) for k, v in out.items()}

    @property
    def weakest(self) -> list[str]:
        """Criteria met least often. What the feedback should lead with."""
        t = self.totals
        if not t:
            return []
        ranked = sorted(t, key=lambda k: (t[k][0] / t[k][1]) if t[k][1] else 1.0)
        return [k for k in ranked if t[k][1] and t[k][0] / t[k][1] <= WEAK]


def build(session_id: str, observations: list[Observation],
          criteria_for: dict[str, list[str]]) -> Report:
    """Assemble the report. `criteria_for` maps question_id -> the phase's rubric criteria."""
    r = Report(session_id=session_id)
    for obs in observations:
        criteria = criteria_for.get(obs.question_id) or []
        if criteria:
            r.scores.append(score_question(obs, criteria))
    return r
