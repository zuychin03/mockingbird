"""Plan review over HTTP.

Every endpoint is a thin call into `app/review.py` or `app/planner.py`. The rules about what
may be asked live there and are not restated here, because a rule stated twice is a rule that
will disagree with itself: the approval gate in particular has to be the same object the
terminal tool uses, or one surface will eventually let through what the other refuses.

A refusal from the domain is a 400 carrying the domain's own sentence. Those sentences were
written to be read by a person -- "Approve it first: a plan may only hold text a person wrote
or a person approved" -- and rewriting them into API prose would lose the reason.

Single user, localhost, one draft at a time. The draft lives on disk, in the same file the
terminal tool uses, so the two surfaces are one workflow rather than two.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import bank as bank_mod  # noqa: E402
from app import (embed, observe, planner, provenance, provider as prov,  # noqa: E402
                 report as report_mod, resume, review, score as score_mod,
                 session as sess)

BANK = ROOT / "config" / "question_bank.json"
DRAFT = ROOT / "data" / "plan_draft.json"
LIVE = ROOT / "data" / "live_session.json"
SESSIONS = ROOT / "data" / "sessions"
UI = ROOT / "ui" / "build"

app = FastAPI(title="Mockingbird", docs_url="/api/docs")


def _bank() -> bank_mod.Bank:
    return bank_mod.load(BANK)


def _draft() -> review.Draft:
    if not DRAFT.exists():
        raise HTTPException(404, "no draft in progress")
    return review.read_draft(DRAFT, _bank())


def _state(d: review.Draft) -> dict:
    """What the UI needs to render a plan. `askable` is sent per question so the surface never
    has to work out for itself what may be asked."""
    review.write_draft(d, DRAFT)
    by_text = {q.text.lower(): q for q in d.bank.questions}
    return {
        "id": d.plan.get("id"),
        "label": d.plan.get("label"),
        "notes": d.plan.get("notes"),
        "editable": list(review.EDITABLE),
        "gaps": list(d.gaps),
        "spec": None if d.spec is None else {
            "role": d.spec.role,
            "seniority": d.spec.seniority,
            "requirements": [{"name": r.name, "evidence": r.evidence}
                             for r in d.spec.requirements],
            "dropped": [{"name": r.name, "evidence": r.evidence} for r in d.spec.dropped],
        },
        "phases": [{
            "id": ph["id"],
            "editable": ph["id"] in review.EDITABLE,
            "scored": bool(ph.get("scored")),
            # The planner's own per-question cost, not a second estimate. A running order
            # whose timings disagree with the arithmetic that trimmed the plan is worse than
            # one with no timings at all.
            "secs": planner._per_question(ph),
            "criteria": list(ph.get("rubric_criteria", [])),
            "questions": [{
                "text": q,
                "edited_from": d.edited_from.get(q),
                "source": getattr(by_text.get(q.lower()), "source", "curated"),
            } for q in ph.get("questions", [])],
        } for ph in d.plan["phases"]],
        "proposals": [{"id": q.id, "text": q.text, "competencies": list(q.competencies)}
                      for q in d.proposals],
        "competencies": d.bank.competencies,
        "stock_kinds": sorted(planner.STOCK),
    }


def _guard(fn, *args, **kwargs):
    """Domain refusals become 400s carrying the domain's own words."""
    try:
        return fn(*args, **kwargs)
    except prov.ProviderError as e:
        # 503, and the provider's own sentence: it already says which host it tried and
        # suggests `lms server start`, which is the whole answer. Without this the runtime
        # being down is an opaque 500 and the page says "Internal Server Error".
        raise HTTPException(503, str(e)) from e
    except (ValueError, IndexError) as e:
        raise HTTPException(400, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\"")) from e


@app.get("/api/plan")
def get_plan() -> dict:
    return _state(_draft())


@app.post("/api/plan/from-description")
async def from_description(text: str = Body(..., embed=True),
                           minutes: int | None = Body(None, embed=True)) -> dict:
    b = _bank()
    spec = await _guard_async(planner.read_jd, prov.LMStudio(), b, text)
    a = _guard(planner.assemble, spec, b, minutes=minutes)
    return _state(review.from_assembled(a, b, spec))


@app.post("/api/plan/from-stock")
def from_stock(kind: str = Body(..., embed=True),
               minutes: int | None = Body(None, embed=True)) -> dict:
    b = _bank()
    a = _guard(planner.stock_plan, kind, b, minutes=minutes)
    return _state(review.from_assembled(a, b, None))


@app.post("/api/plan/{phase_id}/questions")
def add_question(phase_id: str, text: str = Body(..., embed=True)) -> dict:
    return _state(_guard(review.add, _draft(), phase_id, text))


