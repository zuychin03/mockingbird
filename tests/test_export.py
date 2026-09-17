"""The exported copy. 12.9 makes export the sharing mechanism, because everything is local and
there is no link to send -- so what is tested here is that the file is genuinely a copy: it
fetches nothing, it carries its own evidence, and it cannot be made to run what a candidate
said."""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import export  # noqa: E402

TEXT = """HOW IT WENT
==========

  You gave four figures and said how you measured two of them.

EVERY CRITERION
===============

  sets_context        6/6
  specific_detail     2/6
"""

RUBRIC = [
    {"name": "sets_context", "label": "Sets the scene", "description": "said where",
     "met": 1, "of": 2,
     "evidence": [
         {"question_id": "b.1", "question": "Tell me about a time?",
          "met": True, "quote": "We ran checkout on four boxes"},
         {"question_id": "b.2", "question": "And another?", "met": False, "quote": None},
     ]},
    {"name": "specific_detail", "label": "Concrete rather than general",
     "description": "gave a figure", "met": 1, "of": 2,
     "evidence": [
         {"question_id": "b.1", "question": "Tell me about a time?", "met": True, "quote": None},
         {"question_id": "b.2", "question": "And another?", "met": False, "quote": None},
     ]},
]

SESSION = {
    "session_id": "20260101-000000-aaaaaa",
    "plan_id": "swe_general_v2",
    "started_at": "2026-01-01T09:00:00+00:00",
    "status": "complete",
    "provenance": {"model_id": "qwen3-4b-instruct-2507", "quantization": "Q4_K_M",
                   "code_revision": "abc1234", "model_path": None},
}

TURNS = [
    {"index": 0, "question_id": "b.1", "question": "Tell me about a time?",
     "utterance": "We ran checkout on four boxes", "say": "What broke?",
     "at": "2026-01-01T09:01:00+00:00", "audio": "audio/b1-0.wav"},
]


def _report(**over):
    out = {"session_id": SESSION["session_id"], "label": "Mixed round",
           "started_at": SESSION["started_at"], "text": TEXT, "rubric": RUBRIC,
           "asked": 2, "answered": 2, "scored": 2, "delivery": {}}
    out.update(over)
    return out


def _with_audio(tmp_path, blob=b"RIFF0000WAVEfmt "):
    d = tmp_path / SESSION["session_id"]
    (d / "audio").mkdir(parents=True)
    (d / "audio" / "b1-0.wav").write_bytes(blob)
    return d


# --- it has to be a copy, not a view ---------------------------------------------------------

def test_the_document_fetches_nothing(tmp_path):
    """The whole claim of an export is that it opens on a machine that never had this
    installed. One remote stylesheet and it is a view of something instead."""
    d = _with_audio(tmp_path)
    page = export.html_document(_report(), SESSION, TURNS, d)
    assert "http://" not in page and "https://" not in page
    assert "<script" not in page.lower()


def test_the_recording_travels_inside_the_file(tmp_path):
    d = _with_audio(tmp_path, b"RIFF" + b"\x00" * 64)
    delivery = {"answers": [{"question_id": "b.1", "audio": "audio/b1-0.wav", "seconds": 4.0,
                             "articulation_rate": 4.2, "pause_count": 1,
                             "mid_clause_pauses": 0, "pauses": []}]}
    page = export.html_document(_report(delivery=delivery), SESSION, TURNS, d)
    src = re.search(r'src="data:audio/wav;base64,([^"]+)"', page)
    assert src, "no recording was embedded"
    assert base64.b64decode(src.group(1)).startswith(b"RIFF")


def test_a_copy_without_audio_says_that_is_what_it_is(tmp_path):
    """Same document minus the one thing that makes it large. Silently dropping the audio
    would make two very different files look identical."""
    d = _with_audio(tmp_path)
    delivery = {"answers": [{"question_id": "b.1", "audio": "audio/b1-0.wav", "seconds": 4.0,
                             "articulation_rate": 4.2, "pause_count": 0,
                             "mid_clause_pauses": 0, "pauses": []}]}
    page = export.html_document(_report(delivery=delivery), SESSION, TURNS, d,
                                embed_audio=False)
    assert "data:audio/wav" not in page
    assert "left out of this copy" in page


