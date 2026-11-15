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

Format 2 (V1.2_PLAN D8) gives every competency and question a field, `shared` or one of
`fields.IDS`, and the planner only ever sees `Bank.view(field)`. The shipped file is read-only
to the app (D12): generated questions live in `data/bank_local.json`, merged at load.
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from . import fields

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = ROOT / "config" / "question_bank.json"
LOCAL = ROOT / "data" / "bank_local.json"
# The installer's copy of a 1.1 install's bank, taken before the upgrade replaces it (D12).
LEGACY = ROOT / "data" / "bank_1.1.json"
SWE_TEMPLATE = ROOT / "config" / "interview_swe_general.json"

FORMAT = 2
SHARED = "shared"
OWNERS = frozenset(fields.IDS) | {SHARED}
# What a question asks the candidate to produce. `star` expects a past situation, action and
# result; `design` is a hypothetical with no outcome to check against and is not scored.
SHAPES = frozenset({"star", "design"})
# WHERE the text came from. Immutable: approving a generated question does not make it
# curated, because FR-2 requires a generated question to stay marked as one for good.
SOURCES = frozenset({"curated", "generated"})
# WHETHER it may be asked. The agent draws only from questions a person wrote or a person
# approved, so generation lands at `proposed` and stays unaskable until someone says so.
STATUSES = frozenset({"approved", "proposed"})
# Least to most senior. The planner reads one of these from a description.
LEVELS = ("junior", "mid", "senior", "staff")
# O*NET generalized work activity element ids, e.g. 4.A.2.a.4.
_ONET_ID = re.compile(r"^4\.A\.\d\.[a-z]\.\d+$")
# Template phases a plan's questions are selected into (`planner.SELECTABLE`).
_SELECTABLE_TYPES = ("adaptive_discussion", "long_turn")


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    competencies: tuple[str, ...]
    shape: str
    source: str
    status: str
    # The least senior candidate this is fair to ask. A question that can only be answered
    # from a team, a live system or colleagues to review presumes experience a junior may
    # not have had, and asking it anyway measures their CV rather than how they answer.
    # Defaulted, unlike `status`: an omitted level reproduces the behaviour before levels
    # existed, so omission cannot make a plan worse than it was.
    min_level: str = "junior"
    # Required in a format 2 file; the default is what a version 1 file and the pre-1.2
    # constructors mean.
    field: str = fields.SOFTWARE
    # The description's words a kept generated slot was written from (D17).
    duty: str = ""

    @property
    def generated(self) -> bool:
        return self.source == "generated"

    def fits(self, level: str) -> bool:
        return LEVELS.index(self.min_level) <= LEVELS.index(level)

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
    phase_affinity: dict[str, str] = dataclasses.field(default_factory=dict)
    # The file's own explanation of its rules. Carried because `save` used to write the bank
    # back without it, so approving one proposal erased the documentation of every rule the
    # file encodes -- including why `min_level` exists and what earns a question "mid".
    notes: str = ""
    competency_fields: dict[str, str] = dataclasses.field(default_factory=dict)
    # Competency -> ((O*NET element id, title), ...): the work activities it observes (D11).
    onet: dict[str, tuple[tuple[str, str], ...]] = dataclasses.field(default_factory=dict)
    # Ids merged from the local file, which `save` must not write into the shipped one.
    local_ids: frozenset[str] = frozenset()
    # Set on a view, so a view is never saved over the whole bank.
    view_of: str | None = None

    def phase_for(self, competency: str) -> str:
        return self.phase_affinity[competency]

    def field_of(self, competency: str) -> str:
        return self.competency_fields.get(competency, fields.SOFTWARE)

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

    def view(self, field_id: str) -> Bank:
        """The field's competencies and questions plus the shared ones (D8)."""
        fields.get(field_id)
        keep = {c for c in self.competencies if self.field_of(c) in (SHARED, field_id)}
        return replace(
            self,
            competencies={c: d for c, d in self.competencies.items() if c in keep},
            questions=tuple(q for q in self.questions if q.field in (SHARED, field_id)),
            phase_affinity={c: p for c, p in self.phase_affinity.items() if c in keep},
            competency_fields={c: f for c, f in self.competency_fields.items() if c in keep},
            onet={c: a for c, a in self.onet.items() if c in keep},
            view_of=field_id)


