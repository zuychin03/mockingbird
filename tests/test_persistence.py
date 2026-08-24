"""Section 8's three files, read back rather than merely written.

`session.py` records why local files were chosen: the reference project lost every completed
interview for the life of a feature to a silent body-size limit. Nothing in this repo read a
transcript back either, so the same class of failure -- writes that succeed and produce
unusable data -- would have been just as invisible here.

Every test below round-trips: write with the real runner, re-read from disk, compare.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import session  # noqa: E402
from app.runner import Runner  # noqa: E402
from test_runner import PLAN, ScriptedProvider, d  # noqa: E402


def played(decisions, utterances, tmp_path):
    session.SESSIONS = tmp_path / "sessions"
    state = session.new_session(PLAN)
    r = Runner(ScriptedProvider(decisions), PLAN, state)

    async def go():
        await r.ask()
        for u in utterances:
            out = await r.submit(u)
            if out.closed_question and not r.done:
                await r.ask()

    asyncio.run(go())
    session.checkpoint(state)
    return state


def full(tmp_path):
    return played([d("probe", "More?"), d("advance", "Thanks."), d("advance", "Good.")],
                  ["short", "fuller", "the second answer"], tmp_path)


def read(state, name):
    return json.loads((state.dir / name).read_text(encoding="utf-8"))


def test_transcript_round_trips_every_turn(tmp_path):
    state = full(tmp_path)
    turns = read(state, "transcript.json")["turns"]
    assert len(turns) == len(state.turns) == 3
    for saved, live in zip(turns, state.turns):
        assert saved["utterance"] == live.utterance
        assert saved["act"] == live.act
        assert saved["say"] == live.say
        assert saved["guards"] == live.guards


def test_the_utterances_survive_verbatim(tmp_path):
    """Scoring happens against these later. A lossy write is a silently wrong score."""
    state = full(tmp_path)
    turns = read(state, "transcript.json")["turns"]
    assert [t["utterance"] for t in turns] == ["short", "fuller", "the second answer"]


def test_session_file_carries_status_and_the_plan_snapshot(tmp_path):
    state = full(tmp_path)
    meta = read(state, "session.json")
    assert meta["session_id"] == state.session_id
    assert meta["turn_count"] == 3
    assert meta["status"] == state.status
    assert meta["plan_snapshot"] == PLAN, "editing a plan must not rewrite past sessions"
    assert len(meta["questions"]) == len(state.questions)


def test_every_decision_line_is_independently_parseable(tmp_path):
    """One truncated line must not cost the other turns -- that is why it is jsonl."""
    state = full(tmp_path)
    lines = (state.dir / "decisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    for line in lines:
        rec = json.loads(line)
        assert rec["prompt"] and rec["act"]
        assert "wall_ms" in rec and "prompt_tokens" in rec


def test_the_prompt_is_stored_so_a_turn_can_be_replayed(tmp_path):
    state = full(tmp_path)
    first = json.loads(
        (state.dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert PLAN["phases"][0]["questions"][0] in first["prompt"]
    assert "short" in first["prompt"], "the utterance must be in the prompt to replay it"


def test_a_checkpoint_overwrites_rather_than_appends(tmp_path):
    """Called at every question boundary, so a growing file would be a slow leak."""
    state = full(tmp_path)
    before = (state.dir / "transcript.json").read_text(encoding="utf-8")
    session.checkpoint(state)
    session.checkpoint(state)
    assert (state.dir / "transcript.json").read_text(encoding="utf-8") == before


def test_files_are_written_with_lf_endings(tmp_path):
    """These are diffed in review and read on other machines."""
    state = full(tmp_path)
    for name in ("session.json", "transcript.json", "decisions.jsonl"):
        assert b"\r\n" not in (state.dir / name).read_bytes(), name


# ------------------------- the live harness's own state (log 8.19)
def test_the_live_harness_saves_every_field_the_runner_carries():
    """`focus_used` was missed, so a live session silently lost the focus rotation every
    turn while it worked in-process. The next added field must not be able to do that."""
    import ast
    import inspect
    import textwrap
    from app.runner import Runner

    src = (Path(__file__).resolve().parent.parent / "tools" / "live_candidate.py").read_text(
        encoding="utf-8")
    saved = set(re.findall(r'"(\w+)":', src.split("def save")[1].split("def restore")[0]))

    tree = ast.parse(textwrap.dedent(inspect.getsource(Runner.__init__)))
    attrs = {n.attr for n in ast.walk(tree)
             if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)}

    # Rebuilt from the plan or the provider on every restore, so they carry nothing.
    # `_pending` is an in-flight extraction task and MUST NOT cross a process boundary --
    # `settle()` is what makes its result durable, as `seen` and `stalls`.
    # `speech` is configuration, not turn state: it is derived from the loaded model.
    rebuilt = {"provider", "plan", "state", "questions", "history", "pace",
               "observe_fn", "_pending", "speech"}
    missing = attrs - rebuilt - saved
    assert not missing, "live_candidate.save() does not persist: %s" % sorted(missing)


# ------------------------- source hygiene (log 5, 8.18, 9.7)
def _sources(root):
    """app, tests AND tools: the fourth occurrence of this bug was in `tools/`, which an
    earlier version of this check did not look at."""
    return [f for d in ("app", "tests", "tools") for f in (root / d).rglob("*.py")
            if "__pycache__" not in f.parts]

def test_no_source_file_contains_a_stray_control_byte():
    """Three times now, a shell heredoc has eaten one level of escaping and written a literal
    control byte where an escape was meant: a NUL for a null, a BACKSPACE (0x08) where a regex
    word boundary was intended -- which made the pattern silently match nothing -- and a real
    newline inside a string literal. The first two are INVISIBLE IN A DIFF and the code still
    imports, so nothing catches them but their behaviour.
    """
    root = Path(__file__).resolve().parent.parent
    allowed = {9, 10}                       # tab, newline
    bad = []
    for f in _sources(root):
        for c in set(f.read_bytes()):
            if c < 32 and c not in allowed:
                bad.append("%s: 0x%02x" % (f.relative_to(root), c))
    assert not bad, bad


def test_no_source_file_has_windows_line_endings():
    root = Path(__file__).resolve().parent.parent
    crlf = bytes([13, 10])
    bad = [str(f.relative_to(root)) for f in _sources(root) if crlf in f.read_bytes()]
    assert not bad, bad


def test_the_application_package_does_not_reach_outside_itself_for_imports():
    """`app/focus.py` and `app/observe.py` imported `depth_signals` by pushing `tools/` onto
    `sys.path`, so the module resolved only once something else had already done it. The full
    suite passed and `pytest tests/test_guards.py` alone did not, which is the failure mode
    where a green run stops being evidence.
    """
    root = Path(__file__).resolve().parent.parent
    bad = [str(f.relative_to(root)) for f in (root / "app").rglob("*.py")
           if "__pycache__" not in f.parts and "sys.path" in f.read_text(encoding="utf-8")]
    assert not bad, "product code mutates sys.path: %s" % bad
