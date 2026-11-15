"""FR-1: a pasted job description becomes a role, a seniority and RANKED competencies.

Same division of labour as the rest of the product. The model reads the JD and names what it
asks for; Python owns the vocabulary, the grounding and the ranking. Two things make that
enforceable rather than aspirational:

The competency enum is built FROM THE BANK at call time, so the model cannot emit a name the
bank has no question for. That is the strongest form of the check `session.load_plan` performs
after the fact -- here the invalid value is unrepresentable rather than rejected.

Every competency has to cite the JD, and the citation is checked with the SAME grounding used
on interview answers (7.33, measured at zero hallucinations). A competency whose evidence is
not in the JD is dropped, because the alternative is an interview shaped by a requirement the
employer never wrote down. This is the phantom-quote failure of 9.9 in a new place, and it is
worse here: a phantom in the report misleads one reader, a phantom in the plan silently
changes every question that follows.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from . import fields
from .bank import LEVELS, Bank, Question, template_shapes
from .detour import _terms
from .observe import _grounded as _grounded_in
from .provider import Provider, ProviderError

# Closed, and ordered from least to most senior so a caller can compare. The bank's own list,
# because a question's `min_level` is compared against whatever is read here and the two must
# not drift. Inventing more would imply a precision the plan does not have.
SENIORITY = LEVELS

# A JD past this is not a JD -- it is a careers page, and the tail is boilerplate about
# benefits and equal opportunity that competes for attention with the requirements.
MAX_JD_CHARS = 12000

SYSTEM = """You are reading a job description to plan a practice interview for it.

Name the role, judge its seniority, and list the competencies the description actually asks
for, most important first.

Rules:
- "role" is the job title as written, or the closest short phrase to it.
- "seniority" is your reading of the level the description is pitched at.
- List a competency ONLY if the description asks for it. A competency you cannot support with
  the description's own words does not belong in the list.
- "evidence" is a span COPIED WORD FOR WORD from the description. Do not paraphrase it, do not
  tidy it, and do not write a span that is not there. Copy at least a full clause.
- Order the list by how much weight the description puts on each one."""


@dataclass(frozen=True)
class Requirement:
    """One competency the JD asks for, and the words that say so."""
    name: str
    evidence: str


@dataclass(frozen=True)
class JobSpec:
    role: str
    seniority: str
    requirements: tuple[Requirement, ...] = ()
    # Kept rather than discarded: a competency the model named and could not support is the
    # most useful thing to show a user reviewing the plan, because it is the difference
    # between "the JD did not ask for this" and "the planner missed it".
    dropped: tuple[Requirement, ...] = field(default_factory=tuple)

    @property
    def competencies(self) -> tuple[str, ...]:
        return tuple(r.name for r in self.requirements)


def schema(bank: Bank) -> dict:
    """The turn contract for FR-1, with the competency enum taken from the bank."""
    return {
        "type": "object",
        "properties": {
            "role": {"type": "string"},
            "seniority": {"type": "string", "enum": list(SENIORITY)},
            "competencies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": sorted(bank.competencies)},
                        "evidence": {"type": "string"},
                    },
                    "required": ["name", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["role", "seniority", "competencies"],
        "additionalProperties": False,
    }


def _jd(text: str) -> str:
    jd = (text or "").strip()
    if len(jd.split()) < 20:
        raise ValueError("this does not look like a job description: %d words. FR-4 runs a "
                         "stock plan without one, which is the path for having no JD."
                         % len(jd.split()))
    return jd[:MAX_JD_CHARS]


# 1.1's software vocabulary. The software view also holds the five competencies 1.2 shares
# across fields; on qwen3.8-27b they changed 5 of 9 software descriptions' reads, 4 of them to
# `influence` first (13/11). Software's read keeps to these ten until P3 measures the view's.
SOFTWARE_1_1 = frozenset({"incident_response", "performance", "data_modelling",
                          "system_design", "testing_quality", "collaboration", "ownership",
                          "learning", "technical_judgement", "mentoring"})


def _vocabulary(bank: Bank) -> Bank:
    if bank.view_of != fields.SOFTWARE:
        return bank
    return replace(bank, competencies={c: d for c, d in bank.competencies.items()
                                       if c in SOFTWARE_1_1})


async def read_jd(provider: Provider, bank: Bank, text: str) -> JobSpec:
    """Extract FR-1's role, seniority and ranked competencies from a pasted description."""
    jd = _jd(text)
    bank = _vocabulary(bank)

    out = await provider.complete(SYSTEM, jd, schema=schema(bank), max_tokens=800)
    raw = out.json() or {}

    role = (raw.get("role") or "").strip()
    seniority = raw.get("seniority")
    if seniority not in SENIORITY:
        raise ValueError("model returned seniority %r, which the schema should have made "
                         "impossible" % (seniority,))

    kept: list[Requirement] = []
    dropped: list[Requirement] = []
    seen: set[str] = set()
    for item in raw.get("competencies") or []:
        name = item.get("name")
        evidence = " ".join((item.get("evidence") or "").split())
        # The schema pins `name`, so an unknown one means the server ignored the enum. Treat
        # it as a dropped requirement rather than trusting it.
        if name not in bank.competencies:
            dropped.append(Requirement(name=str(name), evidence=evidence))
            continue
        # Order is the ranking, so the FIRST mention of a competency is the one to keep.
        if name in seen:
            continue
        if not _grounded_in(evidence, jd):
            dropped.append(Requirement(name=name, evidence=evidence))
            continue
        seen.add(name)
        kept.append(Requirement(name=name, evidence=evidence))

    # A competency another mention grounded is used, so its ungrounded mentions are not "not
    # used" (15/11: data_quality read as asked for and twice as not used). One line per name.
    unused: dict[str, Requirement] = {}
    for r in dropped:
        if r.name not in seen:
            unused.setdefault(r.name, r)
    return JobSpec(role=role, seniority=seniority,
                   requirements=tuple(kept), dropped=tuple(unused.values()))