def plan_shapes(plan: dict) -> dict[str, str]:
    """Each selectable phase of a plan or template and the question shape it holds."""
    return {ph["id"]: "design" if ph.get("observation_shape") == "design" else "star"
            for ph in plan["phases"] if ph.get("type") in _SELECTABLE_TYPES}


def template_shapes(path: str | Path) -> dict[str, str]:
    return plan_shapes(json.loads(Path(path).read_text(encoding="utf-8")))


def _question(item: dict, competencies: dict[str, str], owners: dict[str, str],
              version: int, where: str) -> Question:
    qid = item.get("id")
    if not qid:
        raise ValueError("a %s question has no id" % where)

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

    min_level = item.get("min_level", "junior")
    if min_level not in LEVELS:
        raise ValueError("bank question %r declares min_level %r; known: %s"
                         % (qid, min_level, ", ".join(LEVELS)))

    # Required in format 2 for the reason `status` is: a default would put a question in a
    # field nobody chose for it.
    owner = item.get("field") if version >= 2 else fields.SOFTWARE
    if owner not in OWNERS:
        raise ValueError("bank question %r declares field %r; known: %s"
                         % (qid, owner, ", ".join(sorted(OWNERS))))
    foreign = [t for t in tags if owners[t] not in (SHARED, owner)]
    if foreign:
        raise ValueError("bank question %r is a %s question tagged with %s, which belong to "
                         "another field" % (qid, owner, ", ".join(foreign)))

    return Question(id=qid, text=text, competencies=tags, shape=shape, source=source,
                    status=status, min_level=min_level, field=owner,
                    duty=" ".join((item.get("duty") or "").split()))


def _parse(raw: dict, where: str) -> Bank:
    version = raw.get("version", 1)
    if version not in (1, FORMAT):
        raise ValueError("%s is bank format %r; this version reads 1 and %d"
                         % (where, version, FORMAT))

    competencies = raw.get("competencies") or {}
    if not competencies:
        raise ValueError("the bank declares no competencies")

    if version == 1:
        owners = {c: fields.SOFTWARE for c in competencies}
    else:
        owners = raw.get("competency_fields") or {}
        missing = sorted(set(competencies) - set(owners))
        if missing:
            raise ValueError("no competency_fields entry for %s" % ", ".join(missing))
        stray = sorted(set(owners) - set(competencies))
        if stray:
            raise ValueError("competency_fields names competencies that do not exist: %s"
                             % ", ".join(stray))
        bad = sorted(c for c, f in owners.items() if f not in OWNERS)
        if bad:
            raise ValueError("competency_fields gives %s an unknown field; known: %s"
                             % (", ".join(bad), ", ".join(sorted(OWNERS))))

    onet: dict[str, tuple[tuple[str, str], ...]] = {}
    for name, acts in (raw.get("onet") or {}).items():
        if name not in competencies:
            raise ValueError("onet names a competency that does not exist: %s" % name)
        pairs = tuple((a.get("id", ""), (a.get("title") or "").strip()) for a in acts)
        if not pairs or any(not _ONET_ID.match(i) or not t for i, t in pairs):
            raise ValueError("onet for %r needs O*NET work activities as {id, title}, e.g. "
                             "{\"id\": \"4.A.2.a.4\", \"title\": \"Analyzing Data or "
                             "Information\"}" % name)
        onet[name] = pairs

    seen: set[str] = set()
    questions: list[Question] = []
    for item in raw.get("questions", []):
        q = _question(item, competencies, owners, version, "bank")
        if q.id in seen:
            raise ValueError("duplicate bank question id %r" % q.id)
        seen.add(q.id)
        questions.append(q)

    if not questions:
        raise ValueError("the bank holds no questions")

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

    return Bank(competencies=dict(competencies), questions=tuple(questions),
                phase_affinity=dict(affinity), notes=raw.get("notes") or "",
                competency_fields=dict(owners), onet=onet)


