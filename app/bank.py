"""The curated question bank, and the closed vocabulary the planner has to speak.

FR-2 draws questions from a bank where one fits and generates only where none does, and FR-6
requires every question to be asked verbatim. Both rest on the bank being reviewed text rather
than model output, so a `generated` question is marked and never silently indistinguishable
from a curated one.

The competency vocabulary is CLOSED and validated here for the reason `session.load_plan`
validates `rubric_criteria`: a planner free to invent a name produces a tag nothing matches,
and the failure is silent -- a competency the JD asked for simply never appears in the plan,
with no error and no warning. `communication` is deliberately absent, because 7.36 removed it
from the rubric as unobservable and it is exactly the word a model reaches for first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# What a question asks the candidate to produce. `star` expects a past situation, action and
# result; `design` is a hypothetical with no outcome to check against and is not scored.
SHAPES = frozenset({"star", "design"})
# WHERE the text came from. Immutable: approving a generated question does not make it
# curated, because FR-2 requires a generated question to stay marked as one for good.
SOURCES = frozenset({"curated", "generated"})
# WHETHER it may be asked. The agent draws only from questions a person wrote or a person
# approved, so generation lands at `proposed` and stays unaskable until someone says so.
STATUSES = frozenset({"approved", "proposed"})


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    competencies: tuple[str, ...]
    shape: str
    source: str
    status: str

    @property
    def generated(self) -> bool:
        return self.source == "generated"

    @property
    def askable(self) -> bool:
        """The whole guarantee, in one place. FR-6 asks every scripted question verbatim,
        which is only worth anything while a person has read it."""
        return self.status == "approved"


@dataclass(frozen=True)
class Bank:
    competencies: dict[str, str]
    questions: tuple[Question, ...]
    # Which phase of a plan each competency belongs in. Data rather than logic: the mapping is
    # a judgement someone should be able to read and disagree with, and putting a competency
    # in the design phase decides it will be DESCRIBED rather than graded (9.6).
    phase_affinity: dict[str, str] = field(default_factory=dict)

    def phase_for(self, competency: str) -> str:
        return self.phase_affinity[competency]

    def for_competency(self, name: str, *, askable_only: bool = True) -> tuple[Question, ...]:
        """Askable by default: a caller that wants proposals has to say so, so the unsafe
        reading is never the one you get by accident."""
        if name not in self.competencies:
            raise KeyError("unknown competency %r; known: %s"
                           % (name, ", ".join(sorted(self.competencies))))
        return tuple(q for q in self.questions
                     if name in q.competencies and (q.askable or not askable_only))

    def by_shape(self, shape: str, *, askable_only: bool = True) -> tuple[Question, ...]:
        return tuple(q for q in self.questions
                     if q.shape == shape and (q.askable or not askable_only))

    @property
    def proposed(self) -> tuple[Question, ...]:
        return tuple(q for q in self.questions if not q.askable)


def load(path: str | Path) -> Bank:
    """Read and validate the bank. Every check here is one a generated plan would otherwise
    fail at interview time, when a candidate is already sitting in front of it."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    competencies = raw.get("competencies") or {}
    if not competencies:
        raise ValueError("the bank declares no competencies")

    seen: set[str] = set()
    questions: list[Question] = []
    for item in raw.get("questions", []):
        qid = item.get("id")
        if not qid:
            raise ValueError("a bank question has no id")
        if qid in seen:
            raise ValueError("duplicate bank question id %r" % qid)
        seen.add(qid)

        text = (item.get("text") or "").strip()
        if not text:
            raise ValueError("bank question %r has no text" % qid)

        tags = tuple(item.get("competencies") or ())
        if not tags:
            raise ValueError("bank question %r is tagged with no competency, so no planner "
                             "will ever select it" % qid)
        unknown = [t for t in tags if t not in competencies]
        if unknown:
            raise ValueError("bank question %r declares unknown competencies %s; known: %s"
                             % (qid, ", ".join(unknown), ", ".join(sorted(competencies))))

        shape = item.get("shape")
        if shape not in SHAPES:
            raise ValueError("bank question %r declares shape %r; known: %s"
                             % (qid, shape, ", ".join(sorted(SHAPES))))

        source = item.get("source")
        if source not in SOURCES:
            raise ValueError("bank question %r declares source %r; known: %s"
                             % (qid, source, ", ".join(sorted(SOURCES))))

        # Required, never defaulted -- the `answer_shape` lesson. A missing status defaulting
        # to approved would make an unreviewed question askable by omission, which is the one
        # way this guarantee can fail quietly.
        status = item.get("status")
        if status not in STATUSES:
            raise ValueError("bank question %r declares status %r; known: %s"
                             % (qid, status, ", ".join(sorted(STATUSES))))

        questions.append(Question(id=qid, text=text, competencies=tags,
                                  shape=shape, source=source, status=status))

    if not questions:
        raise ValueError("the bank holds no questions")

    # A competency nothing covers is not an error in the file, it is a hole in the interview
    # the planner cannot fill from reviewed text. Naming it here is the only place the gap is
    # visible before a session runs.
    uncovered = sorted(set(competencies)
                       - {t for q in questions if q.askable for t in q.competencies})
    if uncovered:
        raise ValueError("no question covers %s -- either add one or drop the competency"
                         % ", ".join(uncovered))

    affinity = raw.get("phase_affinity") or {}
    missing = sorted(set(competencies) - set(affinity))
    if missing:
        raise ValueError("no phase_affinity for %s -- assembly would silently drop them"
                         % ", ".join(missing))
    stray = sorted(set(affinity) - set(competencies))
    if stray:
        raise ValueError("phase_affinity names competencies that do not exist: %s"
                         % ", ".join(stray))
    # A competency needs at least one ASKABLE question of the shape its phase can hold, or
    # assembly reports it covered and then has nothing to put in the plan. The check is on
    # availability, not on every tag: a question may probe two competencies that live in
    # different phases -- "move a nightly batch job to run continuously" is both system_design
    # and data_modelling -- and its SHAPE decides where it can sit, not its tags.
    for name, phase in affinity.items():
        want = "design" if phase == "design" else "star"
        usable = [q for q in questions
                  if name in q.competencies and q.shape == want and q.askable]
        if not usable:
            raise ValueError("%r sits in the %s phase, which can only hold %s questions, and "
                             "no askable %s question is tagged with it"
                             % (name, phase, want, want))

    return Bank(competencies=dict(competencies), questions=tuple(questions),
                phase_affinity=dict(affinity))


