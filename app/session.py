"""Session state and persistence. Plan sections 5.2.2 and 8.

Local files, our own schema, no database server and no framework checkpointer. The
granularity is ours: state is written at question boundaries, which LangGraph's per-invocation
`durability` cannot express (section 5.2.2).

Layout per section 8:

    data/sessions/<session-id>/
        session.json      plan snapshot, timings, status
        transcript.json   every turn, verbatim
        decisions.jsonl   one line per turn: the decision AND the prompt that produced it

`decisions.jsonl` carries the prompt verbatim because that is what makes replay possible.
The reference project lost every completed interview for the life of a feature to a silent
body-size limit; local files avoid the class, and any later HTTP hop carrying this payload
gets an explicit limit and a logged failure.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .score import CRITERIA

ROOT = Path(__file__).resolve().parent.parent
SESSIONS = ROOT / "data" / "sessions"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Turn:
    index: int
    phase: str
    question_id: str
    question: str
    utterance: str
    act: str
    say: str
    ok: bool
    ask: str
    guards: list[str] = field(default_factory=list)
    at: str = field(default_factory=now)


@dataclass
class QuestionState:
    phase: str
    question_id: str
    question: str
    probes_used: int = 0
    answers: list[str] = field(default_factory=list)
    # Separate from `answers` on purpose: what the candidate ASKED is not evidence about how
    # they answer, and putting the two in one list is how a candidate's questions came to be
    # extracted as STAR parts for a scored question.
    asked_back: list[str] = field(default_factory=list)
    closed_by: str | None = None
    # WHY it closed. `closed_by` alone cannot separate an answer the model was satisfied with
    # from a question that ran out of turns, and those are opposite facts about the session.
    closed_because: str | None = None


@dataclass
class SessionState:
    session_id: str
    plan_id: str
    started_at: str
    status: str = "running"           # running | complete | ended_early
    ended_at: str | None = None
    turns: list[Turn] = field(default_factory=list)
    questions: list[QuestionState] = field(default_factory=list)

    @property
    def dir(self) -> Path:
        return SESSIONS / self.session_id


def new_session(plan: dict, provenance: dict | None = None) -> SessionState:
    sid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    s = SessionState(session_id=sid, plan_id=plan.get("id", "unknown"), started_at=now())
    s.dir.mkdir(parents=True, exist_ok=True)
    # Snapshot the plan. Editing a saved plan must never retroactively change what a past
    # session claims it asked (section 8).
    #
    # `provenance` is passed in rather than gathered here: this module does not touch the
    # network or the process table, and the model identity is the caller's to know.
    _write(s.dir / "session.json", {
        "session_id": sid, "plan_id": s.plan_id, "started_at": s.started_at,
        "status": s.status, "plan_snapshot": plan,
        "provenance": provenance or {},
    })
    return s


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")


def append_decision(state: SessionState, record: dict) -> None:
    """One line per turn. Append-only, so a crash keeps everything before it."""
    path = state.dir / "decisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def checkpoint(state: SessionState) -> None:
    """Persist at a question boundary. Chosen granularity, our schema, diffable in a test."""
    _write(state.dir / "transcript.json",
           {"session_id": state.session_id,
            "turns": [asdict(t) for t in state.turns]})
    meta = json.loads((state.dir / "session.json").read_text(encoding="utf-8"))
    meta.update({"status": state.status, "ended_at": state.ended_at,
                 "turn_count": len(state.turns),
                 "questions": [asdict(q) for q in state.questions]})
    _write(state.dir / "session.json", meta)


# The phase types the runner knows how to run. A plan naming anything else fails at LOAD
# rather than at the turn that needed it: `type` and `detour_budget` were configured for
# every phase and read by nothing, so `closing` declared itself a user-questions phase and
# was run by the generic loop, which captured the candidate's questions and advanced past
# them. A setting with no consumer is a comment that looks like a setting.
PHASE_TYPES = frozenset({"fixed_sequence", "adaptive_discussion", "long_turn",
                         "user_questions"})


def load_plan(path: str | Path) -> dict:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    for phase in plan.get("phases", []):
        # answer_shape is required and validated at load, never defaulted (section 3.2).
        # A saved config that dropped the field once sat dormant in production for weeks,
        # silently degrading to the slowest setting.
        if not phase.get("answer_shape"):
            raise ValueError("phase %r is missing answer_shape" % phase.get("id"))
        kind = phase.get("type")
        if not kind:
            raise ValueError("phase %r is missing type" % phase.get("id"))
        if kind not in PHASE_TYPES:
            raise ValueError("phase %r declares type %r, which no handler implements. "
                             "Known types: %s"
                             % (phase.get("id"), kind, ", ".join(sorted(PHASE_TYPES))))
        # The same class as the check above, and the one a generated plan will hit first.
        # `score_question` skips a name it does not recognise, so a phase asking for three
        # criteria could score one and report the denominator it happened to reach -- no
        # error, no warning, a quietly smaller rubric. Harmless while one plan is written by
        # hand; active the moment Stage 3 writes them, and `communication` (removed as
        # unobservable, 7.36) is exactly the name a model reaches for.
        unknown = [c for c in phase.get("rubric_criteria", []) if c not in CRITERIA]
        if unknown:
            raise ValueError("phase %r asks to be scored on %s, which nothing implements. "
                             "Known criteria: %s"
                             % (phase.get("id"), ", ".join(repr(u) for u in unknown),
                                ", ".join(sorted(CRITERIA))))
        if phase.get("scored") and not phase.get("rubric_criteria"):
            raise ValueError("phase %r is marked scored but names no rubric_criteria, so it "
                             "would contribute nothing to the report" % phase.get("id"))
    return plan


def iter_questions(plan: dict):
    """Flatten the plan into the order the runner will ask in."""
    for phase in plan.get("phases", []):
        for i, q in enumerate(phase.get("questions", [])):
            yield {
                "phase": phase["id"],
                "question_id": "%s.%d" % (phase["id"], i + 1),
                "question": q,
                "probe_budget": phase.get("probe_budget", 2),
                "scored": phase.get("scored", False),
                # Both were dropped here, which is what made them configuration fiction.
                "type": phase.get("type", "adaptive_discussion"),
                "detour_budget": phase.get("detour_budget", 0),
                # Both feed the focus selector. `rubric_criteria` was missing here, so the
                # signal path never ran and every phase silently fell through to the
                # unscored ladder -- which is why CONTEXT and ROLE were asked on questions
                # that have neither a scale nor a team (log 8.20).
                "rubric_criteria": phase.get("rubric_criteria", []),
                "focus_ladder": phase.get("focus_ladder", []),
                "observation_shape": phase.get("observation_shape", "star"),
            }
