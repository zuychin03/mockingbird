"""Run a session one turn at a time, with a human (or Claude) as the candidate.

Every session measured so far replayed a FIXED list of candidate utterances. That is why
`--pin` exists: an adaptive interviewer and a fixed script desynchronise, and once they do,
every later answer addresses a question that was not asked. The drift is an artefact of the
fixture, and it has been contaminating the results it was meant to produce -- it inflates
`reask` and `clarify`, which then consume budget, which changes the pacing being measured.

Answering live removes the artefact at the source: the answer is a reply to the question the
interviewer actually asked, so there is nothing to drift.

The runner keeps its state in memory and each invocation is a new process, so the small
amount of state that matters is written to disk between turns. It is listed explicitly rather
than pickled: pickling a live object across a code change is how a harness starts lying.

    python tools/live_candidate.py --start
    python tools/live_candidate.py --answer "I'm a backend engineer, four years in."
    python tools/live_candidate.py --status
    python tools/live_candidate.py --script ux_design --data <scratch dir>
    python tools/live_candidate.py --script ux_design --data <dir> --vendor gemini --model M --pace 15

`--script FIELD` sits that field's scripted candidate from internal_docs/FIELD_TEST_SCRIPTS.md
on `data/field_test_plan_<field>.json` in one run, then reports each question's decisions, the
planted gaps followed up and any family crossing. `--data` moves the live file and the session
out of `data/`, so a test never lands in History.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools._console import utf8  # noqa: E402

utf8()

from app import (contract, detour, embed, observe, provenance, provider as prov, secret,
                 resume, session as sess)  # noqa: E402
from app.runner import Runner  # noqa: E402

STATE = ROOT / "data" / "live_session.json"
SCRIPTS = ROOT / "internal_docs" / "FIELD_TEST_SCRIPTS.md"
FOLLOW = ("probe", "reask")
FALLBACK = ["I think that's everything I have on that one.", "That's really all there is to it.",
            "Sorry, I don't have more detail than that.", "Can we move on to the next one?"]


def read_script(field: str, path: Path = SCRIPTS) -> dict[int, dict]:
    """One field's section: {n: {"question", "gap", "lines"}}."""
    script: dict[int, dict] = {}
    inside, n = False, 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("## "):
            inside = raw[3:].strip() == field
            continue
        if not inside:
            continue
        m = re.match(r"### Q(\d+)(.*)", raw)
        if m:
            n = int(m.group(1))
            gap = re.search(r"gap: ([^·]+)", m.group(2))
            script[n] = {"question": "", "gap": gap.group(1).strip() if gap else "", "lines": []}
        elif n and raw.startswith("> "):
            script[n]["question"] = raw[2:].strip()
        elif n and re.match(r"\d+\. ", raw):
            script[n]["lines"].append(raw.split(". ", 1)[1].strip())
    if not script:
        raise KeyError("no script for %r in %s" % (field, path))
    return script


async def sit(r: Runner, script: dict[int, dict], pace: float = 0.0) -> list[dict]:
    """Say each question's lines in order while the interviewer stays on it; fillers after.
    `pace` waits that many seconds before each answer, as a person would: back to back, a turn
    and its extraction exceed a free tier's requests a minute."""
    used: dict[int, int] = {}
    fillers: dict[int, int] = {}
    log: list[dict] = []
    while not r.done:
        n = r.index + 1
        q = script.get(n) or {"question": "", "gap": "", "lines": []}
        if q["question"] and q["question"] != r.current["question"]:
            raise ValueError("Q%d is %r in the plan but %r in the script"
                             % (n, r.current["question"], q["question"]))
        if used.get(n, 0) < len(q["lines"]):
            text, kind = q["lines"][used.get(n, 0)], "script"
            used[n] = used.get(n, 0) + 1
        elif fillers.get(n, 0) < 8:
            # The runner's caps end every question; this bound only stops a runaway driver.
            text, kind = FALLBACK[min(fillers.get(n, 0), len(FALLBACK) - 1)], "filler"
            fillers[n] = fillers.get(n, 0) + 1
        else:
            print("stuck on Q%d, stopping" % n)
            break
        before = len(r.state.turns)
        phase = r.current["phase"]
        await asyncio.sleep(pace)
        out = await r.submit(text)
        line = out.spoken.text
        if out.closed_question and not r.done and not out.end_session:
            line = (line + "  " if line else "") + (await r.ask()).text
        mine = [t for t in r.state.turns[before:] if t.utterance == text] or r.state.turns[-1:]
        t = mine[0]
        log.append({"q": n, "phase": phase, "kind": kind, "said": text, "act": t.act,
                    "guards": t.guards, "reply": line})
        print("Q%-2d %-6s %-8s | %s" % (n, kind, t.act, line[:150]), flush=True)
        await r.settle()
        save(r)
        if out.end_session:
            break
    return log