def test_audio_past_the_cap_is_left_out_rather_than_making_a_file_that_will_not_open(tmp_path,
                                                                                     monkeypatch):
    monkeypatch.setattr(export, "AUDIO_CAP", 8)
    d = _with_audio(tmp_path, b"RIFF" + b"\x00" * 64)
    page = export.html_document(_report(), SESSION, TURNS, d)
    assert "data:audio/wav" not in page
    assert "would not have opened" in page


# --- it has to carry its own evidence --------------------------------------------------------

def test_each_criterion_carries_the_words_it_rests_on(tmp_path):
    d = _with_audio(tmp_path)
    page = export.html_document(_report(), SESSION, TURNS, d)
    assert "<q>We ran checkout on four boxes</q>" in page
    assert "Sets the scene" in page


def test_a_detection_is_never_dressed_up_as_a_quotation(tmp_path):
    """`specific_detail` is a regex. Printing "found in the answer" inside quotation marks
    attributes our sentence to the candidate, which is the one thing an evidence panel in a
    file they may forward must not do."""
    d = _with_audio(tmp_path)
    page = export.html_document(_report(), SESSION, TURNS, d)
    assert "measured, not extracted" in page
    assert "<q>Detected" not in page


def test_the_rubric_is_laid_out_once_not_printed_twice(tmp_path):
    d = _with_audio(tmp_path)
    page = export.html_document(_report(), SESSION, TURNS, d)
    assert page.count('class="rubric"') == 1
    # The text report's space-aligned version is replaced, not appended.
    assert "sets_context        6/6" not in page


def test_what_produced_it_travels_with_it(tmp_path):
    """FR-42. A report that cannot say which model and which prompt made it cannot be compared
    to a later one, and "the local model" stops being an answer the first time it is swapped."""
    d = _with_audio(tmp_path)
    page = export.html_document(_report(), SESSION, TURNS, d)
    assert "qwen3-4b-instruct-2507" in page
    assert "Q4_K_M" in page
    # Empty provenance fields are omitted rather than printed as None.
    assert "None" not in page


# --- it must not run what the candidate said -------------------------------------------------

def test_an_answer_cannot_become_markup(tmp_path):
    d = _with_audio(tmp_path)
    hostile = dict(TURNS[0], utterance='<script>alert(1)</script> and "quoted"')
    page = export.html_document(_report(), SESSION, [hostile], d)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_a_hostile_quote_in_the_evidence_is_escaped_too(tmp_path):
    d = _with_audio(tmp_path)
    rubric = [dict(RUBRIC[0], evidence=[
        {"question_id": "b.1", "question": "<img src=x onerror=1>",
         "met": True, "quote": "</q><script>bad()</script>"}])]
    page = export.html_document(_report(rubric=rubric), SESSION, TURNS, d)
    assert "<script>bad()</script>" not in page
    assert "<img src=x" not in page


# --- the sidecar -----------------------------------------------------------------------------

def test_the_sidecar_is_the_same_interview_without_the_presentation():
    got = export.sidecar(_report(), SESSION, TURNS)
    assert got["rubric"] == RUBRIC
    assert got["provenance"]["model_id"] == "qwen3-4b-instruct-2507"
    assert got["turns"][0]["utterance"] == "We ran checkout on four boxes"
    assert got["turns"][0]["said"] == "What broke?"


def test_the_sidecar_carries_no_judgement_fields_from_the_turn():
    """`ok`, the guard names and the posterior are the decision record. They are not part of
    what the candidate is given, in the app or in a file they can forward."""
    turn = dict(TURNS[0], ok=False, guards=["extra-sentences-dropped"], act="probe")
    got = export.sidecar(_report(), SESSION, [turn])
    assert set(got["turns"][0]) == {"index", "question_id", "question", "utterance", "said", "at"}