# Its own call before `read_jd` (V1.2_PLAN D13): `read_jd`'s competency enum depends on the
# field, which one schema cannot choose in the same reply.
FIELD_SYSTEM = """You are reading a job description to choose which kind of practice interview fits it.

Choose the ONE field the job's day-to-day work belongs to:
- software: building, testing or running software. Software, data, platform, reliability and
  front-end engineers, and managers of engineering teams.
- data_analytics: turning data into answers for the business. Data analysts, business
  intelligence analysts, analytics engineers, and data scientists whose work is analysis.
- product_management: deciding what a product should do and why. Product managers and product
  owners, technical ones included.
- ux_design: designing how people use a product. UX, UI, interaction and product designers,
  and UX researchers.
- project_management: delivering projects and programmes on time and on budget. Project,
  programme and delivery managers, technical ones included.
- general: any other kind of work.

Rules:
- Judge by the work the job does, not by the industry or the tools it names.
- "evidence" is a span COPIED WORD FOR WORD from the description that shows what the work is.
  Do not paraphrase it, do not tidy it, and do not write a span that is not there. Copy at
  least a full clause."""

# Evidence before the field, so the reply quotes the work before it names a field for it.
FIELD_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence": {"type": "string"},
        "field": {"type": "string", "enum": list(fields.IDS)},
    },
    "required": ["evidence", "field"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Detection:
    """`field` is None when the reading cannot be trusted; `reason` says why, and `named` is
    what the model chose regardless."""
    field: str | None
    evidence: str
    reason: str = ""
    named: str | None = None


async def detect_field(provider: Provider, text: str) -> Detection:
    """Which field a description is for, with the words that say so. Ungrounded evidence
    gives no field: a plan built on a reading the description does not support is the
    phantom-requirement failure `read_jd` drops."""
    jd = _jd(text)
    out = await provider.complete(FIELD_SYSTEM, jd, schema=FIELD_SCHEMA, max_tokens=300)
    raw = out.json() or {}
    named = raw.get("field")
    evidence = " ".join((raw.get("evidence") or "").split())
    if named not in fields.FIELDS:
        return Detection(None, evidence, "the reply named no known field: %r" % (named,),
                         named=None if named is None else str(named))
    if not _grounded_in(evidence, jd):
        return Detection(None, evidence, "its evidence is not in the description", named=named)
    return Detection(named, evidence, named=named)


# Cosine similarity above which a proposal is judged to be a bank question in different
# words. MEASURED (tools/tier1_duplicate.py): 378 pairs of curated questions as negatives,
# and as positives the model asked to rephrase each bank question -- which is the failure this
# exists to catch, produced by the path that will meet the threshold in production. AUC 0.987.
#
# 0.75 is the highest-recall threshold with ZERO false positives, which is the rule the sweep
# was run under: rejecting a usable proposal is silent and the reviewer never learns it
# existed, while a near-duplicate that gets through is shown to someone already reading every
# proposal. It was a guess before this and the measurement kept it.
#
# What it costs: it catches 12 of 28 real rephrasings. The classes genuinely overlap -- the
# closest pair of DIFFERENT reviewed questions scores 0.726 ("a time you disagreed with a
# technical decision" against "a decision your team made that you disagreed with and went
# along with anyway") and 15 of 28 rephrasings score below that. So this is a cheap filter on
# the obvious cases, NOT a guarantee, and review is what actually catches a near-duplicate.
#
# Deliberately not `embed.SIMILAR`: that is 0.33 and was fitted to whether one PROBE repeats
# the previous probe inside an interview, a different question with a different distribution.
DUPLICATE = 0.75


# The phase configuration is TAKEN FROM the shipped plan, never generated. Every field in it
# is a measured decision -- `probe_budget` 3 -> 2 on the design phase (9.10), the design
# phase's `scored: false` and the paragraph explaining why scoring it inverts the ranking
# (9.6), each phase's focus ladder. A planner that re-derived those would be re-litigating
# settled measurements with a model, so assembly chooses QUESTIONS and nothing else.
TEMPLATE = fields.get(fields.SOFTWARE).template

# Assembly selects into the template's discussion and long-turn phases (`template_shapes`).
# Warmup and closing are structural: identical in every plan, carrying no competency, and their
# wording is the disclosure and the sign-off.


@dataclass(frozen=True)
class Assembled:
    plan: dict
    # What the JD asked for and the plan actually covers, in ranked order.
    covered: tuple[str, ...] = ()
    # Asked for, and NOT in the plan. The single most important thing to show at review: the
    # extractor's recall is imperfect and the bank may not stretch, and a user can only fix
    # what they can see.
    gaps: tuple[str, ...] = ()
    estimated_secs: int = 0
    # Per phase, the questions chosen for one of the description's requirements. A generated
    # question may take any other slot, never one of these (D10).
    picked: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def questions(self) -> tuple[str, ...]:
        return tuple(q for ph in self.plan["phases"] for q in ph.get("questions", []))


def _per_question(phase: dict) -> int:
    """What one question in this phase costs: its prep, one answer at the midpoint of the
    phase's own bounds, and one probe per unit of budget at half an answer."""
    lo, hi = phase.get("min_answer_secs", 0), phase.get("max_answer_secs", 0)
    answer = (lo + hi) // 2
    return phase.get("prep_secs", 0) + answer + phase.get("probe_budget", 0) * (answer // 2)


def _estimate_counts(plan: dict, counts: dict[str, int]) -> int:
    """Length for a hypothetical number of questions per phase. Needed because the capacity
    decision happens BEFORE selection: estimating from the questions present at that moment
    measured the template's supply, not the target, so a phase that would later be topped up
    was costed as though it stayed short and no trimming happened at all."""
    return sum(_per_question(ph) * counts.get(ph["id"], 0) for ph in plan["phases"])


def _estimate(plan: dict) -> int:
    """Rough wall time. A question costs its prep, one answer at the midpoint of the phase's
    own bounds, and one probe per unit of budget at half an answer. Reported as an estimate
    because nothing here is measured -- the recorded sessions are text, and a typed answer is
    not a spoken one."""
    return _estimate_counts(plan, {ph["id"]: len(ph.get("questions", []))
                                   for ph in plan["phases"]})


# How far past the length asked for a plan may run. The estimate is rough (`_estimate`), and held
# to the length exactly, a 30-minute technical plan kept one technical question (15/11).
OVERRUN = 1.05


def _capacity(plan: dict, minutes: int | None,
              shape: dict[str, int] | None = None) -> dict[str, int]:
    """How many questions each phase should hold to land near a target length, never more
    than `OVERRUN` past it.

    Scaled from the template rather than computed from nothing: the template's shape is a
    reviewed judgement about how much of an interview is behavioural against technical, and a
    shorter interview should be the same interview with less of it, not a different one.

    Every phase keeps at least one question. A scored phase with none gives the rubric a
    denominator of zero, and the warmup and closing are the disclosure and the sign-off.
    """
    capacity = {ph["id"]: (shape or {}).get(ph["id"], len(ph.get("questions", [])))
                for ph in plan["phases"]}
    if minutes is None:
        return capacity
    target = minutes * 60
    limit = target * OVERRUN
    # The floor is one question per surviving phase. Below it the request cannot be met, and
    # silently returning a longer interview than was asked for is the kind of quiet degrading
    # this codebase refuses elsewhere -- `answer_shape` is validated rather than defaulted for
    # the same reason.
    shortest = _estimate_counts(plan, {ph["id"]: 1 for ph in plan["phases"]})
    if shortest > limit:
        raise ValueError("%d minutes is shorter than this plan can be: one question per phase "
                         "already runs about %d minutes"
                         % (minutes, round(shortest / 60)))
    full = _estimate_counts(plan, capacity)
    if target >= full:
        return capacity
    scale = target / full
    counts = {pid: max(1, round(n * scale)) for pid, n in capacity.items()}
    if _estimate_counts(plan, counts) <= limit:
        return counts
    # Rounding and the one-question floor never shrink a case phase, which costs about nine
    # minutes at one question, so 30-minute plans ran 35 to 37. Take a question from the phase
    # furthest over its share until the plan fits, then spend the room that freed on the phase
    # furthest under, scored phases first. The trim always ends: `shortest` fits.
    cost = {ph["id"]: _per_question(ph) for ph in plan["phases"]}
    scored = {ph["id"]: bool(ph.get("scored")) for ph in plan["phases"]}
    order = [ph["id"] for ph in plan["phases"]]
    while _estimate_counts(plan, counts) > limit:
        cut = max((p for p in counts if counts[p] > 1),
                  key=lambda p: (counts[p] - capacity[p] * scale, cost[p]))
        counts[cut] -= 1
    while True:
        room = limit - _estimate_counts(plan, counts)
        open_ = [p for p in counts if counts[p] < capacity[p] and cost[p] <= room]
        if not open_:
            return counts
        counts[max(open_, key=lambda p: (capacity[p] * scale - counts[p], scored[p],
                                         -order.index(p)))] += 1


def _select(role: str, seniority: str, ranked: list[Requirement], bank: Bank,
            template: str | Path, minutes: int | None, source_note: str,
            shape: dict[str, int] | None = None, *, field_id: str = fields.SOFTWARE,
            stock: bool = False, recent: dict[str, str] | None = None) -> Assembled:
    """FR-2: a JobSpec and a bank become a plan `session.load_plan` accepts.

    Selection is ranked: the competencies the JD leaned on hardest get their question first,
    and a phase stops when the template says it is full. Only ASKABLE questions are reachable,
    so a proposal cannot enter a plan before someone has approved it.
    """
    plan = json.loads(Path(template).read_text(encoding="utf-8"))
    if shape:
        # Drop a phase before anything else, so it never competes for a question it will not
        # keep and never appears in the length estimate.
        plan["phases"] = [ph for ph in plan["phases"] if shape.get(ph["id"], 0) > 0]
        for ph in plan["phases"]:
            have = ph.get("questions", [])
            want = shape[ph["id"]]
            # The template cannot supply more than it holds; the top-up fills the rest.
            ph["questions"] = have[:want]
    capacity = _capacity(plan, minutes, shape)

    # Seniority used to reach only the label, so a junior plan asked "describe a production
    # incident you were responsible for" and "give difficult feedback to a colleague" -- and
    # neither came from the description: both were the mid-level template filling its slots.
    # Every source below now prefers what fits the level and falls back to what does not only
    # when nothing fairer fills the slot, so coverage and length are unchanged. A level that
    # filters nothing leaves every list exactly as it was.
    by_text = {q.text.lower(): q for q in bank.questions}
    # D20: of equal candidates, the one asked least recently in History. Never asked sorts
    # first, and an empty History leaves the bank's order exactly as it was.
    last = recent or {}

    def fits(text: str) -> bool:
        q = by_text.get(text.lower())
        return q is None or q.fits(seniority)

    def fitted(texts: list[str]) -> list[str]:
        return [t for t in texts if fits(t)] + [t for t in texts if not fits(t)]

    shapes = template_shapes(template)
    chosen: dict[str, list[str]] = {pid: [] for pid in shapes}
    used: set[str] = set()
    # Question TEXT already committed anywhere in the plan. Ids are not enough: the bank was
    # seeded from this template, so the same sentence exists as a bank entry and as a template
    # line, and an interview that asks it twice is worse than one that covers less.
    spoken: set[str] = set()
    covered: list[str] = []
    gaps: list[str] = []

    for req in ranked:
        phase = bank.phase_for(req.name)
        if phase not in chosen:
            gaps.append(req.name)
            continue
        want = shapes[phase]
        options = [q for q in bank.for_competency(req.name)
                   if q.shape == want and q.id not in used
                   and q.text.lower() not in spoken]
        options.sort(key=lambda q: (not q.fits(seniority), last.get(q.text.lower(), "")))
        if not options or len(chosen[phase]) >= capacity.get(phase, 0):
            gaps.append(req.name)
            continue
        pick = options[0]
        used.add(pick.id)
        spoken.add(pick.text.lower())
        chosen[phase].append(pick.text)
        covered.append(req.name)

    # A scored phase with no questions is not an interview, so a phase the JD did not reach is
    # filled from the template rather than left empty. The plan is a practice interview first
    # and a reflection of this JD second.
    for ph in plan["phases"]:
        pid = ph["id"]
        if pid not in chosen:
            continue
        picked = chosen[pid]
        # A phase the JD did not reach keeps the reviewed template as it is -- unless the
        # template holds something this level should not be asked, which is how the junior
        # plan came to ask about colleagues it may never have had, or something already asked
        # elsewhere. The second is real: a JD asking only for collaboration put "disagreed
        # with a technical decision on your team" into the collaboration phase AND kept it as
        # a template line in an unreached behavioural_core -- 249 of 4,089 swept plans asked a
        # question twice. Only the lines that survive the length trim are checked, since those
        # are the only ones that will be asked.
        surviving = ph["questions"][:capacity[pid]]
        if not picked and all(fits(q) and q.lower() not in spoken for q in surviving):
            # Claimed even though nothing was rebuilt. Skipping without recording them let a
            # LATER phase take one of these as a top-up, which is the same bug the other way
            # round.
            spoken.update(q.lower() for q in surviving)
            continue
        # Fill the remaining slots from the template by EXCLUDING what was already selected,
        # not by index. Slicing by count asked the same question twice whenever a selected
        # question also appeared earlier in the template, which is the common case: the bank
        # was seeded from this very plan.
        keep = [q for q in ph["questions"] if q.lower() not in spoken]
        # A phase can still come up short: a question selected for one competency may have
        # moved out of the phase the template had it in, and the template has nothing left to
        # replace it. Top up from the bank rather than shipping a thinner interview, because
        # the shortfall is otherwise silent -- the plan simply has fewer questions than the
        # reviewed one it was built from. The spares are also what replaces a template line
        # that does not fit the level, so they are gathered before the phase is filled.
        want_shape = shapes[pid]
        phase_competencies = [c for c, ph_id in bank.phase_affinity.items() if ph_id == pid]
        taken = {x.lower() for x in picked + keep}
        spare = [q.text for q in bank.questions
                 if q.askable and q.shape == want_shape
                 and any(c in q.competencies for c in phase_competencies)
                 and q.text.lower() not in spoken and q.text.lower() not in taken]
        # Template before bank within each group, so a fitting template line still outranks
        # any spare -- the template is the reviewed shape of the interview.
        ph["questions"] = (picked + fitted(keep + spare))[:capacity[pid]]
        spoken.update(q.lower() for q in ph["questions"])

    # A phase trimmed for length keeps its own questions, so the trim never leaves a phase
    # holding text that was chosen for a longer interview it is no longer part of.
    for ph in plan["phases"]:
        want = capacity.get(ph["id"], len(ph.get("questions", [])))
        ph["questions"] = ph.get("questions", [])[:want]

    # Said only when the level actually filtered something, so a mid-level plan's notes read
    # exactly as they did. A fallback is named rather than left to be noticed: the reviewer
    # sees the questions, but not which of them presume experience the candidate may lack.
    pitched = ""
    if any(q.askable and not q.fits(seniority) for q in bank.questions):
        pitched = (" Pitched at %s: questions that presume more experience are asked only where "
                   "nothing fairer fills the slot." % seniority)
        unfit = [q for ph in plan["phases"] for q in ph.get("questions", []) if not fits(q)]
        if unfit:
            pitched += " Asked anyway, for want of a fairer one: %s" % " / ".join(unfit)

    plan["id"] = "generated.%s" % (role or "role").lower().replace(" ", "_")[:40]
    plan["label"] = "%s (%s)" % (role or "Interview", seniority)
    plan["field"] = field_id
    # A stock plan has no description to cover (Duy 13/11: software's technical plan read
    # "Not covered: technical_judgement").
    plan["notes"] = ("%s Phase configuration is the reviewed template; only the questions were "
                     "selected.%s%s"
                     % (source_note, "" if stock else " Covered: %s. Not covered: %s."
                        % (", ".join(covered) or "nothing", ", ".join(gaps) or "nothing"),
                        pitched))
    picked = {ph["id"]: tuple(q for q in ph["questions"] if q in chosen[ph["id"]])
              for ph in plan["phases"] if ph["id"] in chosen}
    return Assembled(plan=plan, covered=tuple(covered), gaps=tuple(gaps),
                     estimated_secs=_estimate(plan), picked=picked)


def assemble(spec: JobSpec, bank: Bank, *, field: str = fields.SOFTWARE,
             template: str | Path | None = None, minutes: int | None = None,
             recent: dict[str, str] | None = None) -> Assembled:
    """FR-2: a JobSpec and a bank become a plan `session.load_plan` accepts. `bank` is the
    field's view; `recent` maps a question's lowercased text to when History last asked it."""
    return _select(spec.role, spec.seniority, list(spec.requirements), bank,
                   template or fields.get(field).template, minutes,
                   "Generated from a job description.", field_id=field, recent=recent)


# FR-4's stock plans live in `config/fields.json`, per field. Each carries a ranked competency
# list AND a phase shape, because the ranking alone does not produce different interviews:
# every plan keeps the same phases, so a "technical" one still held two behavioural questions
# and a "behavioural" one two technical. Measured on the first version -- behavioural and
# technical shared 7 of 8 questions, which made the choice cosmetic.
#
# A shape's number is how many questions that phase holds; 0 drops the phase entirely rather
# than leaving it empty, because a scored phase with no questions gives the rubric a
# denominator of zero. Dropping the design or case phase is safe in a way dropping a scored
# phase is not: it is observed and described, never scored (9.6).
#
# `mixed` is not the union of the other two. It alternates so that trimming for length takes
# from both halves evenly -- a mixed interview cut to twenty minutes should still be mixed.
#
# Software's, for the callers that do not name a field yet (V1.2_PLAN P3).
STOCK: dict[str, dict] = {k.id: {"ranked": k.ranked, "shape": k.shape}
                          for k in fields.get(fields.SOFTWARE).kinds}


def stock_plan(kind: str, bank: Bank, *, minutes: int | None = None,
               template: str | Path | None = None, field: str = fields.SOFTWARE,
               recent: dict[str, str] | None = None) -> Assembled:
    """FR-4: an interview with no job description behind it.

    The same selection as the JD path, with a fixed ranked list standing in for what a
    description would have asked for. Nothing is invented for it: a stock competency carries
    no evidence, because there is no employer text to cite and a fabricated citation is
    exactly what the JD path drops.
    """
    f = fields.get(field)
    k = f.kind(kind)
    ranked = [Requirement(name=n, evidence="") for n in k.ranked]
    name = k.label if k.label.isupper() else k.label.lower()
    return _select(k.label + " interview", "mid", ranked, bank, template or f.template, minutes,
                   "Stock %s plan, no job description." % name, shape=k.shape,
                   field_id=f.id, stock=True, recent=recent)


# --- the description's duties (V1.2_PLAN D16) ------------------------------------------------

# Its own call: `read_jd` maps requirements onto the vocabulary and is pinned (D5), so it is not
# asked to do a second job. The offer kind is what stops "Learning budget of $1000" becoming a
# question, as it became a learning requirement on 13/11.
DUTIES_SYSTEM = """You are reading a job description to list what the job involves and what the employer offers.

List up to 12 items, in the order the description gives them. Each item is a span COPIED WORD
FOR WORD from the description, and its kind:
- "duty": something the person will do in the job, or must bring to it: a task, a
  responsibility, or experience or a skill the description asks for.
- "offer": something the employer gives or says about itself: pay, benefits, perks, learning
  budgets, flexible hours, culture, the company's pitch, the hiring process.

Rules:
- Copy each span word for word. Do not paraphrase it, tidy it or join two spans.
- One duty per item. Where a sentence lists several duties, copy each as its own item when the
  words allow it.
- Skip headings, the job title and the location."""

DUTY, OFFER = "duty", "offer"
MAX_DUTIES = 12

# Quote before kind, so the reply copies the words before it classifies them.
DUTIES_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"quote": {"type": "string"},
                       "kind": {"type": "string", "enum": [DUTY, OFFER]}},
        "required": ["quote", "kind"],
        "additionalProperties": False}}},
    "required": ["items"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Duty:
    quote: str
    kind: str


@dataclass(frozen=True)
class Duties:
    items: tuple[Duty, ...] = ()
    # Quotes the description does not contain, kept for review as `JobSpec.dropped` is.
    dropped: tuple[Duty, ...] = ()

    @property
    def duties(self) -> tuple[Duty, ...]:
        return tuple(d for d in self.items if d.kind == DUTY)


async def read_duties(provider: Provider, text: str) -> Duties:
    """D16: the description's duties and offers, each a verbatim span."""
    jd = _jd(text)
    out = await provider.complete(DUTIES_SYSTEM, jd, schema=DUTIES_SCHEMA, max_tokens=1200)
    kept: list[Duty] = []
    dropped: list[Duty] = []
    seen: set[str] = set()
    for item in ((out.json() or {}).get("items") or [])[:MAX_DUTIES]:
        quote = " ".join((item.get("quote") or "").split())
        kind = item.get("kind")
        if not quote or kind not in (DUTY, OFFER) or quote.lower() in seen:
            continue
        seen.add(quote.lower())
        (kept if _grounded_in(quote, jd) else dropped).append(Duty(quote, kind))
    return Duties(tuple(kept), tuple(dropped))


def overlaps(first: str, second: str) -> bool:
    """Two spans say the same thing: half the shorter one's content words are in the other."""
    a, b = set(_terms(first)), set(_terms(second))
    return bool(a and b) and len(a & b) / min(len(a), len(b)) >= 0.5


# --- generated questions (V1.2_PLAN D10, D18) ------------------------------------------------

GENERATE_SYSTEM = """You are writing ONE interview question from one duty in a job description.

The question asks the candidate about something they have ALREADY DONE that shows they can do
this duty, so the answer can be a real situation, what they did, and how it turned out.

Rules:
- Write from the FIRST duty in the list that a question for this phase can ask about. If none
  fits the phase, write from the first.
- Begin with "Tell me about", "Describe" or "Walk me through".
- Ask about one thing, in one sentence, or two when the second asks for one detail. At most 24
  words.
- Ask about that one thing only. Do not add a second ask the duty does not need, such as a
  decision made without all the information.
- Name the kind of work, not this employer's own product or industry: "a feature you
  redesigned", not "a pet-insurance quote feature".
- Ask about the past. Never "would you", "how would", "imagine", "suppose" or "if you were".
- Keep to the duty's own subject, pitched so a candidate at the given level could have done it.
- Do not ask anything the plan already asks, in the same words or in different ones.
- "duty" is the duty you wrote from, copied exactly from the list.
- "competency" is the one from the list that the question shows best.
- "min_level" is the lowest level that could answer it from their own experience.

Questions that sound right:
- "Tell me about a decision you made without all the information you wanted."
- "Describe a time a hand-off between you and someone else went wrong."
- "Tell me about a time you had to choose between two reasonable options. How did you decide?\""""

# "Tell me how" opens one approved question (da.quality.2); "how would" still fails.
OPENERS = ("tell me about", "tell me how", "describe", "walk me through")
# D18's list plus "you would": "Tell me about how you would..." passed without it. A past
# "knew you would miss" falls back to the bank question, the safe direction.
HYPOTHETICAL = re.compile(r"\b(would you|you would|how would|imagine|suppose|if you were)\b",
                          re.I)
# The bank's STAR questions run 9 to 24 words; `bank.perf.1` is two sentences.
MAX_GENERATED_WORDS = 24
MAX_SENTENCES = 2
CHECKS = ("duty", "opener", "shape", "past", "distinct", "competency", "level")

# What a scored phase asks about, for the prompt. Any other scored phase is the field's round.
PHASE_BRIEF = {
    "behavioural_core": "how they work: owning outcomes, making decisions, learning",
    "collaboration": "working with other people: colleagues, stakeholders, disagreement",
}
ROUND_BRIEF = "the hands-on work of the job"
FILL_ORDER = {"collaboration": 0, "behavioural_core": 2}
MAX_CHOICES = 6


def _generate_schema(competencies: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "duty": {"type": "string"},
            "question": {"type": "string"},
            "competency": {"type": "string", "enum": competencies},
            "min_level": {"type": "string", "enum": list(SENIORITY)},
        },
        "required": ["duty", "question", "competency", "min_level"],
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    reason: str = ""


def check_generated(text: str, competency: str, min_level: str, duty: str, *, level: str,
                    jd: str, duties: Duties, competencies: list[str], existing: list[str],
                    similarity=None, choices: list[str] | None = None,
                    allowed: tuple[str, ...] = ()) -> tuple[Check, ...]:
    """D18's checks, every one run, so a fallback can say which failed. With `choices`, the
    duty must also be one of them, which is what keeps a duty from being used twice. With
    `allowed` (D21), the competency must be one of those."""
    text = " ".join((text or "").split())
    words = len(text.split())
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text) if s]
    out = [
        Check("duty", _grounded_in(duty, jd)
              and any(overlaps(duty, d.quote) for d in duties.duties)
              and (choices is None or any(overlaps(duty, c) for c in choices)),
              "the duty is not one of the description's unused duties: %r" % duty),
        Check("opener", text.lower().startswith(OPENERS),
              'it must begin with "Tell me about", "Tell me how", "Describe" or "Walk me '
              'through"'),
        Check("shape", 0 < words <= MAX_GENERATED_WORDS and len(sentences) <= MAX_SENTENCES
              and text.endswith((".", "?")),
              "it is %d words in %d sentences; the limit is %d words in %d, ending in . or ?"
              % (words, len(sentences), MAX_GENERATED_WORDS, MAX_SENTENCES)),
        Check("past", not HYPOTHETICAL.search(text),
              "it asks about a hypothetical, not something the candidate has done"),
    ]
    same = next((q for q in existing if q.lower() == text.lower()), None)
    if same is None and similarity is not None:
        for q in existing:
            score = similarity(text, q)
            if score is not None and score >= DUPLICATE:
                same = q
                break
    out.append(Check("distinct", same is None, "it restates a question already asked: %r" % same))
    if allowed:
        out.append(Check("competency", competency in allowed,
                         "%r is not one this slot may use: %s" % (competency, ", ".join(allowed))))
    else:
        out.append(Check("competency", competency in competencies,
                         "%r is not one of this phase's competencies" % competency))
    out.append(Check("level", min_level in SENIORITY
                     and SENIORITY.index(min_level) <= SENIORITY.index(level),
                     "it needs %s experience and the plan is pitched at %s" % (min_level, level)))
    return tuple(out)