def report(plan: dict, script: dict[int, dict], log: list[dict]) -> dict:
    """Follow-ups to scripted lines per question, gaps followed up, and family crossings."""
    generated = {g["text"] for g in plan.get("generated", [])}
    rows, caught, crossings = [], 0, []
    for n, q in enumerate(sess.iter_questions(plan), 1):
        mine = [e for e in log if e["q"] == n]
        follow = sum(e["act"] in FOLLOW for e in mine if e["kind"] == "script")
        gap = script.get(n, {}).get("gap", "")
        hit = bool(gap) and bool(mine) and mine[0]["act"] in FOLLOW
        caught += hit
        rows.append({"q": n, "phase": q["phase"], "generated": q["question"] in generated,
                     "gap": gap, "followed": hit, "follow_ups": follow,
                     "acts": [e["act"] for e in mine]})
        print("  Q%-2d %-22s %-4s %-16s %s%s" % (
            n, q["phase"], "gen" if q["question"] in generated else "", gap or "-",
            " ".join(e["act"] for e in mine) or "(not reached)",
            "" if not gap else ("  <- gap followed up" if hit else "  <- GAP MISSED")))
        if q["type"] != "user_questions":
            crossings += [e for e in mine if e["act"] in contract.HALT]
    gaps = sum(1 for q in script.values() if q["gap"])
    print("gaps followed up %d/%d, family crossings %d" % (caught, gaps, len(crossings)))
    return {"rows": rows, "gaps_followed": caught, "gaps": gaps,
            "crossings": [{"q": e["q"], "act": e["act"]} for e in crossings]}


def save(r: Runner) -> None:
    resume.write(r, STATE)


def extractor(p):
    """Plan 1c.5's per-answer extraction, as the runner wants it."""
    async def fn(question_id, question, utterance):
        return await observe.observe(p, question_id, question, [utterance])
    return fn


def restore(p, plan) -> Runner:
    # `plan` is ignored for a snapshot that carries its own, which is what makes a session
    # started here resumable in the browser and the other way round.
    return resume.read(p, None, STATE, observe_fn=extractor(p),
                       similarity=embed.similarity, detour_for=detour.corpus)


def show(r: Runner, line: str) -> None:
    n = len(r.state.turns)
    print("\nINTERVIEWER: %s" % line)
    print("\n[q %d/%d | turn %d | pool %d | follow-ups %d/%d%s]" % (
        min(r.index + 1, len(r.questions)), len(r.questions), n, r.pool,
        r.follow_ups_used, (r.current or {}).get("probe_budget", 0),
        " | AWAITING YOUR REPLY TO AN OFFER" if r.awaiting_skip_offer or r.awaiting_confirm
        else ""))
    if r.state.turns:
        t = r.state.turns[-1]
        print("[hidden: act=%s guards=%s]" % (t.act, ",".join(t.guards) or "-"))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--answer")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--plan")
    ap.add_argument("--script", metavar="FIELD")
    ap.add_argument("--data", type=Path, help="keep the live file and the session here")
    ap.add_argument("--vendor", choices=list(prov.VENDORS),
                    help="a cloud interviewer, with --model and the stored key")
    ap.add_argument("--model")
    ap.add_argument("--pace", type=float, default=0.0, help="seconds before each scripted answer")
    a = ap.parse_args()

    global STATE
    if a.data:
        a.data.mkdir(parents=True, exist_ok=True)
        STATE = a.data / "live_session.json"
        sess.SESSIONS = a.data / "sessions"
    if a.vendor:
        key = secret.load()
        if not key or not a.model:
            print("a cloud interviewer needs --model and a stored key")
            return 2
        p = prov.CloudClient(prov.profile_for(a.vendor, a.model), key)
    else:
        p = prov.LlamaServer()
    plan_path = a.plan or (ROOT / "data" / ("field_test_plan_%s.json" % a.script) if a.script
                           else ROOT / "config" / "interview_swe_general.json")
    plan = sess.load_plan(plan_path)

    if a.start or a.script:
        model = None
        if not a.vendor:
            try:
                model = prov.product_model()
            except prov.ProviderError as e:
                print(e)
                return 1
            if model is None:
                print("the model server is not serving %s. %s" % (prov.MODEL, prov.START_HINT))
                return 1
        state = sess.new_session(plan, provenance.snapshot(model, prov.describe(p), plan))
        print("model %s" % (model["id"] if model else "%s/%s" % (a.vendor, a.model)))
        r = Runner(p, plan, state, observe_fn=extractor(p), similarity=embed.similarity,
                   detour=detour.corpus(plan))
        await p.warmup(contract.for_plan(plan)[0],
                       contract.render(r.current["question"], "", ""))
        spoken = await r.ask()
        save(r)
        show(r, spoken.text)
        if not a.script:
            return 0
        script = read_script(a.script)
        log = await sit(r, script, a.pace)
        result = {"field": a.script, "plan": str(plan_path), "session": r.state.session_id,
                  "status": r.state.status, "opening": spoken.text, "log": log,
                  "report": report(plan, script, log)}
        out = (a.data or ROOT / "data") / ("field_script_%s%s.json"
                                           % (a.script, "." + a.vendor if a.vendor else ""))
        out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8",
                       newline="\n")
        print("session %s %s -> %s" % (r.state.session_id, r.state.status, out))
        return 0

    r = restore(p, plan)

    if a.status:
        print("session %s  %s  q %d/%d  turns %d  pool %d" % (
            r.state.session_id, r.state.status, r.index + 1, len(r.questions),
            len(r.state.turns), r.pool))
        return 0

    if r.done:
        print("session already finished: %s" % r.state.status)
        return 0

    out = await r.submit(a.answer)
    line = out.spoken.text
    if out.closed_question and not r.done and not out.end_session:
        line = (line + "  " if line else "") + (await r.ask()).text
    elif r.done:
        line = line or "That's everything. Thanks for your time."
    save(r)
    show(r, line)
    await r.settle()
    save(r)
    if r.done or out.end_session:
        print("\n=== SESSION %s: %d/%d questions in %d turns ===" % (
            r.state.status.upper(), len(r.state.questions), len(r.questions),
            len(r.state.turns)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except prov.ProviderError as e:
        print("provider error: %s" % e)
        sys.exit(1)
