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

import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import origin, voice  # noqa: E402
from app import bank as bank_mod  # noqa: E402
from app import compare as compare_mod  # noqa: E402
from app import corrections as corrections_mod  # noqa: E402
from app import examples as examples_mod  # noqa: E402
from app import (contract, detour as detour_mod, embed, hardware,  # noqa: E402
                 export as export_mod, observe, planner, provenance,
                 provider as prov, report as report_mod, resume, review,
                 score as score_mod, secret, session as sess, settings as settings_mod,
                 speech)

BANK = ROOT / "config" / "question_bank.json"
DRAFT = ROOT / "data" / "plan_draft.json"
LIVE = ROOT / "data" / "live_session.json"
SESSIONS = ROOT / "data" / "sessions"
UI = ROOT / "ui" / "build"

app = FastAPI(title="Mockingbird", docs_url="/api/docs")
# The 503 a failed model call becomes carries the provider's sentence to the page and nowhere
# else; a cloud interview that died on one was undiagnosable from the server log (08/11/2026).
log = logging.getLogger("uvicorn.error")


@app.middleware("http")
async def same_origin_only(request: Request, call_next):
    """Refuse a state-changing request another site's page sent (`api/origin.py`)."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin.foreign(
            request.headers.get("origin"), request.headers.get("host")):
        return JSONResponse({"detail": "refused: this request came from another site"}, 403)
    return await call_next(request)


def _bank() -> bank_mod.Bank:
    return bank_mod.load(BANK)


def _draft() -> review.Draft:
    if not DRAFT.exists():
        raise HTTPException(404, "no draft in progress")
    return review.read_draft(DRAFT, _bank())


def _rubric_preview(plan: dict) -> list[dict]:
    """How answers will be scored, for the sheet to show before anyone sits the interview.

    12.9 asks for this on the way in, not only in the report. Saying up front how someone will
    be judged is ordinary assessment practice, and it is what makes the report arguable
    afterwards instead of something to be taken on trust.

    Only criteria a phase actually declares appear. The plan's rubric block lists more than any
    one interview applies -- several are shown-not-scored -- and listing those here would
    promise a judgement that never happens.
    """
    labels = plan.get("rubric") or {}
    order: list[str] = []
    where: dict[str, list[str]] = {}
    for ph in plan.get("phases", []):
        for name in ph.get("rubric_criteria") or []:
            if name not in where:
                order.append(name)
                where[name] = []
            where[name].append(ph["id"])
    return [{
        "name": name,
        "label": (labels.get(name) or {}).get("label") or name.replace("_", " "),
        "description": score_mod.CRITERIA.get(name, (None, ""))[1],
        "phases": where[name],
    } for name in order]


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
        "rubric": _rubric_preview(d.plan),
    }


def _guard(fn, *args, **kwargs):
    """Domain refusals become 400s carrying the domain's own words."""
    try:
        return fn(*args, **kwargs)
    except prov.SetupRequired as e:
        raise HTTPException(409, str(e)) from e
    except prov.ProviderError as e:
        log.warning("model call failed: %s", e)
        # 503, and the provider's own sentence: it already says which host it tried and
        # says how to start the model servers, which is the whole answer. Without this the runtime
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
    spec = await _guard_async(planner.read_jd, _guard(prov.current), b, text)
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
    q = await _guard_async(planner.propose_question, _guard(prov.current), d.bank, competency,
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


def _detour(plan: dict) -> list:
    """Stage 5's corpus: the plan, the description it was read from, and the policy document.

    FR-32 wants every subsystem to have a kill switch that restores the previous behaviour
    exactly. An empty corpus is that switch -- `_user_questions_turn` falls back to the line it
    always said, because there is no second code path to keep in step.
    """
    if os.environ.get("MOCKINGBIRD_NO_DETOUR"):
        return []
    return detour_mod.corpus(plan)


# An extraction still in flight cannot go into the snapshot, and the Runner is rebuilt from the
# snapshot on every request, so it is held here until the next answer's `_settle` folds it in.
# Without it the observation stop rules never fired in the browser: 0 of ~100 question closes
# over 8 sessions on 07/11/2026, against 93 in-process. One live session, so one entry.
_PENDING: dict[str, asyncio.Future] = {}


def _hold_pending(r) -> None:
    """Called only by the endpoints that create or advance a session. A read-only request
    restoring an older task here could overwrite the one an answer just started."""
    _PENDING.clear()
    if r._pending is not None:
        _PENDING[r.state.session_id] = r._pending


def _live_id() -> str | None:
    try:
        return json.loads(LIVE.read_text(encoding="utf-8")).get("session_id")
    except (OSError, ValueError):
        return None


def _live_running() -> bool:
    try:
        return json.loads(LIVE.read_text(encoding="utf-8")).get("status") == "running"
    except (OSError, ValueError):
        return False


def _recorded_provider(session_id: str | None) -> dict | None:
    """What a session's provenance says served it; None for 1.0 sessions, which were local."""
    if not session_id:
        return None
    try:
        raw = json.loads((SESSIONS / session_id / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return (raw.get("provenance") or {}).get("provider")


def _runner():
    """The snapshot carries its own plan, so nothing here has to know which one was running.
    A session started by the terminal harness resumes here and vice versa."""
    if not LIVE.exists():
        raise HTTPException(404, "no session in progress")
    # The provider the interview started on, never whatever Settings say now (D4).
    p = prov.Metered(_guard(prov.for_session, _recorded_provider(_live_id())))
    try:
        r = resume.read(p, None, LIVE, observe_fn=_extractor(p),
                        similarity=embed.similarity, detour_for=_detour)
    except KeyError as e:
        raise HTTPException(
            409, "this session predates the self-describing snapshot and cannot be resumed "
                 "here; finish it in the terminal or start a new one (%s)" % e) from e
    r._pending = _PENDING.get(r.state.session_id)
    return r


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
        # FR-40 and FR-41: who is reading the answers, and what it has cost, on screen for the
        # whole interview. Neither is a judgement, so neither breaks FR-34.
        # Leaving builds no provider, so the recorded one stands in, in the same shape.
        "provider": (prov.describe(r.provider) if getattr(r, "provider", None)
                     else _recorded_provider(r.state.session_id)),
        "usage": getattr(r.state, "usage", None) or {},
    }


def _warm(p, plan: dict) -> None:
    """Prefill llama.cpp's prefix cache while the candidate reads question one.

    `cli.py` warms before the first question and the browser never did, so every interview sat
    through a cold prefill on turn 0. Measured on qwen with this contract: the warm-up costs
    411 ms against a cold cache and 43 ms against a warm one, so it takes ~370 ms off the
    candidate's first answer. `provider.warmup` still cites ~1,277 ms from log 8.14; that was
    llama-3.2-3b before the model switch, and this configuration does not reproduce it. Deliberately NOT awaited: the wait it removes is the one after
    they have spoken, and they spend far longer than this composing an answer, so the warm
    finishes inside time the candidate was going to spend anyway. Awaiting it here would just
    move the same delay onto the button they press to begin.

    Failures are swallowed on purpose. This is an optimisation; if the model is unreachable the
    real call reports it, and a warm-up that raised here would break starting an interview for
    a reason the candidate cannot act on. When phase 2 lands, the TTS pitch shifter warms here
    too -- its first call is ~14.8 s of numba JIT.
    """
    async def go() -> None:
        try:
            await p.warmup(contract.SYSTEM,
                           contract.render(next(sess.iter_questions(plan))["question"], "", ""))
        except Exception:
            pass

    asyncio.get_running_loop().create_task(go())


@app.post("/api/session/start")
async def session_start(plan_path: str = Body(..., embed=True)) -> dict:
    target = (ROOT / plan_path).resolve()
    if ROOT not in target.parents:
        raise HTTPException(400, "a plan is loaded from inside the project")
    plan = _guard(sess.load_plan, target)
    p = _guard(prov.current)
    model = None
    if prov.is_local(p):
        model = prov.product_model(_guard(prov.served_model))
        if model is None:
            raise HTTPException(
                503, "the model server is not serving %s from %s. %s"
                % (prov.MODEL, prov.MODEL_FILE, prov.START_HINT))
    snap = provenance.snapshot(model, prov.describe(p))
    # FR-44: the voice the interview will speak in, fixed now because Settings lock until it ends.
    try:
        snap["voice"] = speech.describe()
    except (OSError, ValueError, KeyError, RuntimeError):
        snap["voice"] = None
    state = sess.new_session(plan, snap)
    p = prov.Metered(p, state.usage)
    r = resume.Runner(p, plan, state, observe_fn=_extractor(p), similarity=embed.similarity,
                      detour=_detour(plan))
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    # Called for the effect, not the text: `ask` is the only place the rolling history
    # refreshes, and `_pending` derives the line to show.
    await _guard_async(r.ask)
    if prov.is_local(p):
        _warm(p, plan)
    _hold_pending(r)
    return _session_state(r)


@app.get("/api/session")
def session_get() -> dict:
    return _session_state(_runner())


def _recording(r, audio: str | None) -> str | None:
    """The recording this answer was spoken from, or None.

    The path arrives from the browser, so it is checked against this session's own audio
    directory rather than trusted. A path that does not survive the check drops the link
    instead of refusing the answer: a wrong link quietly corrupts a report, while a refused
    submit loses what the candidate just said, and only one of those is recoverable.
    """
    if not audio:
        return None
    target = (ROOT / audio).resolve()
    room = (r.state.dir / "audio").resolve()
    if room not in target.parents or not target.is_file():
        return None
    return audio


@app.post("/api/session/answer")
async def session_answer(text: str = Body(..., embed=True),
                         audio: str | None = Body(None, embed=True),
                         heard: str | None = Body(None, embed=True)) -> dict:
    r = _runner()
    if r.done:
        raise HTTPException(400, "this session has finished")
    heard = (heard or "").strip()[:20000] or None
    out = await _guard_async(r.submit, text, _recording(r, audio), heard)
    if out.closed_question and not r.done and not out.end_session:
        await _guard_async(r.ask)
    # Only on success: a failed request leaves the snapshot as it was, and the task it had
    # already folded in is folded in again by the retry, which is then correct.
    _hold_pending(r)
    return _session_state(r)


@app.post("/api/session/leave")
async def session_leave() -> dict:
    """End the interview where it stands, keeping what was answered for History to score.

    Without this an abandoned interview ran for good: Settings lock while one runs (D4) and
    this page resumes it, so the only way out was answering every remaining question. No
    provider is built, so a stopped model server or a missing key cannot block leaving.
    """
    if not LIVE.exists():
        raise HTTPException(404, "no session in progress")
    try:
        r = resume.read(None, None, LIVE)
    except KeyError as e:
        raise HTTPException(
            409, "this session predates the self-describing snapshot and cannot be left "
                 "here; finish it in the terminal (%s)" % e) from e
    if r.done:
        raise HTTPException(409, "this interview has already finished")
    r.leave()
    held = _PENDING.pop(r.state.session_id, None)
    if held is not None:
        held.cancel()
    return _session_state(r)


LOOPBACK =("127.0.0.1", "::1", "localhost", "testclient")


def _served_remotely(request: Request) -> str | None:
    """Why this instance is being served to someone other than the person at the keyboard, or
    None when it is not.

    Three signals, because the one that matters must not be forgettable. `MOCKINGBIRD_HOSTED`
    is the operator saying so; a caller that is not on loopback says so by existing; and a
    forwarding header says a proxy is in front, which is how a hosted instance would otherwise
    look local to itself. Any one of them is enough.

    The default is local because that is what running this on your own machine is, and the two
    self-evident signals are what stop that default from becoming a lie the day it is served
    without anybody remembering this function.
    """
    if os.environ.get("MOCKINGBIRD_HOSTED"):
        return "this copy is configured as a hosted service"
    for header in ("x-forwarded-for", "x-forwarded-host", "forwarded"):
        if request.headers.get(header):
            return "this copy is being served through a proxy"
    client = (request.client.host if request.client else "") or ""
    if client and client not in LOOPBACK:
        return "this copy is being served over the network"
    return None


def _storage(request: Request) -> dict:
    """Where a candidate's interviews actually are, and what is true about them right now.

    12.9 makes *"this never leaves your machine"* the trust the whole design is spent on, and
    says it counts only while it is true. So nothing here is a written-down reassurance: every
    part is derived, and from **two independent facts** rather than one, because they are
    different exposures and only saying one of them would be a half-truth.

    `answers_leave` is about the model: a remote provider means the words are transmitted to be
    read, wherever the files sit. `served_remotely` is about the deployment: a hosted copy keeps
    the recordings on somebody else's disk, even with a local model doing the reading. The
    interview module runs on one machine and the IELTS module is intended to be hosted, so the
    same build has to be able to say either.
    """
    total, files, recordings = 0, 0, 0
    for f in SESSIONS.rglob("*"):
        if not f.is_file():
            continue
        files += 1
        if f.suffix == ".wav":
            recordings += 1
        try:
            total += f.stat().st_size
        except OSError:
            pass
    conf = prov.configured()
    # Cloud mode, or a "local" server that is not on this machine: either way the words travel.
    remote_model = conf["mode"] == "cloud" or not str(conf["host"]).startswith(
        ("http://127.0.0.1", "http://localhost"))
    hosted = _served_remotely(request)
    return {
        "path": str(SESSIONS),
        "sessions": sum(1 for _ in SESSIONS.glob("*/session.json")),
        "recordings": recordings,
        "files": files,
        "bytes": total,
        # Named, not implied. A reader deciding whether to trust the claim should be able to
        # see which machine and which port answered for it.
        "provider": {"vendor": conf["label"] if remote_model else None, "host": conf["host"],
                     "model": conf["model"], "measured": conf["measured"]},
        "answers_leave": remote_model,
        "served_remotely": hosted is not None,
        "why_hosted": hosted,
        # The summary the interface branches on. Either exposure alone is enough to make the
        # sentence false, so it is the union rather than a third opinion.
        "leaves_machine": remote_model or hosted is not None,
    }


@app.get("/api/storage")
def storage(request: Request) -> dict:
    return _storage(request)


# ------------------------------------------------------------ settings (V1.1_PLAN P2)
def _settings_view() -> dict:
    """Everything the Settings page shows. The key appears only as set or not, and its last four
    characters, never itself (FR-39)."""
    s = settings_mod.load()
    return {
        "settings": s,
        "ack": {"version": settings_mod.ACK_VERSION, "text": settings_mod.ACK_TEXT,
                "current": settings_mod.acknowledged(s)},
        "key": secret.status(),
        "vendors": [{"name": v.name, "label": v.label, "host": prov.host(v.url)}
                    for v in prov.VENDORS.values()],
        "measured": [{"vendor": m["vendor"], "model": m["model"], "label": m.get("label"),
                      "gate": m.get("gate") or {}, "free_tier": m.get("free_tier")}
                     for m in prov.measured_models()],
        "configured": prov.configured(),
        # D4: an interview never changes provider halfway, so nothing changes while one runs.
        "locked": _live_running(),
    }


def _unlocked() -> None:
    if _live_running():
        raise HTTPException(409, "an interview is in progress; settings take effect on the "
                                 "next one, so change them once it has finished")


def _from_this_page(request: Request) -> None:
    # A custom header forces a cross-site page into a CORS preflight this server never
    # answers, on top of the origin check, for the one endpoint that takes a secret.
    if request.headers.get("x-mockingbird") != "1":
        raise HTTPException(403, "refused: the key can only be set from the Settings page")


@app.get("/api/settings")
def settings_get() -> dict:
    return _settings_view()


@app.put("/api/settings")
def settings_put(changes: dict = Body(...)) -> dict:
    _unlocked()
    before = settings_mod.load()
    try:
        after = settings_mod.save(changes)
    except settings_mod.SettingsError as e:
        raise HTTPException(400, str(e)) from e
    if SUPERVISOR is not None and (before["mode"], before["hearing"]) != (after["mode"],
                                                                          after["hearing"]):
        # The other mode may need files and servers this one did not.
        SUPERVISOR.begin(after["mode"], after["hearing"], hardware.nvidia())
    return _settings_view()


# ------------------------------------------------------------ voices (V1.1_PLAN P4)
PREVIEW_LINE = "Tell me about a time you disagreed with a technical decision on your team."


def _voices_view() -> dict:
    """The picker: every voice, whether it is here, whether it can speak on this computer, and
    which one will actually speak with Settings as they are."""
    from app import piper
    speaks = speech.lfm3_speaks()
    speaking, fallback = speech.resolve()
    rows = []
    for v in speech.voices():
        lfm3_voice = v["engine"] == "lfm3"
        rows.append({
            "id": v["id"], "label": v["label"], "engine": v["engine"], "gender": v["gender"],
            "licence": v["licence"], "noncommercial": bool(v.get("noncommercial")),
            "size": v.get("size"), "installed": lfm3_voice or piper.installed(v["id"]),
            "usable": speaks if lfm3_voice else True,
            "why_not": None if (speaks or not lfm3_voice) else
            "needs the voice model on a GPU; on this computer's processor it is too slow to speak",
        })
    return {"voices": rows, "selected": settings_mod.load()["voice"],
            "default": speech.default_voice(), "speaking": speaking, "fallback": fallback,
            "managed": SUPERVISOR is not None,
            "download": SUPERVISOR.status().get("voice_download") if SUPERVISOR else None}


@app.get("/api/voices")
def voices_get() -> dict:
    return _voices_view()


@app.post("/api/voices/{voice_id}/download")
def voice_download(voice_id: str) -> dict:
    from app import piper
    e = piper.entry(voice_id)
    if e is None:
        raise HTTPException(404, "no voice %r" % voice_id)
    if e["engine"] != "piper":
        raise HTTPException(400, "%s comes with the voice model and needs no download" % e["label"])
    if SUPERVISOR is None:
        raise HTTPException(409, "this copy runs from source: fetch it with `python -m "
                                 "app.download --voice %s`" % voice_id.split(":")[-1])
    SUPERVISOR.fetch_voice(voice_id)
    return _voices_view()


@app.get("/api/voices/{voice_id}/preview")
async def voice_preview(voice_id: str) -> Response:
    """One interview line in that voice, so it can be judged by ear before it is chosen."""
    from app import lfm3, piper
    e = piper.entry(voice_id)
    if e is None:
        raise HTTPException(404, "no voice %r" % voice_id)
    if e["engine"] == "lfm3":
        if not speech.lfm3_speaks():
            raise HTTPException(409, "LFM3 cannot speak in time on this computer's processor")
        speaker = lfm3.Speaker(e["voice"])
    else:
        if not piper.installed(voice_id):
            raise HTTPException(409, "download the %s voice first" % e["label"])
        speaker = piper.speaker(voice_id)
    try:
        samples = await asyncio.to_thread(speaker.say, PREVIEW_LINE)
    except RuntimeError as err:
        raise HTTPException(503, str(err)) from err
    return Response(lfm3.wav_bytes(samples, speaker.rate), media_type="audio/wav")


# ------------------------------------------------------------ first run (V1.1_PLAN P3)
# Handed over by `app/launch.py` when the app runs from an install; None from source, where
# models and servers are fetched and started by hand.
SUPERVISOR = None


def _setup_view() -> dict:
    hw = hardware.describe()
    if SUPERVISOR is None:
        return {"managed": False, "set_up": True, "hardware": hw}
    return {"managed": True, "set_up": SUPERVISOR.is_set_up(), "hardware": hw,
            "sizes": SUPERVISOR.option_sizes(hw["gpu"]), "status": SUPERVISOR.status(),
            "settings": settings_mod.load()}


@app.get("/api/setup")
def setup_get() -> dict:
    return _setup_view()


@app.post("/api/setup")
def setup_post(mode: str = Body(..., embed=True), hearing: bool = Body(True, embed=True)) -> dict:
    if SUPERVISOR is None:
        raise HTTPException(409, "this copy runs from source: fetch the models with "
                                 "`python -m app.download` and start them with "
                                 "`python -m app.servers`")
    if mode == "local" and not hardware.can_run_local():
        raise HTTPException(400, "the model on this computer needs an NVIDIA GPU with 6 GB of "
                                 "memory, and none was found; choose the cloud instead")
    changes = {"mode": mode, "hearing": bool(hearing), "setup_done": True}
    s = settings_mod.load()
    if mode == "cloud" and not s["vendor"]:
        # Preselect the measured free option; the key and the acknowledgement still come first.
        first = next(iter(prov.measured_models()), None)
        if first:
            changes.update(vendor=first["vendor"], model=first["model"])
    try:
        settings_mod.save(changes)
    except settings_mod.SettingsError as e:
        raise HTTPException(400, str(e)) from e
    SUPERVISOR.begin(mode, bool(hearing), hardware.nvidia())
    return _setup_view()


@app.put("/api/settings/key")
def settings_key_put(request: Request, key: str = Body(..., embed=True)) -> dict:
    _from_this_page(request)
    _unlocked()
    try:
        secret.save(key)
    except secret.SecretError as e:
        raise HTTPException(400, str(e)) from e
    return _settings_view()


@app.delete("/api/settings/key")
def settings_key_delete(request: Request) -> dict:
    _from_this_page(request)
    _unlocked()
    secret.clear()
    return _settings_view()


@app.post("/api/settings/test")
def settings_test() -> dict:
    """One short call to what Settings point at, so a wrong key or model shows here rather than
    as the first question of an interview."""
    p = _guard(prov.current)
    if prov.is_local(p):
        model = prov.product_model(_guard(prov.served_model))
        if model is None:
            raise HTTPException(503, "the model server is not serving %s. %s"
                                % (prov.MODEL, prov.START_HINT))
        return {"ok": True, "provider": prov.describe(p)}
    got = _guard(p.ping)
    return {"ok": True, "provider": prov.describe(p), "wall_ms": got["wall_ms"]}


@app.delete("/api/sessions/{session_id}")
def session_delete(session_id: str) -> dict:
    """Delete one interview and everything recorded with it.

    12.9 asks for a working delete button, and the word doing the work is *working*: a product
    that records a candidate's voice and offers no way to remove it has not earned the claim
    above. So this removes the directory whole -- transcript, decisions, the cached report and
    the audio -- and reports what went, rather than deleting quietly.

    A running interview is refused. Deleting the interview currently being conducted would
    leave the runner writing turns into a directory that no longer exists, and "I meant the
    other one" is a likelier click than wanting that. One that finished or was left can go, and
    the live snapshot goes with it so the interview page does not resume a deleted interview.
    """
    d = (SESSIONS / session_id).resolve()
    if SESSIONS.resolve() not in d.parents or not (d / "session.json").exists():
        raise HTTPException(404, "no session %r" % session_id)
    try:
        live = json.loads(LIVE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        live = None
    is_live = isinstance(live, dict) and live.get("session_id") == session_id
    if is_live and live.get("status") == "running":
        raise HTTPException(
            409, "this interview is still running; leave it or finish it before deleting it")

    files = [f for f in d.rglob("*") if f.is_file()]
    gone = {"session_id": session_id, "files": len(files),
            "recordings": sum(1 for f in files if f.suffix == ".wav"),
            "bytes": sum(f.stat().st_size for f in files if f.exists())}
    shutil.rmtree(d)
    if is_live:
        LIVE.unlink(missing_ok=True)
    return gone


def _readable() -> int:
    """Interviews that could be read, whether or not they have been.

    Shown beside the number that have, because the gap is the actionable part: this page is
    only as long as the reports someone has actually built, and building one is a minutes-long
    model pass rather than something a page can do on its own.
    """
    n = 0
    for f in SESSIONS.glob("*/session.json"):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if raw.get("status") == "complete" and any(
                q.get("answers") for q in raw.get("questions") or []):
            n += 1
    return n


@app.get("/api/progress")
def progress() -> dict:
    """The same criteria across every interview that has been read.

    Reads cached reports only. Scoring a session costs a full extraction pass, so rebuilding
    sixty of them to draw a line would be hours of model time; what this shows is what has
    already been built, and it says how many that is.

    **No trend, no percentage improved, no arrow.** The scores come from model extraction, so
    two readings of one interview need not agree, and nothing here has measured by how much.
    Until that noise floor is known, a number claiming improvement would be a number this
    cannot support -- so the criteria are laid out with their denominators and the reader draws
    their own line.
    """
    rows = []
    for f in sorted(SESSIONS.glob("*/report.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not raw.get("rubric"):
            continue
        rows.append(raw)
    rows.sort(key=lambda r: r.get("started_at") or "")

    seen: dict[str, dict] = {}
    for i, raw in enumerate(rows):
        for c in raw["rubric"]:
            entry = seen.setdefault(c["name"], {
                "name": c["name"], "description": c.get("description", ""), "points": []})
            of = c.get("of") or 0
            # `at` is the column, and the session it names is `sessions[at]`. Repeating the id
            # and the date on every point would be the same two facts sixty times over.
            entry["points"].append({
                "at": i, "met": c.get("met", 0), "of": of,
                "rate": round(c.get("met", 0) / of, 3) if of else None,
            })
    return {
        "read": len(rows),
        "readable": _readable(),
        "sessions": [{"session_id": r.get("session_id"), "started_at": r.get("started_at")}
                     for r in rows],
        # Least consistent first: a criterion that moves is the one worth looking at, and
        # alphabetical buried it. Ties break on the name so the order is stable.
        "criteria": sorted(seen.values(),
                           key=lambda e: (-_spread(e["points"]), e["name"])),
    }


def _spread(points: list[dict]) -> float:
    """How far a criterion's rate has moved across the readings there are. Ordering only --
    it is never shown as a figure, because two points cannot support one."""
    rates = [p["rate"] for p in points if p["rate"] is not None]
    return max(rates) - min(rates) if len(rates) > 1 else 0.0


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


def _cache_report(d: Path, payload: dict) -> dict:
    """Keep the built report beside the session it describes.

    Written through a temporary file and replaced atomically, so a reader that arrives mid-write
    sees either the old report or the new one and never a half-written file. A failure to cache
    is not a failure to report: the payload is returned either way.
    """
    try:
        tmp = d / "report.json.tmp"
        tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                       encoding="utf-8", newline="\n")
        tmp.replace(d / "report.json")
    except OSError:
        pass
    return payload


def _report_is_fresh(d: Path) -> dict | None:
    """A cached report, if one exists and no session file has changed since it was written.

    Freshness is decided by mtime against every file in the session directory rather than by
    the session's `status`, because a running session gains answers and a report built from
    four of them must not be served once there are six. Comparing against the newest file
    means anything that appends -- another turn, a re-run, a hand edit -- invalidates it
    without this needing to know which file carries what.
    """
    cached = d / "report.json"
    if not cached.exists():
        return None
    # Example answers are written from the report, not into what it reads.
    newest = max((f.stat().st_mtime for f in d.iterdir()
                  if f.is_file() and f.name not in ("report.json", examples_mod.FILE)
                  and not f.name.endswith(".tmp")), default=0.0)
    if cached.stat().st_mtime < newest:
        return None
    try:
        return json.loads(cached.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _delivery(d: Path) -> dict:
    """How the answers were said, measured from the recordings the turns point at.

    Measured here rather than when each answer was submitted, which is what makes it work on
    sessions recorded before any of this existed. Optional in every direction: a session with
    no audio returns nothing to show, and an install without the voice extra still builds a
    report rather than failing on an import it never needed for text.
    """
    try:
        from app import delivery as delivery_mod
    except ImportError:
        return {}
    try:
        turns = json.loads((d / "transcript.json").read_text(encoding="utf-8"))["turns"]
    except (OSError, ValueError, KeyError):
        return {}
    try:
        return delivery_mod.for_session(turns, ROOT)
    except Exception:
        # A report is worth more than its delivery section. Anything parselmouth objects to on
        # one odd recording must not cost the candidate the scoring that took minutes to build.
        return {}


@app.get("/api/sessions/{session_id}/audio/{name}")
def session_audio(session_id: str, name: str) -> FileResponse:
    """One answer's recording, for the report to play back.

    12.9 puts hearing yourself among the highest-value things a speaking report can offer, and
    it costs nothing extra now that a turn names its own recording.

    `name` arrives from a URL, so it is resolved and checked against the session's own audio
    directory rather than joined and trusted. A path parameter matches no slash, which stops the
    obvious escape; this stops the rest, and it is the same check `_recording` makes on the way
    in. Nothing is served from outside one session's audio folder.
    """
    room = (SESSIONS / session_id / "audio").resolve()
    target = (room / name).resolve()
    if room not in target.parents or not target.is_file():
        raise HTTPException(404, "no recording %r in session %r" % (name, session_id))
    return FileResponse(target, media_type="audio/wav")


def _rubric(rep: score_mod.Report, plan: dict) -> list[dict]:
    """The rubric as data, each criterion carrying the answers that decided it.

    12.9's third layer wants a criterion judgement to name the span of the answer that drove
    it. `score.py` has recorded one per question all along and nothing was sending it, so the
    surface could show 4/6 and never what the four rest on -- which is the half of a scored
    report that makes it disputable rather than authoritative.

    `quote` is null where there is none. The deterministic criteria are detections rather than
    extractions, and putting "found in the answer" inside quotation marks would attribute our
    own sentence to the candidate. `report._quote` draws the same line for the text renderer.
    """
    labels = plan.get("rubric") or {}
    return [{
        "name": name,
        # The plan's own wording. `score.CRITERIA[name][0]` is the observation field the
        # criterion reads, not a label, and sending it put "situation" on the row.
        "label": (labels.get(name) or {}).get("label") or name.replace("_", " "),
        "description": score_mod.CRITERIA[name][1],
        "met": met,
        "of": of,
        "evidence": [{
            "question_id": qs.question_id,
            "question": qs.question,
            "met": qs.met[name],
            "quote": qs.evidence.get(name) if name in qs.quoted else None,
        } for qs in rep.scores if name in qs.met],
    } for name, (met, of) in sorted(rep.totals.items())]


def _switching(recorded: dict | None, conf: dict) -> bool:
    """Would using the configured cloud model send this interview's answers somewhere they
    have not been? (D5)"""
    return conf["mode"] == "cloud" and (
        not recorded or recorded.get("mode") != "cloud"
        or (recorded.get("vendor"), recorded.get("model")) != (conf["vendor"], conf["model"]))


def _session_dir(session_id: str) -> Path:
    """A session folder named by a query string, which unlike a path parameter can carry a
    slash, so the id is checked before it is joined."""
    if not session_id or not all(ch.isalnum() or ch in "-_" for ch in session_id):
        raise HTTPException(404, "no session %r" % session_id)
    d = SESSIONS / session_id
    if not (d / "session.json").exists():
        raise HTTPException(404, "no session %r" % session_id)
    return d


@app.get("/api/sessions/{session_id}/report")
async def session_report(session_id: str, refresh: bool = False, provider: str = "recorded",
                         ack: bool = False) -> dict:
    """Extraction and scoring run here, not during the interview. They are offline work by
    design (the live and assessment channels are separate), so this is slow and deliberate
    rather than something the session view polls.

    Slow enough to be worth keeping: a 14-question interview costs about three and a half
    minutes of extraction and scoring, and re-reading a report is a normal thing to do, so the
    result is cached beside the session. `refresh=true` forces a rebuild.
    """
    d = SESSIONS / session_id
    if not (d / "session.json").exists():
        raise HTTPException(404, "no session %r" % session_id)
    if not refresh:
        hit = _report_is_fresh(d)
        if hit is not None:
            return hit
    raw = json.loads((d / "session.json").read_text(encoding="utf-8"))
    plan = raw.get("plan_snapshot") or {}

    states = [sess.QuestionState(**q) for q in raw.get("questions", [])]
    # FR-31: scored on what the candidate said, as they corrected it after the interview.
    corrected = corrections_mod.apply(states, corrections_mod.load(d))
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
    # D5: scored by the provider that heard it. Rebuilding an old local interview's report must
    # not send its answers to a cloud vendor just because Settings changed since; that takes
    # an explicit request naming the switch, which the page makes only after asking.
    recorded = (raw.get("provenance") or {}).get("provider")
    if provider == "current":
        conf = prov.configured()
        if _switching(recorded, conf) and not ack:
            raise HTTPException(409, "scoring this interview with %s would send its answers "
                                     "there; confirm to continue" % conf["label"])
        p = _guard(prov.current)
    else:
        p = _guard(prov.for_session, recorded)
    p = prov.Metered(p)

    observations = []
    for qs in states:
        if not qs.answers:
            continue
        # Guarded like every other model call here. Unguarded, an unreachable model server came
        # back as an opaque 500 and the page said "Internal Server Error" -- the same failure
        # `/api/session/start` was already fixed for, and the provider's own sentence names the
        # host it tried and how to start it.
        observations.append(await _guard_async(
            observe.observe, p, qs.question_id, qs.question, qs.answers))

    rep = score_mod.build(raw.get("session_id", session_id), observations, criteria_for)
    spoken = _delivery(d)
    text = report_mod.render(rep, questions_asked=len(states),
                             questions_answered=sum(1 for q in states if q.answers),
                             observations=observations, question_states=states,
                             delivery=spoken)
    return _cache_report(d, {
        "session_id": session_id,
        "label": plan.get("label") or raw.get("plan_id"),
        "started_at": raw.get("started_at"),
        "text": text,
        "scored": len(rep.scores),
        "asked": len(states),
        "answered": sum(1 for q in states if q.answers),
        # The rubric as data, so the report can be laid out rather than printed, and each row
        # naming the answers behind its count.
        "rubric": _rubric(rep, plan),
        # Sent as data as well as prose so 12.9's surface can lay it out per answer, and
        # never merged into `rubric`: FR-36 keeps delivery out of the score.
        "delivery": spoken,
        # Who read the interview and who scored it, and what each cost (FR-41, FR-42).
        "provider": recorded or prov.describe(prov.LlamaServer()),
        "scored_by": prov.describe(p),
        "usage": raw.get("usage") or {},
        "scoring_usage": p.usage,
        # Each correction with the original beside it, so a report never hides what was heard.
        "corrections": corrected,
    })


@app.get("/api/sessions/{session_id}/corrections")
def corrections_get(session_id: str) -> dict:
    """Every scored answer, with its recording and what the recogniser heard (FR-31)."""
    d = SESSIONS / session_id
    if not (d / "session.json").exists():
        raise HTTPException(404, "no session %r" % session_id)
    raw = json.loads((d / "session.json").read_text(encoding="utf-8"))
    rows = corrections_mod.review(d, raw, _recorded_turns(d))
    return {"answers": rows, "spoken": sum(r["spoken"] for r in rows),
            "reviewed": corrections_mod.load(d) is not None,
            "report_cached": (d / "report.json").exists(),
            "editable": not (_live_running() and _live_id() == session_id)}


@app.put("/api/sessions/{session_id}/corrections")
def corrections_put(session_id: str, answers: list = Body(..., embed=True)) -> dict:
    d = SESSIONS / session_id
    if not (d / "session.json").exists():
        raise HTTPException(404, "no session %r" % session_id)
    if _live_running() and _live_id() == session_id:
        # FR-35: nothing is edited while it is still being interviewed.
        raise HTTPException(409, "this interview is still running; correct it once it ends")
    raw = json.loads((d / "session.json").read_text(encoding="utf-8"))
    try:
        corrections_mod.save(d, raw, answers)
    except corrections_mod.CorrectionError as e:
        raise HTTPException(400, str(e)) from e
    return corrections_get(session_id)


def _recorded_turns(d: Path) -> list[dict]:
    """The transcript on disk. `_turns` is the live runner's dialogue for the session view;
    this is the finished record, which is what an export copies."""
    try:
        return json.loads((d / "transcript.json").read_text(encoding="utf-8")).get("turns") or []
    except (OSError, ValueError, KeyError):
        return []


def _export_name(session_id: str, report: dict, suffix: str) -> str:
    """Named for the day it was sat, so a folder of these sorts by interview rather than by
    download order."""
    day = (report.get("started_at") or "")[:10] or session_id[:8]
    return "mockingbird-%s-%s.%s" % (day, session_id[-6:], suffix)


@app.get("/api/sessions/{session_id}/export.html")
async def export_html(session_id: str, audio: bool = True) -> Response:
    """One interview as a single file, with its recordings inside it (12.9).

    Everything here is local, so export is the sharing mechanism -- there is no link to send.
    That is what makes self-contained the requirement rather than a nicety: this has to open on
    a machine that never had Mockingbird installed, with the app long gone.

    `audio=false` for a copy that travels by email. It is the same document minus the one thing
    that makes it large, and the document says which it is.
    """
    d = SESSIONS / session_id
    report = await session_report(session_id)
    raw = json.loads((d / "session.json").read_text(encoding="utf-8"))
    page = export_mod.html_document(report, raw, _recorded_turns(d), d, embed_audio=audio)
    return Response(
        content=page, media_type="text/html; charset=utf-8",
        headers={"content-disposition": 'attachment; filename="%s"'
                 % _export_name(session_id, report, "html")})


@app.get("/api/sessions/{session_id}/export.json")
async def export_json(session_id: str) -> Response:
    """The sidecar: the same interview without the presentation, so the export is not a dead
    end. Diffable, re-scorable, and readable by something that is not a browser."""
    d = SESSIONS / session_id
    report = await session_report(session_id)
    raw = json.loads((d / "session.json").read_text(encoding="utf-8"))
    body = export_mod.sidecar(report, raw, _recorded_turns(d))
    return Response(
        content=json.dumps(body, indent=1, ensure_ascii=False),
        media_type="application/json",
        headers={"content-disposition": 'attachment; filename="%s"'
                 % _export_name(session_id, report, "json")})


@app.get("/api/sessions/{session_id}/export.md")
async def export_md(session_id: str) -> Response:
    """FR-22: the report as Markdown, for notes and documents. No recordings."""
    d = _session_dir(session_id)
    report = await session_report(session_id)
    raw = json.loads((d / "session.json").read_text(encoding="utf-8"))
    return Response(
        content=export_mod.markdown_document(report, raw),
        media_type="text/markdown; charset=utf-8",
        headers={"content-disposition": 'attachment; filename="%s"'
                 % _export_name(session_id, report, "md")})


@app.get("/api/compare")
async def compare(a: str, b: str) -> dict:
    """FR-25: two interviews side by side, from their reports as scored. A report not yet
    built is built here by the provider its interview was recorded with (D5), never switched."""
    if a == b:
        raise HTTPException(400, "pick two different interviews to compare")
    sides = []
    for sid in (a, b):
        d = _session_dir(sid)
        report = await session_report(sid)
        sides.append((report, json.loads((d / "session.json").read_text(encoding="utf-8"))))
    return compare_mod.compare(*sides)


def _examples_view(d: Path, raw: dict) -> dict:
    conf = prov.configured()
    recorded = (raw.get("provenance") or {}).get("provider")
    record = examples_mod.view(examples_mod.load(d), raw,
                               corrections_mod.as_changes(corrections_mod.load(d)))
    # D9: offered only when Settings point at a cloud model. Examples already written stay
    # readable after switching back to local.
    offer = None if conf["mode"] != "cloud" else {
        "model": conf["model"], "label": conf["label"], "host": conf["host"],
        "measured": conf["measured"], "switching": _switching(recorded, conf)}
    return {"examples": record, "offer": offer, "most": examples_mod.MOST}


@app.get("/api/sessions/{session_id}/examples")
def examples_get(session_id: str) -> dict:
    d = _session_dir(session_id)
    return _examples_view(d, json.loads((d / "session.json").read_text(encoding="utf-8")))


@app.post("/api/sessions/{session_id}/examples")
async def examples_post(session_id: str, ack: bool = False) -> dict:
    """Write example answers for the weakest scored responses with the configured cloud model.
    An interview whose answers have not been to that model before needs `ack` (D5)."""
    d = _session_dir(session_id)
    if _live_running() and _live_id() == session_id:
        raise HTTPException(409, "this interview is still running; example answers come after")
    raw = json.loads((d / "session.json").read_text(encoding="utf-8"))
    conf = prov.configured()
    if conf["mode"] != "cloud":
        raise HTTPException(409, "example answers are written by a cloud model; choose one in "
                                 "Settings")
    if _switching((raw.get("provenance") or {}).get("provider"), conf) and not ack:
        raise HTTPException(409, "writing example answers with %s would send these answers "
                                 "there; confirm to continue" % conf["label"])
    report = await session_report(session_id)
    items = examples_mod.weakest(report, raw)
    p = prov.Metered(_guard(prov.current))
    try:
        written = await _guard_async(examples_mod.write, p, items)
    except examples_mod.ExampleError as e:
        raise HTTPException(503, str(e)) from e
    examples_mod.save(d, written, prov.describe(p), p.usage)
    return _examples_view(d, raw)


async def _guard_async(fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except prov.SetupRequired as e:
        raise HTTPException(409, str(e)) from e
    except prov.ProviderError as e:
        log.warning("model call failed: %s", e)
        raise HTTPException(503, str(e)) from e
    except (ValueError, IndexError) as e:
        raise HTTPException(400, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\"")) from e


app.include_router(voice.router)


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
        # A page newer than the running server got the app shell here and failed to parse it.
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "This server has no such route. If Mockingbird was just "
                                     "updated, it is still running the old version: restart it.")
        candidate = (UI / path).resolve()
        if path and UI.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(UI / "index.html")