@dataclass(frozen=True)
class Generated:
    """One generated slot: what was written, every attempt's checks, and the bank question the
    slot keeps when no attempt passed."""
    phase: str
    duty: str
    text: str | None
    competency: str | None
    min_level: str | None
    attempts: tuple[dict, ...]
    fallback: str = ""
    allowed: tuple[str, ...] = ()

    @property
    def kept(self) -> bool:
        return self.text is not None


async def generate_question(provider: Provider, view: Bank, *, field_id: str, phase: str,
                            level: str, choices: list[str], duties: Duties, jd: str,
                            asked: list[str], allowed: tuple[str, ...], similarity=None,
                            retries: int = 1, replacing: str = "",
                            temperature: float = 0.0) -> Generated:
    """D18: one question from one duty, checked, retried once with the failed check's reason.

    `choices` are the duties still unused, in D10's priority order; the model writes from the
    first one this phase can ask about. `asked` is the plan's questions so far; the duplicate
    check also covers the view's bank. `allowed` are the competencies the question may show
    (D21, `open_competencies`). `replacing` is the slot's question when Replace asks again."""
    competencies = sorted(c for c, p in view.phase_affinity.items() if p == phase)
    offered = list(allowed)
    listed = "\n".join("- %s: %s" % (c, view.competencies[c]) for c in offered)
    one = len(offered) == 1
    pick = ("%s the plan does not ask about yet (%s):\n%s\n\nWrite from the first duty in "
            "the list that a question showing %s can ask about."
            % ("COMPETENCY" if one else "COMPETENCIES",
               "the question must show it" if one else "choose the one the duty shows best",
               listed, "it" if one else "one of them"))
    existing = asked + [q.text for q in view.questions if q.text not in asked]
    shown = choices[:MAX_CHOICES]
    base = ("JOB: %s, pitched at %s level.\nPHASE: %s\n\nDUTIES, in priority order:\n%s\n\n"
            "%s\n\nTHE PLAN ALREADY ASKS:\n%s"
            % (fields.get(field_id).interview, level, PHASE_BRIEF.get(phase, ROUND_BRIEF),
               "\n".join("%d. %s" % (n, d) for n, d in enumerate(shown, 1)), pick,
               "\n".join("- %s" % q for q in asked) or "- nothing yet"))
    if replacing:
        base += ("\n\nTHE QUESTION BEING REPLACED: %s\nWrite a different question from the same "
                 "duty." % replacing)
    sampling = {"temperature": temperature} if temperature else {}
    duty = shown[0]
    attempts: list[dict] = []
    user = base
    for _ in range(retries + 1):
        try:
            out = await provider.complete(GENERATE_SYSTEM, user,
                                          schema=_generate_schema(offered), max_tokens=250,
                                          **sampling)
            raw = out.json() or {}
        except ProviderError as e:
            attempts.append({"error": str(e)})
            continue
        text = " ".join((raw.get("question") or "").split())
        got = {"text": text, "competency": raw.get("competency"),
               "min_level": raw.get("min_level"),
               "duty": " ".join((raw.get("duty") or "").split())}
        checks = check_generated(text, got["competency"], got["min_level"], got["duty"],
                                 level=level, jd=jd, duties=duties, competencies=competencies,
                                 existing=existing, similarity=similarity, choices=shown,
                                 allowed=allowed)
        attempts.append({**got, "checks": [c.__dict__ for c in checks]})
        failed = [c for c in checks if not c.ok]
        if not failed:
            used = next((d for d in shown if d.lower() == got["duty"].lower()),
                        next(d for d in shown if overlaps(got["duty"], d)))
            return Generated(phase, used, text, got["competency"], got["min_level"],
                             tuple(attempts), allowed=allowed)
        user = ("%s\n\nYOUR LAST QUESTION: %s\nIT FAILED: %s\nWrite a different question that "
                "passes." % (base, text, "; ".join(c.reason for c in failed)))
    return Generated(phase, duty, None, None, None, tuple(attempts), allowed=allowed)