def _merge(b: Bank, raw: dict, where: str) -> Bank:
    """The local file's generated questions on top of the shipped bank."""
    extra: list[Question] = []
    ids = {q.id for q in b.questions}
    for item in raw.get("questions", []):
        q = _question(item, b.competencies, b.competency_fields, FORMAT, where)
        # The local file holds only what the app's model wrote. Curated text there would be
        # unreviewed text marked as reviewed.
        if not q.generated:
            raise ValueError("%s holds %r marked %s; only generated questions live there"
                             % (where, q.id, q.source))
        if q.id in ids:
            raise ValueError("%s repeats question id %r" % (where, q.id))
        ids.add(q.id)
        extra.append(q)
    return replace(b, questions=b.questions + tuple(extra),
                   local_ids=frozenset(q.id for q in extra))


def _check_view(v: Bank, shapes: dict[str, str]) -> None:
    field_id = v.view_of
    # A competency nothing covers is not an error in the file, it is a hole in the interview
    # the planner cannot fill from reviewed text. Naming it here is the only place the gap is
    # visible before a session runs.
    uncovered = sorted(set(v.competencies)
                       - {t for q in v.questions if q.askable for t in q.competencies})
    if uncovered:
        raise ValueError("no question covers %s in the %s view -- either add one or drop the "
                         "competency" % (", ".join(uncovered), field_id))
    # A competency needs at least one ASKABLE question of the shape its phase can hold, or
    # assembly reports it covered and then has nothing to put in the plan. The check is on
    # availability, not on every tag: a question may probe two competencies that live in
    # different phases -- "move a nightly batch job to run continuously" is both system_design
    # and data_modelling -- and its SHAPE decides where it can sit, not its tags.
    for name, phase in v.phase_affinity.items():
        if phase not in shapes:
            raise ValueError("%r sits in the %s phase, which the %s template does not have"
                             % (name, phase, field_id))
        want = shapes[phase]
        usable = [q for q in v.questions
                  if name in q.competencies and q.shape == want and q.askable]
        if not usable:
            raise ValueError("%r sits in the %s phase, which can only hold %s questions, and "
                             "no askable %s question is tagged with it in the %s view"
                             % (name, phase, want, want, field_id))


def _validate(b: Bank, templates: dict[str, Path] | None) -> None:
    if templates is None:
        templates = {fields.SOFTWARE: SWE_TEMPLATE}
    for field_id, template in templates.items():
        _check_view(b.view(field_id), template_shapes(template))


def load(path: str | Path, *, local: str | Path | None = None,
         templates: dict[str, Path] | None = None) -> Bank:
    """Read and validate the bank. Every check here is one a generated plan would otherwise
    fail at interview time, when a candidate is already sitting in front of it.

    Every field in `templates` has its view validated against that template, so a field
    missing a question fails here rather than mid-interview.
    """
    b = _parse(json.loads(Path(path).read_text(encoding="utf-8")), str(path))
    if local is not None and Path(local).exists():
        b = _merge(b, json.loads(Path(local).read_text(encoding="utf-8")), str(local))
    _validate(b, templates)
    return b