@app.put("/api/plan/{phase_id}/questions/{index}")
def edit_question(phase_id: str, index: int, text: str = Body(..., embed=True)) -> dict:
    return _state(_guard(review.edit, _draft(), phase_id, index, text))


@app.delete("/api/plan/{phase_id}/questions/{index}")
def delete_question(phase_id: str, index: int) -> dict:
    return _state(_guard(review.delete, _draft(), phase_id, index))


@app.post("/api/plan/{phase_id}/questions/{index}/move")
def move_question(phase_id: str, index: int, to: int = Body(..., embed=True)) -> dict:
    return _state(_guard(review.move, _draft(), phase_id, index, to))


@app.post("/api/proposals")
async def propose(competency: str = Body(..., embed=True)) -> dict:
    d = _draft()
    evidence = next((r.evidence for r in (d.spec.requirements if d.spec else ())
                     if r.name == competency), competency)
    q = await _guard_async(planner.propose_question, prov.LMStudio(), d.bank, competency,
                           evidence, similarity=embed.similarity)
    return _state(review.propose_into_bank(d, q))


@app.post("/api/proposals/{question_id}/approve")
def approve(question_id: str) -> dict:
    return _state(_guard(review.approve, _draft(), question_id))


@app.post("/api/plan/{phase_id}/from-bank")
def add_from_bank(phase_id: str, question_id: str = Body(..., embed=True)) -> dict:
    return _state(_guard(review.add_from_bank, _draft(), phase_id, question_id))


@app.post("/api/plan/save")
def save(path: str = Body(..., embed=True)) -> dict:
    d = _draft()
    target = ROOT / path
    if ROOT not in target.resolve().parents:
        raise HTTPException(400, "a plan is saved inside the project, not outside it")
    wrote_bank = any(q.generated and q.askable for q in d.bank.questions)
    _guard(review.save, d, target, BANK if wrote_bank else None)
    return {"saved": str(target.relative_to(ROOT)), "bank_updated": wrote_bank}


def _extractor(p):
    async def fn(question_id, question, utterance):
        return await observe.observe(p, question_id, question, [utterance])
    return fn


def _runner():
    """The snapshot carries its own plan, so nothing here has to know which one was running.
    A session started by the terminal harness resumes here and vice versa."""
    if not LIVE.exists():
        raise HTTPException(404, "no session in progress")
    p = prov.LMStudio()
    try:
        return resume.read(p, None, LIVE, observe_fn=_extractor(p),
                           similarity=embed.similarity)
    except KeyError as e:
        raise HTTPException(
            409, "this session predates the self-describing snapshot and cannot be resumed "
                 "here; finish it in the terminal or start a new one (%s)" % e) from e


def _turns(r) -> list[dict]:
    """The dialogue, and only the dialogue. Judgement fields -- `ok`, guard names, the
    posterior -- go to the decision record and never to the person being interviewed
    (section 12), so they are not in this payload at all."""
    out: list[dict] = []
    for t in r.state.turns:
        if t.utterance:
            out.append({"who": "candidate", "text": t.utterance})
        if (t.say or "").strip():
            out.append({"who": "interviewer", "text": t.say})
    return out


def _pending(r) -> str | None:
    """The line awaiting an answer, which `_turns` cannot show: a turn is only recorded once
    an answer closes it, so anything spoken after the last answer is in no turn yet.

    `said_this_question` decides which. `probe`, `reask` and `clarify` append to it and their
    line is also the last turn's `say`, so there is nothing more to show; the acts that close
    a question do not, and the boundary clears it, so empty means a fresh question. Derived
    rather than passed in because a resumed session has no caller to pass it -- reloading
    mid-interview used to leave the candidate no question at all.
    """
    if r.done or r.said_this_question or r.current is None:
        return None
    return r.current["question"]


def _session_state(r) -> dict:
    resume.write(r, LIVE)
    turns = _turns(r)
    pending = _pending(r)
    if pending:
        turns.append({"who": "interviewer", "text": pending})
    return {
        "session_id": r.state.session_id,
        "status": r.state.status,
        "started_at": r.state.started_at,
        "done": r.done,
        "question_number": min(r.index + 1, len(r.questions)),
        "question_total": len(r.questions),
        "turns": turns,
    }


@app.post("/api/session/start")
async def session_start(plan_path: str = Body(..., embed=True)) -> dict:
    target = (ROOT / plan_path).resolve()
    if ROOT not in target.parents:
        raise HTTPException(400, "a plan is loaded from inside the project")
    plan = _guard(sess.load_plan, target)
    model = prov.product_model(_guard(prov.loaded_models))
    if model is None:
        raise HTTPException(
            503, "%s is not loaded under that exact identifier in LM Studio" % prov.MODEL)
    state = sess.new_session(plan, provenance.snapshot(model))
    p = prov.LMStudio()
    r = resume.Runner(p, plan, state, observe_fn=_extractor(p), similarity=embed.similarity)
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    # Called for the effect, not the text: `ask` is the only place the rolling history
    # refreshes, and `_pending` derives the line to show.
    await _guard_async(r.ask)
    return _session_state(r)