def open_competencies(view: Bank, plan: dict, phase: str, replaced: str,
                      known: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """D21's choice for one slot: the replaced question's competencies first (the
    phase's share, or all of them when none is the phase's, as with software's "technical
    decision you'd make differently" in technical_experience), then the phase's others, less
    every competency another question in the plan asks about. A behavioural slot left with
    fewer than two gives nothing, and keeps its bank question; any other slot whose every
    option is taken keeps its own. A question with none known gives nothing.
    `known` maps each question's text to its competencies, generated ones included.
    Free to choose any of the phase's, local Qwen took decision_making in about 30 of 40
    behavioural slots and Groq ownership in 36 of 45, repeating what the plan already asked
    (14/11 gate)."""
    own = known.get(replaced, ())
    mine = tuple(c for c in own if view.phase_affinity.get(c) == phase) or tuple(own)
    if not mine:
        return ()
    taken = {c for ph in plan["phases"] for q in ph.get("questions", []) if q != replaced
             for c in known.get(q, ())}
    rest = sorted(c for c, p in view.phase_affinity.items() if p == phase and c not in mine)
    offered = tuple(c for c in mine + tuple(rest) if c not in taken)
    if phase == "behavioural_core":
        # Given one, local Qwen forced it onto any duty here: 21 of 30 such questions well
        # formed. A round's one fits its duties better, 17 of 22 (14/11 gate). Duy: "Limit to
        # behavioural", after skipping every one-option slot left no technical round question.
        return offered if len(offered) > 1 else ()
    return offered or mine


def duty_order(duties: Duties, spec: JobSpec, covered: tuple[str, ...]) -> list[Duty]:
    """D10: the duties no selected question answers first, then the rest, each group in the
    description's order. A duty is answered when it overlaps the evidence of a requirement
    whose bank question made the plan."""
    evidence = [r.evidence for r in spec.requirements if r.name in covered]
    answered = [d for d in duties.duties if any(overlaps(d.quote, e) for e in evidence)]
    return [d for d in duties.duties if d not in answered] + answered


async def fill_generated(provider: Provider, assembled: Assembled, spec: JobSpec,
                         duties: Duties, view: Bank, *, field_id: str, jd: str,
                         similarity=None) -> tuple[dict, tuple[Generated, ...]]:
    """D10: at most one generated question per scored phase, in a slot the template or a
    top-up filled. A slot whose question fails keeps its bank question, so the plan is never
    shorter or differently shaped than the bank-only one."""
    plan = copy.deepcopy(assembled.plan)
    known = {q.text: tuple(q.competencies) for q in view.questions}
    pool = [d.quote for d in duty_order(duties, spec, assembled.covered)]
    order = [ph["id"] for ph in plan["phases"]]
    rows: list[Generated] = []
    # The most constrained phase chooses first: collaboration needs a duty about other people,
    # behavioural_core can be written from almost any. Taken in plan order, the collaboration
    # slot was left "comfortable with PostgreSQL and message queues" (13/11, local Qwen).
    for ph in sorted(plan["phases"], key=lambda p: FILL_ORDER.get(p["id"], 1)):
        pid = ph["id"]
        # Design and case phases stay curated: unscored, and a hypothetical is the hardest
        # thing for the model to write well.
        if not ph.get("scored") or ph.get("observation_shape") == "design":
            continue
        if pid not in assembled.picked or not pool:
            continue
        slots = [i for i, q in enumerate(ph["questions"]) if q not in assembled.picked[pid]]
        if not slots:
            continue
        i = slots[-1]
        allowed = open_competencies(view, plan, pid, ph["questions"][i], known)
        if not allowed:
            continue
        asked = [q for p in plan["phases"] for q in p.get("questions", [])]
        g = await generate_question(provider, view, field_id=field_id, phase=pid,
                                    level=spec.seniority, choices=pool, duties=duties, jd=jd,
                                    asked=asked, allowed=allowed, similarity=similarity)
        g = replace(g, fallback=ph["questions"][i])
        if g.kept:
            ph["questions"][i] = g.text
            known[g.text] = (g.competency,)
            # A failed slot leaves its duty for another phase: no duty is used twice (D10).
            pool.remove(g.duty)
        rows.append(g)
    return plan, tuple(sorted(rows, key=lambda g: order.index(g.phase)))


# --- the gap path and planning from a description (V1.2_PLAN D17, P3) ------------------------

# Plain words for the plan's notes line, by the first check that failed.
FELL_BACK = {
    "duty": "its duty was not in the description",
    "opener": "it did not open as an interview question",
    "shape": "it ran too long",
    "past": "it asked what you would do",
    "distinct": "it repeated a question the plan asks",
    "competency": "it asked about something the slot does not cover",
    "level": "it was pitched above the plan's level",
}
PROMPT_HASH = hashlib.sha256(GENERATE_SYSTEM.encode("utf-8")).hexdigest()[:12]
NO_DUTIES = "No question was written from the description: none of its duties could be read."


def _failed(g: Generated) -> list[dict]:
    last = g.attempts[-1] if g.attempts else {}
    return [c for c in last.get("checks", []) if not c["ok"]]


def fell_back_because(g: Generated) -> str:
    last = g.attempts[-1] if g.attempts else {}
    if "error" in last:
        return "the model did not answer"
    failed = _failed(g)
    return FELL_BACK.get(failed[0]["name"], failed[0]["name"]) if failed else "nothing came back"


async def propose_question(provider: Provider, bank: Bank, competency: str, evidence: str,
                           *, jd: str = "", level: str = "mid", asked: list[str] | None = None,
                           similarity=None, question_id: str | None = None) -> Question:
    """Write one question for a competency the description asked for. It comes back PROPOSED.

    Nothing here can produce an askable question. That is the whole point: FR-2 allows
    generation and FR-6 promises every scripted question is asked verbatim, and the only way
    both hold is if a person reads the text before a candidate hears it.

    D17: the same generator and checks as a generated slot, with the requirement's evidence as
    the duty. Without a description, the competency's own description stands in for both.
    """
    if competency not in bank.competencies:
        raise KeyError("unknown competency %r" % competency)
    field_id = bank.view_of or fields.SOFTWARE
    phase = bank.phase_for(competency)
    if template_shapes(fields.get(field_id).template).get(phase) == "design":
        raise ValueError("%s is asked in the design or case phase, whose questions stay curated"
                         % competency)
    duty = " ".join((evidence or "").split()) or bank.competencies[competency]
    g = await generate_question(provider, bank, field_id=field_id, phase=phase, level=level,
                                choices=[duty], duties=Duties((Duty(duty, DUTY),)),
                                jd=jd or duty, asked=list(asked or ()), allowed=(competency,),
                                similarity=similarity)
    if not g.kept:
        last = g.attempts[-1] if g.attempts else {}
        raise ValueError("no question passed the checks: %s"
                         % (last.get("error") or "; ".join(c["reason"] for c in _failed(g))))
    return Question(id=question_id or ("gen.%s.%d" % (competency, len(bank.questions) + 1)),
                    text=g.text, competencies=(competency,), shape="star",
                    source="generated", status="proposed", min_level=g.min_level,
                    field=field_id)


def generated_row(g: Generated, model: str | None) -> dict:
    """One kept slot as the plan records it; `fallback` is the bank question it replaced."""
    last = g.attempts[-1] if g.attempts else {}
    return {"phase": g.phase, "text": g.text, "duty": g.duty, "competency": g.competency,
            "min_level": g.min_level, "model": model, "prompt_hash": PROMPT_HASH,
            "checks": [c["name"] for c in last.get("checks", []) if c["ok"]],
            "fallback": g.fallback, "kept": False}


def written_note(rows: tuple[Generated, ...]) -> str:
    """'2 written from the description; 1 fell back: it asked what you would do.'"""
    if not rows:
        return ""
    kept = [g for g in rows if g.kept]
    lost = [g for g in rows if not g.kept]
    note = "%d written from the description" % len(kept)
    if lost:
        note += "; %d fell back: %s" % (len(lost), "; ".join(fell_back_because(g) for g in lost))
    return note + "."


def job_description(text: str, field_id: str, detection: Detection | None, spec: JobSpec,
                    duties: Duties, covered: tuple[str, ...]) -> dict:
    evidence = [r.evidence for r in spec.requirements if r.name in covered]
    return {
        "text": _jd(text),
        "field": field_id,
        "field_evidence": (detection.evidence
                           if detection is not None and detection.field == field_id else ""),
        "role": spec.role,
        "seniority": spec.seniority,
        "requirements": [{"name": r.name, "evidence": r.evidence} for r in spec.requirements],
        "dropped": [{"name": r.name, "evidence": r.evidence} for r in spec.dropped],
        "duties": [{"quote": d.quote, "kind": d.kind,
                    "answered": any(overlaps(d.quote, e) for e in evidence)}
                   for d in duties.items],
        "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@dataclass(frozen=True)
class Planned:
    assembled: Assembled
    spec: JobSpec
    field: str
    detection: Detection | None
    generated: tuple[Generated, ...]


async def plan_description(provider: Provider, bank: Bank, text: str, *,
                           field_id: str | None = None, detection: Detection | None = None,
                           minutes: int | None = None, similarity=None,
                           recent: dict[str, str] | None = None,
                           model: str | None = None) -> Planned:
    """D13, FR-1, D16 and D10 in order: the field, what the description asks for, the bank
    plan, its duties and the generated slots. `bank` is the whole bank. `field_id` skips
    detection (the switch), keeping `detection` as it was first read. A description detection
    cannot ground is planned as general, the field for any other kind of work."""
    jd = _jd(text)
    if field_id is None:
        detection = await detect_field(provider, jd)
        field_id = detection.field or fields.GENERAL
    view = bank.view(field_id)
    spec = await read_jd(provider, view, jd)
    a = assemble(spec, view, field=field_id, minutes=minutes, recent=recent)
    try:
        duties = await read_duties(provider, jd)
    except ProviderError:
        # Generated slots are an extra on the bank plan: without duties the plan is the bank's.
        duties = Duties()
    plan, rows = await fill_generated(provider, a, spec, duties, view, field_id=field_id,
                                      jd=jd, similarity=similarity)
    plan["job_description"] = job_description(text, field_id, detection, spec, duties,
                                              a.covered)
    plan["generated"] = [generated_row(g, model) for g in rows if g.kept]
    # Local Qwen sometimes reads no duty at all (14/11, the same text read fine minutes before);
    # the plan says so rather than looking as if generation never ran.
    note = written_note(rows) or ("" if duties.duties else NO_DUTIES)
    if note:
        plan["notes"] = "%s %s" % (plan["notes"], note)
    return Planned(replace(a, plan=plan), spec, field_id, detection, rows)


# Replace asks again for the same duty, and at 0 local Qwen wrote the slot's question again
# (14/11: both of two Replaces failed). 0.7 read well in the gate's free-choice run, 90.2%.
REPLACE_TEMPERATURE = 0.7


async def regenerate(provider: Provider, view: Bank, plan: dict, row: dict, *,
                     similarity=None) -> Generated:
    """Replace: another question for a generated slot's duty and competency, through the same
    checks. The slot's own question is among those asked, so it cannot come back."""
    jd = plan.get("job_description") or {}
    duties = Duties(tuple(Duty(d["quote"], d["kind"]) for d in jd.get("duties", []))
                    or (Duty(row["duty"], DUTY),))
    return await generate_question(
        provider, view, field_id=plan.get("field", fields.SOFTWARE), phase=row["phase"],
        level=jd.get("seniority") or "mid", choices=[row["duty"]], duties=duties,
        jd=jd.get("text") or row["duty"],
        asked=[q for ph in plan["phases"] for q in ph.get("questions", [])],
        allowed=(row["competency"],), similarity=similarity, replacing=row["text"],
        temperature=REPLACE_TEMPERATURE)