def with_question(b: Bank, q: Question) -> Bank:
    """A new bank carrying one more question. Frozen dataclasses, so nothing mutates under a
    caller holding the old one."""
    if any(x.id == q.id for x in b.questions):
        raise ValueError("bank already holds a question with id %r" % q.id)
    unknown = [t for t in q.competencies if t not in b.competencies]
    if unknown:
        raise ValueError("question %r declares unknown competencies %s"
                         % (q.id, ", ".join(unknown)))
    foreign = [t for t in q.competencies if b.field_of(t) not in (SHARED, q.field)]
    if foreign:
        raise ValueError("question %r is a %s question tagged with %s, which belong to "
                         "another field" % (q.id, q.field, ", ".join(foreign)))
    # `replace` for the same reason as `approve`: a field-by-field rebuild drops whatever was
    # added after it was written, and `notes` was dropped exactly that way.
    return replace(b, competencies=dict(b.competencies), questions=b.questions + (q,),
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
    # `replace`, not a field-by-field rebuild, which dropped any field added after it was
    # written -- `min_level` would have reverted to junior on approval.
    swapped = replace(q, status="approved")
    return replace(b, competencies=dict(b.competencies),
                   questions=tuple(swapped if x.id == question_id else x for x in b.questions),
                   phase_affinity=dict(b.phase_affinity))


def _row(q: Question) -> dict:
    """One question as the file holds it. The level is written only where it narrows the
    default, so a save does not add a line to every question that never had one -- and it IS
    written, because `load` treats a missing level as junior and would have untagged the whole
    bank on the first approval without any error."""
    row = {"id": q.id, "text": q.text, "field": q.field, "competencies": list(q.competencies),
           "shape": q.shape, "source": q.source, "status": q.status}
    if q.min_level != "junior":
        row["min_level"] = q.min_level
    if q.duty:
        row["duty"] = q.duty
    return row


def _write(payload: dict, path: Path) -> Path:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    return tmp


def save(b: Bank, path: str | Path) -> None:
    """Write the bank back. Round-trips through `load`, so anything `load` would refuse is
    refused here rather than written and discovered on the next run."""
    if b.view_of is not None:
        raise ValueError("this is the %s view; saving it would drop every other field's "
                         "questions" % b.view_of)
    payload = {
        "version": FORMAT,
        **({"notes": b.notes} if b.notes else {}),
        "competencies": dict(b.competencies),
        "competency_fields": {c: b.field_of(c) for c in b.competencies},
        **({"onet": {c: [{"id": i, "title": t} for i, t in acts]
                     for c, acts in b.onet.items()}} if b.onet else {}),
        "phase_affinity": dict(b.phase_affinity),
        "questions": [_row(q) for q in b.questions if q.id not in b.local_ids],
    }
    tmp = _write(payload, Path(path))
    load(tmp)
    tmp.replace(path)


def _read_local(path: Path) -> dict:
    if not path.exists():
        return {"version": FORMAT, "questions": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_local(b: Bank, path: str | Path | None = None) -> None:
    """Write the bank's generated questions to the local file (D12), keeping the rows a view
    does not hold, so saving one field's review never drops another's."""
    p = Path(path or LOCAL)
    data = _read_local(p)
    mine = {q.id: _row(q) for q in b.questions if q.generated}
    kept = [r for r in data.get("questions", []) if r.get("id") not in mine]
    data["version"] = FORMAT
    data["questions"] = kept + list(mine.values())
    p.parent.mkdir(parents=True, exist_ok=True)
    _write(data, p).replace(p)


def import_legacy(shipped: Bank, legacy: str | Path | None = None,
                  local: str | Path | None = None) -> list[str]:
    """Bring a 1.1 install's generated questions into the local file, once.

    Read row by row rather than through `load`: one row this version cannot read must not
    stop the app from starting, and the record names what was skipped.
    """
    src, dst = Path(legacy or LEGACY), Path(local or LOCAL)
    data = _read_local(dst)
    if "imported_1_1" in data or not src.exists():
        return []
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
        rows = raw.get("questions", []) if isinstance(raw, dict) else []
    except (OSError, ValueError):
        rows = []
    have = {q.id for q in shipped.questions} | {r.get("id") for r in data.get("questions", [])}
    said = ({q.text.lower() for q in shipped.questions}
            | {(r.get("text") or "").lower() for r in data.get("questions", [])})
    took, skipped = [], []
    for item in rows:
        if item.get("source") != "generated":
            continue
        try:
            q = _question({**item, "field": fields.SOFTWARE}, shipped.competencies,
                          shipped.competency_fields, FORMAT, "1.1 bank")
        except ValueError:
            skipped.append(item.get("id"))
            continue
        if q.id in have or q.text.lower() in said:
            skipped.append(q.id)
            continue
        took.append(_row(q))
        have.add(q.id)
        said.add(q.text.lower())
    data["version"] = FORMAT
    data["questions"] = data.get("questions", []) + took
    data["imported_1_1"] = {"from": src.name, "imported": [r["id"] for r in took],
                            "skipped": skipped,
                            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    dst.parent.mkdir(parents=True, exist_ok=True)
    _write(data, dst).replace(dst)
    return [r["id"] for r in took]


def installed(shipped: str | Path | None = None, *, field: str | None = None) -> Bank:
    """The bank the app plans from: shipped, plus the user's generated questions, with every
    field's view checked against its template. `field` narrows it to that field's view."""
    shipped = shipped or SHIPPED
    import_legacy(load(shipped))
    b = load(shipped, local=LOCAL, templates=fields.templates())
    return b.view(field) if field else b
