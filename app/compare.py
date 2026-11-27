"""Two interviews side by side (FR-25; V1.1_PLAN P6).

Built from the two reports as they were scored, never re-scored here, so the numbers on the
compare page are the numbers each report already shows. Questions pair by their wording rather
than their id: two plans can both have a `p1.1` that asks different things, and one plan sat
twice asks the same words under the same id anyway.
"""

from __future__ import annotations

from .corrections import scored_answers
from .report import about
from .score import met_by_question

DELIVERY = ("spoken", "articulation_rate", "wpm", "pause_count", "mid_clause_share",
            "speaking_seconds")


def _key(question: str) -> str:
    return " ".join((question or "").lower().split())


def _planned(session: dict) -> tuple:
    """Which plan an interview sat. A plan from a description is named for its role, so two
    descriptions for the same role share an id; when the description was read tells them apart."""
    snap = session.get("plan_snapshot") or {}
    return session.get("plan_id"), (snap.get("job_description") or {}).get("read_at")


def _side(report: dict, session: dict) -> dict:
    info = about(session)
    return {
        "session_id": report.get("session_id") or session.get("session_id"),
        "label": report.get("label"),
        "plan_id": session.get("plan_id"),
        "field": info["field"],
        "field_label": info["field_label"],
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

    questions: dict[tuple, dict] = {}
    generated = False
    for side, report, session in (("a", ra, sa), ("b", rb, sb)):
        met = met_by_question(rubric[side])
        duty = {g["question_id"]: g["duty"] for g in about(session)["generated"]}
        generated = generated or bool(duty)
        for qid, (question, answers) in scored_answers(session, report.get("corrections")).items():
            # A written question belongs to its plan: two plans' never pair, even word for word.
            key = (_key(question) or "%s:%s" % (side, qid),
                   _planned(session) if qid in duty else None)
            row = questions.setdefault(key, {"question": question, "duty": duty.get(qid),
                                             "a": None, "b": None})
            row[side] = {"question_id": qid, "answers": answers, "met": met.get(qid) or {}}

    a, b = _side(ra, sa), _side(rb, sb)
    same_plan = bool(sa.get("plan_id")) and _planned(sa) == _planned(sb)
    same_field = a["field"] == b["field"]
    note = None
    if not same_field:
        note = ("These interviews were for different fields (%s, then %s), so their plans "
                "differ too." % (a["field_label"], b["field_label"]))
    elif not same_plan:
        note = "These interviews used different plans."
    if note:
        note += (" Questions asked in both sit side by side; the rest appear under the interview "
                 "that asked them.")
        if generated:
            note += (" A question written from a job description belongs to its own plan, so it "
                     "is never paired with another plan's.")
    return {
        "a": a,
        "b": b,
        "same_plan": same_plan,
        "same_field": same_field,
        "note": note,
        "criteria": sorted(criteria.values(), key=lambda c: c["label"].lower()),
        "questions": list(questions.values()),
        "delivery": {side: {k: (r.get("delivery") or {}).get(k) for k in DELIVERY}
                     for side, r in (("a", ra), ("b", rb))},
    }