def with_question(b: Bank, q: Question) -> Bank:
    """A new bank carrying one more question. Frozen dataclasses, so nothing mutates under a
    caller holding the old one."""
    if any(x.id == q.id for x in b.questions):
        raise ValueError("bank already holds a question with id %r" % q.id)
    unknown = [t for t in q.competencies if t not in b.competencies]
    if unknown:
        raise ValueError("question %r declares unknown competencies %s"
                         % (q.id, ", ".join(unknown)))
    return Bank(competencies=dict(b.competencies), questions=b.questions + (q,),
                phase_affinity=dict(b.phase_affinity))


def approve(b: Bank, question_id: str) -> Bank:
    """The one transition that makes a question askable, and it only happens here.

    `source` is deliberately untouched: FR-2 requires a generated question to stay marked as
    generated after approval, so a reader of the bank can always tell where the text came
    from even once a person has signed it off.
    """
    found = [q for q in b.questions if q.id == question_id]
    if not found:
        raise KeyError("no bank question with id %r" % question_id)
    q = found[0]
    if q.askable:
        raise ValueError("question %r is already approved" % question_id)
    swapped = Question(id=q.id, text=q.text, competencies=q.competencies, shape=q.shape,
                       source=q.source, status="approved")
    return Bank(competencies=dict(b.competencies),
                questions=tuple(swapped if x.id == question_id else x for x in b.questions),
                phase_affinity=dict(b.phase_affinity))


def save(b: Bank, path: str | Path) -> None:
    """Write the bank back. Round-trips through `load`, so anything `load` would refuse is
    refused here rather than written and discovered on the next run."""
    payload = {
        "version": 1,
        "competencies": dict(b.competencies),
        "phase_affinity": dict(b.phase_affinity),
        "questions": [{"id": q.id, "text": q.text, "competencies": list(q.competencies),
                       "shape": q.shape, "source": q.source, "status": q.status}
                      for q in b.questions],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    load(tmp)
    tmp.replace(path)
