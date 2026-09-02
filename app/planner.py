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

import json
from dataclasses import dataclass, field
from pathlib import Path

from .bank import Bank, Question
from .observe import _grounded as _grounded_in
from .provider import Provider

# Closed, and ordered from least to most senior so a caller can compare. These are the four
# the question bank can actually differentiate; inventing more would imply a precision the
# plan does not have.
SENIORITY = ("junior", "mid", "senior", "staff")

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


async def read_jd(provider: Provider, bank: Bank, text: str) -> JobSpec:
    """Extract FR-1's role, seniority and ranked competencies from a pasted description."""
    jd = (text or "").strip()
    if len(jd.split()) < 20:
        raise ValueError("this does not look like a job description: %d words. FR-4 runs a "
                         "stock plan without one, which is the path for having no JD."
                         % len(jd.split()))
    jd = jd[:MAX_JD_CHARS]

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

    return JobSpec(role=role, seniority=seniority,
                   requirements=tuple(kept), dropped=tuple(dropped))


# A proposal is one question, and the model is told the shape rather than trusted to infer it.
PROPOSE_SYSTEM = """You are writing ONE interview question for a software engineering role.

The question must ask the candidate about something they have ALREADY DONE, so that the answer
can be a real situation, what they did, and how it turned out.

Rules:
- Write ONE question, at most 20 words. End it with a question mark.
- Questions that sound right: "Tell me about a schema change you made to a system that was
  already live." / "Describe a production incident you were responsible for resolving." /
  "Tell me about a time you made something faster and could show by how much."
  Match that length. Anything longer is a form, not a conversation.
- Ask about the competency given, in the terms this employer used for it.
- Ask about something they DID, not something they would do."""

PROPOSE_SCHEMA = {
    "type": "object",
    "properties": {"question": {"type": "string"}},
    "required": ["question"],
    "additionalProperties": False,
}

# Long enough for a real question, short enough to be spoken. The scripted questions already
# in the bank run 9 to 24 words.
MAX_QUESTION_WORDS = 32
# Cosine similarity above which a proposal is judged to be a bank question in different
# words. UNMEASURED, and deliberately not `embed.SIMILAR`: that threshold is 0.33 and was
# fitted to a different question -- whether one PROBE repeats the previous probe inside a
# single interview. Two scripted questions about the same competency sit far higher than 0.33
# by construction, so borrowing it would reject almost every proposal. This is a placeholder
# until it is measured against labelled pairs the way the probe threshold was.
DUPLICATE = 0.75


async def propose_question(provider: Provider, bank: Bank, competency: str, evidence: str,
                           *, similarity=None, question_id: str | None = None) -> Question:
    """Write one question for a competency the JD asked for. It comes back PROPOSED.

    Nothing here can produce an askable question. That is the whole point: FR-2 allows
    generation and FR-6 promises every scripted question is asked verbatim, and the only way
    both hold is if a person reads the text before a candidate hears it.
    """
    if competency not in bank.competencies:
        raise KeyError("unknown competency %r" % competency)

    user = ("COMPETENCY: %s -- %s\n\nWHAT THIS EMPLOYER SAID ABOUT IT: %s"
            % (competency, bank.competencies[competency], evidence.strip()))
    out = await provider.complete(PROPOSE_SYSTEM, user, schema=PROPOSE_SCHEMA, max_tokens=200)
    text = " ".join(((out.json() or {}).get("question") or "").split())

    if not text.endswith("?"):
        raise ValueError("proposal is not a question: %r" % text)
    if len(text.split()) > MAX_QUESTION_WORDS:
        raise ValueError("proposal is %d words, over the %d-word cap: %r"
                         % (len(text.split()), MAX_QUESTION_WORDS, text))
    if any(text.lower() == q.text.lower() for q in bank.questions):
        raise ValueError("proposal is a bank question verbatim: %r" % text)
    if similarity is not None:
        for q in bank.questions:
            score = similarity(text, q.text)
            if score is not None and score >= DUPLICATE:
                raise ValueError("proposal restates %s (%.2f): %r" % (q.id, score, text))

    return Question(id=question_id or ("gen.%s.%d" % (competency, len(bank.questions) + 1)),
                    text=text, competencies=(competency,), shape="star",
                    source="generated", status="proposed")


# The phase configuration is TAKEN FROM the shipped plan, never generated. Every field in it
# is a measured decision -- `probe_budget` 3 -> 2 on the design phase (9.10), the design
# phase's `scored: false` and the paragraph explaining why scoring it inverts the ranking
# (9.6), each phase's focus ladder. A planner that re-derived those would be re-litigating
# settled measurements with a model, so assembly chooses QUESTIONS and nothing else.
TEMPLATE = "config/interview_swe_general.json"

# Phases whose questions assembly selects. Warmup and closing are structural: identical in
# every plan, carrying no competency, and their wording is the disclosure and the sign-off.
SELECTABLE = ("behavioural_core", "technical_experience", "design", "collaboration")


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


