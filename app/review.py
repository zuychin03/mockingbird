"""FR-3: the plan is reviewed before anyone is interviewed with it.

Every operation here returns a NEW draft and revalidates the plan, so a review session cannot
walk a plan into a state the runner would refuse -- the failure would otherwise land at the
start of an interview, which is the worst moment to discover it.

The invariant the whole of Stage 3 rests on lives here too: every question in a plan is text a
person wrote or a person approved. There are exactly three ways a question gets in --

    the bank, which is curated text
    a proposal a person approved
    a person typing it here

-- and `add` treats the third as curated for the honest reason that someone did write it.
Editing is the same act: an edited question is the reviewer's words now, not the model's, and
`edited_from` keeps what it was so the change is visible rather than silent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import bank as bank_mod
from . import session as sess
from .bank import Bank, Question
from .planner import Assembled, JobSpec

# Phases whose questions a reviewer may touch. Warmup and closing carry the AI disclosure and
# the sign-off; editing those is a different decision from planning an interview.
EDITABLE = ("behavioural_core", "technical_experience", "design", "collaboration")


@dataclass(frozen=True)
class Draft:
    plan: dict
    bank: Bank
    spec: JobSpec | None = None
    gaps: tuple[str, ...] = ()
    # Text that was changed in review, as {new: old}. Kept so a reviewer can see what they
    # altered, and so a saved plan carries the provenance rather than looking hand-written.
    edited_from: dict[str, str] = field(default_factory=dict)

    def questions(self, phase_id: str) -> tuple[str, ...]:
        return tuple(self._phase(phase_id).get("questions", []))

    def _phase(self, phase_id: str) -> dict:
        for ph in self.plan["phases"]:
            if ph["id"] == phase_id:
                return ph
        raise KeyError("no phase %r in this plan" % phase_id)

    @property
    def proposals(self) -> tuple[Question, ...]:
        return self.bank.proposed

    @property
    def all_questions(self) -> tuple[str, ...]:
        return tuple(q for ph in self.plan["phases"] for q in ph.get("questions", []))


def from_assembled(a: Assembled, bank: Bank, spec: JobSpec | None = None) -> Draft:
    return Draft(plan=json.loads(json.dumps(a.plan)), bank=bank, spec=spec, gaps=a.gaps)


def _editable(phase_id: str) -> None:
    if phase_id not in EDITABLE:
        raise ValueError("%r is structural: it carries the disclosure or the sign-off, and "
                         "changing it is a different decision from planning an interview. "
                         "Editable phases: %s" % (phase_id, ", ".join(EDITABLE)))


def _revalidated(draft: Draft, plan: dict, **changes) -> Draft:
    """Every operation goes through here. A draft that the runner would refuse is refused at
    the moment it is created, not at the start of an interview."""
    tmp = Path(sess.__file__).parent.parent / ".plan-check.tmp.json"
    tmp.write_text(json.dumps(plan), encoding="utf-8")
    try:
        sess.load_plan(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return replace(draft, plan=plan, **changes)


def _copy(draft: Draft) -> dict:
    return json.loads(json.dumps(draft.plan))


def delete(draft: Draft, phase_id: str, index: int) -> Draft:
    _editable(phase_id)
    plan = _copy(draft)
    questions = [ph for ph in plan["phases"] if ph["id"] == phase_id][0]["questions"]
    if not 0 <= index < len(questions):
        raise IndexError("phase %r has %d questions" % (phase_id, len(questions)))
    if len(questions) == 1:
        raise ValueError("%r would be left with no questions, and a scored phase with none "
                         "produces a rubric denominator of zero" % phase_id)
    questions.pop(index)
    return _revalidated(draft, plan)


def move(draft: Draft, phase_id: str, index: int, to: int) -> Draft:
    _editable(phase_id)
    plan = _copy(draft)
    questions = [ph for ph in plan["phases"] if ph["id"] == phase_id][0]["questions"]
    if not 0 <= index < len(questions) or not 0 <= to < len(questions):
        raise IndexError("phase %r has %d questions" % (phase_id, len(questions)))
    questions.insert(to, questions.pop(index))
    return _revalidated(draft, plan)


def edit(draft: Draft, phase_id: str, index: int, text: str) -> Draft:
    """Replace a question with the reviewer's own words. The result is theirs, not the
    model's, which is why no approval is involved."""
    _editable(phase_id)
    new = " ".join((text or "").split())
    if not new:
        raise ValueError("a question cannot be empty")
    if not new.endswith("?") and not new.endswith("."):
        raise ValueError("a question should end with ? or . -- got %r" % new[-12:])
    plan = _copy(draft)
    questions = [ph for ph in plan["phases"] if ph["id"] == phase_id][0]["questions"]
    if not 0 <= index < len(questions):
        raise IndexError("phase %r has %d questions" % (phase_id, len(questions)))
    if new.lower() in {q.lower() for q in draft.all_questions}:
        raise ValueError("this plan already asks that")
    old, questions[index] = questions[index], new
    edited = dict(draft.edited_from)
    edited[new] = edited.pop(old, old)
    return _revalidated(draft, plan, edited_from=edited)


