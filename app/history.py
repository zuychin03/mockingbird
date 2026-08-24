"""History for the turn prompt. Plan section 1c.6.

A running summary of COMPLETED questions, refreshed when a question closes and cached
between turns. Measured against six alternatives across two sessions with different
candidate shapes (log 7.28):

  summary              pooled severity 13, zero family crossings on both, 556 tokens
  verbatim             17, and inconsistent -- severity 4 on a fluent candidate, 13 on a
                       hesitant one. A strategy whose quality depends on who is being
                       interviewed is disqualifying for a coach
  none                 28, the worst of the seven
  summary+scoped-turns 25, sixth of seven -- do not re-add scoped verbatim turns

The current question's own exchanges are deliberately NOT included. That combination was
measured and lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SUMMARISER = ("You maintain a running note of an interview for the interviewer's reference. "
              "Four sentences maximum. Say what ground has been covered. "
              "Do not evaluate the candidate.")


@dataclass
class History:
    """Owns the summary and knows when it is stale.

    Refreshed on a question boundary rather than per turn: the content only changes when a
    question completes, so a per-turn refresh would pay for a call that returns the same
    paragraph.
    """
    summary: str = ""
    _completed: list[tuple[str, list[str]]] = field(default_factory=list)
    _dirty: bool = False

    def close_question(self, question: str, answers: list[str]) -> None:
        if answers:
            self._completed.append((question, list(answers)))
            self._dirty = True

    @property
    def stale(self) -> bool:
        return self._dirty

    @property
    def covered(self) -> list[str]:
        return [q for q, _ in self._completed]

    def source_text(self) -> str:
        return "".join("Q: %s\nA: %s\n\n" % (q, " ".join(a)) for q, a in self._completed)

    async def refresh(self, provider) -> None:
        """Regenerate the summary from completed questions. No-op when nothing closed."""
        if not self._dirty or not self._completed:
            return
        out = await provider.complete(SUMMARISER, self.source_text(), max_tokens=250)
        text = (out.text or "").strip()
        if text:
            self.summary = text
            self._dirty = False

    def render(self) -> str:
        return self.summary
