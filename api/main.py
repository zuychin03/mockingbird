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

import sys
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import bank as bank_mod  # noqa: E402
from app import embed, planner, provider as prov, review  # noqa: E402

BANK = ROOT / "config" / "question_bank.json"
DRAFT = ROOT / "data" / "plan_draft.json"
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


async def _guard_async(fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
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