def add(draft: Draft, phase_id: str, text: str) -> Draft:
    """Add a question the reviewer wrote. Curated by definition: a person typed it."""
    _editable(phase_id)
    new = " ".join((text or "").split())
    if not new:
        raise ValueError("a question cannot be empty")
    if new.lower() in {q.lower() for q in draft.all_questions}:
        raise ValueError("this plan already asks that")
    plan = _copy(draft)
    [ph for ph in plan["phases"] if ph["id"] == phase_id][0]["questions"].append(new)
    return _revalidated(draft, plan)


def add_from_bank(draft: Draft, phase_id: str, question_id: str) -> Draft:
    """Put an existing bank question into the plan. Refused unless it is askable, which is the
    same gate `assemble` applies -- a reviewer should not be able to reach past it by hand."""
    _editable(phase_id)
    found = [q for q in draft.bank.questions if q.id == question_id]
    if not found:
        raise KeyError("no bank question %r" % question_id)
    q = found[0]
    if not q.askable:
        raise ValueError("%r is a proposal. Approve it first: a plan may only hold text a "
                         "person wrote or a person approved." % question_id)
    return add(draft, phase_id, q.text)


def approve(draft: Draft, question_id: str) -> Draft:
    """Approve a proposal. It becomes selectable; putting it in THIS plan is a separate act,
    so approving never silently changes the interview in front of you."""
    return replace(draft, bank=bank_mod.approve(draft.bank, question_id))


def propose_into_bank(draft: Draft, question: Question) -> Draft:
    return replace(draft, bank=bank_mod.with_question(draft.bank, question))


def save(draft: Draft, plan_path: str | Path, bank_path: str | Path | None = None) -> None:
    """Write the reviewed plan, and the bank if approvals happened. Both round-trip through
    their validators first, so an unusable file is never written."""
    plan = _copy(draft)
    if draft.edited_from:
        plan["notes"] = (plan.get("notes", "") + " Reviewed by hand: %d question(s) edited."
                         % len(draft.edited_from)).strip()
    text = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    tmp = Path(plan_path).with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    sess.load_plan(tmp)
    tmp.replace(plan_path)
    if bank_path is not None:
        bank_mod.save(draft.bank, bank_path)


# A draft outlives the process that made it: the terminal tool runs one command per process,
# and the web surface holds none of it in memory between requests. Both read and write THIS,
# rather than each carrying its own copy of the shape -- two serialisations of one structure
# drift, and the one that drifts is whichever is exercised less.
def to_json(draft: Draft) -> dict:
    return {
        "plan": draft.plan,
        "gaps": list(draft.gaps),
        "edited_from": draft.edited_from,
        "spec": None if draft.spec is None else {
            "role": draft.spec.role, "seniority": draft.spec.seniority,
            "requirements": [[r.name, r.evidence] for r in draft.spec.requirements],
            "dropped": [[r.name, r.evidence] for r in draft.spec.dropped]},
        # Every question this draft added, whatever its status. Approving one takes it out of
        # `bank.proposed`, and it is not in config/ either, so persisting only the proposals
        # lost an approval the moment it happened. They stay here rather than in the shipped
        # bank because that file is read by every future plan, and an approval belongs to this
        # review until someone saves it.
        "draft_questions": [{"id": q.id, "text": q.text,
                             "competencies": list(q.competencies), "shape": q.shape,
                             "source": q.source, "status": q.status}
                            for q in draft.bank.questions if q.generated],
    }


def from_json(raw: dict, bank: Bank) -> Draft:
    from .planner import JobSpec, Requirement

    b = bank
    for item in raw.get("draft_questions", []):
        if any(q.id == item["id"] for q in b.questions):
            continue
        b = bank_mod.with_question(b, Question(
            id=item["id"], text=item["text"], competencies=tuple(item["competencies"]),
            shape=item["shape"], source=item["source"], status=item["status"]))
    spec = None
    if raw.get("spec"):
        s = raw["spec"]
        spec = JobSpec(role=s["role"], seniority=s["seniority"],
                       requirements=tuple(Requirement(n, e) for n, e in s["requirements"]),
                       dropped=tuple(Requirement(n, e) for n, e in s["dropped"]))
    return Draft(plan=raw["plan"], bank=b, spec=spec,
                 gaps=tuple(raw.get("gaps", [])),
                 edited_from=raw.get("edited_from", {}))


def write_draft(draft: Draft, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(to_json(draft), indent=1), encoding="utf-8", newline="\n")


def read_draft(path: str | Path, bank: Bank) -> Draft:
    return from_json(json.loads(Path(path).read_text(encoding="utf-8")), bank)