@app.get("/api/session")
def session_get() -> dict:
    return _session_state(_runner())


@app.post("/api/session/answer")
async def session_answer(text: str = Body(..., embed=True)) -> dict:
    r = _runner()
    if r.done:
        raise HTTPException(400, "this session has finished")
    out = await _guard_async(r.submit, text)
    if out.closed_question and not r.done and not out.end_session:
        await _guard_async(r.ask)
    return _session_state(r)


SESSIONS_SHOWN = 50


@app.get("/api/sessions")
def sessions(limit: int = SESSIONS_SHOWN) -> list[dict]:
    """History, newest first. Read from the session records themselves rather than an index,
    so a session that exists on disk is always listed and one that was deleted always
    disappears.

    Capped because each record embeds a whole plan snapshot, and there were 206 of them here.
    Directory names begin with a timestamp, so reverse order is chronological before anything
    is opened and the scan stops early. The cap counts what is shown, not what is read, so a
    malformed record does not cost a row.
    """
    out = []
    for d in sorted(SESSIONS.glob("*/session.json"), reverse=True):
        if len(out) >= limit:
            break
        try:
            raw = json.loads(d.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({
            "session_id": raw.get("session_id"),
            "started_at": raw.get("started_at"),
            "status": raw.get("status"),
            "label": (raw.get("plan_snapshot") or {}).get("label") or raw.get("plan_id"),
            "questions": len(raw.get("questions") or []),
            "turns": raw.get("turn_count") or 0,
        })
    return out


@app.get("/api/sessions/{session_id}/report")
async def session_report(session_id: str) -> dict:
    """Extraction and scoring run here, not during the interview. They are offline work by
    design (the live and assessment channels are separate), so this is slow and deliberate
    rather than something the session view polls."""
    d = SESSIONS / session_id
    if not (d / "session.json").exists():
        raise HTTPException(404, "no session %r" % session_id)
    raw = json.loads((d / "session.json").read_text(encoding="utf-8"))
    plan = raw.get("plan_snapshot") or {}

    states = [sess.QuestionState(**q) for q in raw.get("questions", [])]
    # question_id -> that phase's rubric criteria. A question whose phase scores nothing maps
    # to an empty list and `score.build` skips it, which is how the warmup, design and closing
    # phases stay out of the rubric.
    criteria_for = {
        q: ph.get("rubric_criteria", [])
        for ph in plan.get("phases", [])
        for q in ["%s.%d" % (ph["id"], i + 1) for i in range(len(ph.get("questions", [])))]
    }
    criteria_for.update({qs.question_id: next(
        (ph.get("rubric_criteria", []) for ph in plan.get("phases", [])
         if qs.question_id.startswith(ph["id"])), []) for qs in states})
    p = prov.LMStudio()

    observations = []
    for qs in states:
        if not qs.answers:
            continue
        observations.append(await observe.observe(p, qs.question_id, qs.question, qs.answers))

    rep = score_mod.build(raw.get("session_id", session_id), observations, criteria_for)
    text = report_mod.render(rep, questions_asked=len(states),
                             questions_answered=sum(1 for q in states if q.answers),
                             observations=observations, question_states=states)
    return {
        "session_id": session_id,
        "label": plan.get("label") or raw.get("plan_id"),
        "started_at": raw.get("started_at"),
        "text": text,
        "scored": len(rep.scores),
        "asked": len(states),
        "answered": sum(1 for q in states if q.answers),
        # The rubric as data, so the report can be laid out rather than printed. The labels
        # live in `score.CRITERIA` and are the same strings the text renderer uses; sending
        # them keeps one wording, not two that drift.
        "rubric": [{"name": k, "label": score_mod.CRITERIA[k][0],
                    "description": score_mod.CRITERIA[k][1], "met": m, "of": n}
                   for k, (m, n) in sorted(rep.totals.items())],
    }


async def _guard_async(fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except prov.ProviderError as e:
        raise HTTPException(503, str(e)) from e
    except (ValueError, IndexError) as e:
        raise HTTPException(400, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\"")) from e


# The built UI, when there is one. Declared last so it never shadows /api, and absent
# entirely until `npm run build` has run -- the API is usable on its own.
#
# adapter-static emits hashed bundles under `_app/`, not `assets/`. Mounting the wrong name
# is a startup crash rather than a 404, which is the good failure: it cannot ship broken.
if UI.exists():
    if (UI / "_app").is_dir():
        app.mount("/_app", StaticFiles(directory=UI / "_app"), name="app_assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        candidate = (UI / path).resolve()
        if path and UI.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(UI / "index.html")
