"""Two interviews side by side (FR-25; V1.1_PLAN P6).

Built from the two reports as they were scored, never re-scored here, so the numbers on the
compare page are the numbers each report already shows. Questions pair by their wording rather
than their id: two plans can both have a `p1.1` that asks different things, and one plan sat
twice asks the same words under the same id anyway.
"""

from __future__ import annotations

from .corrections import scored_answers
from .score import met_by_question

DELIVERY = ("spoken", "articulation_rate", "wpm", "pause_count", "mid_clause_share",
            "speaking_seconds")


def _key(question: str) -> str:
    return " ".join((question or "").lower().split())


def _side(report: dict, session: dict) -> dict:
    return {
        "session_id": report.get("session_id") or session.get("session_id"),
        "label": report.get("label"),
        "plan_id": session.get("plan_id"),
        "started_at": report.get("started_at") or session.get("started_at"),
        "asked": report.get("asked", 0),
        "answered": report.get("answered", 0),
        "scored": report.get("scored", 0),
        "scored_by": report.get("scored_by"),
        "corrected": len(report.get("corrections") or []),
    }


def compare(first: tuple[dict, dict], second: tuple[dict, dict]) -> dict:
    """Each argument is (report payload, session.json). The earlier interview is `a`."""
    (ra, sa), (rb, sb) = sorted(
        (first, second), key=lambda x: x[0].get("started_at") or x[1].get("started_at") or "")
    rubric = {"a": ra.get("rubric") or [], "b": rb.get("rubric") or []}

    criteria: dict[str, dict] = {}
    for side, rows in rubric.items():
        for c in rows:
            row = criteria.setdefault(c["name"], {
                "name": c["name"],
                "label": c.get("label") or c["name"].replace("_", " "),
                "description": c.get("description") or "", "a": None, "b": None})
            row[side] = {"met": c.get("met", 0), "of": c.get("of", 0)}

    questions: dict[str, dict] = {}
    for side, report, session in (("a", ra, sa), ("b", rb, sb)):
        met = met_by_question(rubric[side])
        for qid, (question, answers) in scored_answers(session, report.get("corrections")).items():
            row = questions.setdefault(_key(question) or "%s:%s" % (side, qid), {
                "question": question, "a": None, "b": None})
            row[side] = {"question_id": qid, "answers": answers, "met": met.get(qid) or {}}

    same_plan = bool(sa.get("plan_id")) and sa.get("plan_id") == sb.get("plan_id")
    return {
        "a": _side(ra, sa),
        "b": _side(rb, sb),
        "same_plan": same_plan,
        "note": None if same_plan else (
            "These interviews used different plans. Questions asked in both sit side by side; "
            "the rest appear under the interview that asked them."),
        "criteria": sorted(criteria.values(), key=lambda c: c["label"].lower()),
        "questions": list(questions.values()),
        "delivery": {side: {k: (r.get("delivery") or {}).get(k) for k in DELIVERY}
                     for side, r in (("a", ra), ("b", rb))},
    }