def _capacity(plan: dict, minutes: int | None,
              shape: dict[str, int] | None = None) -> dict[str, int]:
    """How many questions each phase should hold to land near a target length.

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
    # The floor is one question per surviving phase. Below it the request cannot be met, and
    # silently returning a longer interview than was asked for is the kind of quiet degrading
    # this codebase refuses elsewhere -- `answer_shape` is validated rather than defaulted for
    # the same reason.
    shortest = _estimate_counts(plan, {ph["id"]: 1 for ph in plan["phases"]})
    if minutes * 60 < shortest:
        raise ValueError("%d minutes is shorter than this plan can be: one question per phase "
                         "already runs about %d minutes"
                         % (minutes, round(shortest / 60)))
    full = _estimate_counts(plan, capacity)
    target = minutes * 60
    if target >= full:
        return capacity
    scale = target / full
    return {pid: max(1, round(n * scale)) for pid, n in capacity.items()}


def _select(role: str, seniority: str, ranked: list[Requirement], bank: Bank,
            template: str | Path, minutes: int | None, source_note: str,
            shape: dict[str, int] | None = None) -> Assembled:
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

    chosen: dict[str, list[str]] = {pid: [] for pid in SELECTABLE}
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
        want = "design" if phase == "design" else "star"
        options = [q for q in bank.for_competency(req.name)
                   if q.shape == want and q.id not in used
                   and q.text.lower() not in spoken]
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
        if not picked:
            continue
        # Fill the remaining slots from the template by EXCLUDING what was already selected,
        # not by index. Slicing by count asked the same question twice whenever a selected
        # question also appeared earlier in the template, which is the common case: the bank
        # was seeded from this very plan.
        keep = [q for q in ph["questions"] if q.lower() not in spoken]
        filled = (picked + keep)[:capacity[pid]]
        # A phase can still come up short: a question selected for one competency may have
        # moved out of the phase the template had it in, and the template has nothing left to
        # replace it. Top up from the bank rather than shipping a thinner interview, because
        # the shortfall is otherwise silent -- the plan simply has fewer questions than the
        # reviewed one it was built from.
        if len(filled) < capacity[pid]:
            want_shape = "design" if pid == "design" else "star"
            phase_competencies = [c for c, ph_id in bank.phase_affinity.items() if ph_id == pid]
            spare = [q for q in bank.questions
                     if q.askable and q.shape == want_shape
                     and any(c in q.competencies for c in phase_competencies)
                     and q.text.lower() not in spoken
                     and q.text.lower() not in {x.lower() for x in filled}]
            filled += [q.text for q in spare[:capacity[pid] - len(filled)]]
        ph["questions"] = filled
        spoken.update(q.lower() for q in ph["questions"])

    # A phase trimmed for length keeps its own questions, so the trim never leaves a phase
    # holding text that was chosen for a longer interview it is no longer part of.
    for ph in plan["phases"]:
        want = capacity.get(ph["id"], len(ph.get("questions", [])))
        ph["questions"] = ph.get("questions", [])[:want]

    plan["id"] = "generated.%s" % (role or "role").lower().replace(" ", "_")[:40]
    plan["label"] = "%s (%s)" % (role or "Interview", seniority)
    plan["notes"] = ("%s Phase configuration is the reviewed template; only the questions were "
                     "selected. Covered: %s. Not covered: %s."
                     % (source_note, ", ".join(covered) or "nothing",
                        ", ".join(gaps) or "nothing"))
    return Assembled(plan=plan, covered=tuple(covered), gaps=tuple(gaps),
                     estimated_secs=_estimate(plan))


def assemble(spec: JobSpec, bank: Bank, *, template: str | Path = TEMPLATE,
             minutes: int | None = None) -> Assembled:
    """FR-2: a JobSpec and a bank become a plan `session.load_plan` accepts."""
    return _select(spec.role, spec.seniority, list(spec.requirements), bank, template,
                   minutes, "Generated from a job description.")


# FR-4's three stock plans. Each carries a ranked competency list AND a phase shape, because
# the ranking alone does not produce three different interviews: every plan keeps the same
# phases, so a "technical" one still held two behavioural questions and a "behavioural" one
# two technical. Measured on the first version -- behavioural and technical shared 7 of 8
# questions, which made the choice cosmetic.
#
# `questions` is the number of questions that phase holds; 0 drops the phase entirely rather
# than leaving it empty, because a scored phase with no questions gives the rubric a
# denominator of zero. Dropping `design` is safe in a way dropping a scored phase is not: it
# is observed and described, never scored (9.6).
#
# `mixed` is not the union of the other two. It alternates so that trimming for length takes
# from both halves evenly -- a mixed interview cut to twenty minutes should still be mixed.
STOCK: dict[str, dict] = {
    "behavioural": {
        "ranked": ("collaboration", "ownership", "incident_response", "mentoring",
                   "learning", "technical_judgement"),
        "shape": {"warmup": 2, "behavioural_core": 5, "technical_experience": 1,
                  "design": 0, "collaboration": 3, "closing": 1},
    },
    "technical": {
        "ranked": ("data_modelling", "performance", "system_design", "testing_quality",
                   "incident_response", "technical_judgement"),
        "shape": {"warmup": 1, "behavioural_core": 1, "technical_experience": 6,
                  "design": 2, "collaboration": 1, "closing": 1},
    },
    "mixed": {
        "ranked": ("collaboration", "data_modelling", "ownership", "performance",
                   "system_design", "mentoring", "testing_quality", "learning"),
        "shape": {"warmup": 2, "behavioural_core": 3, "technical_experience": 3,
                  "design": 1, "collaboration": 2, "closing": 1},
    },
}


def stock_plan(kind: str, bank: Bank, *, minutes: int | None = None,
               template: str | Path = TEMPLATE) -> Assembled:
    """FR-4: an interview with no job description behind it.

    The same selection as the JD path, with a fixed ranked list standing in for what a
    description would have asked for. Nothing is invented for it: a stock competency carries
    no evidence, because there is no employer text to cite and a fabricated citation is
    exactly what the JD path drops.
    """
    if kind not in STOCK:
        raise KeyError("unknown stock plan %r; known: %s" % (kind, ", ".join(sorted(STOCK))))
    ranked = [Requirement(name=n, evidence="") for n in STOCK[kind]["ranked"]]
    return _select(kind.capitalize() + " interview", "mid", ranked, bank, template, minutes,
                   "Stock %s plan, no job description." % kind,
                   shape=STOCK[kind]["shape"])
