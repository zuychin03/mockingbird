"""Delivery metrics, against signals whose answer is known in advance.

Real speech cannot test this: nobody knows how many syllables are in a recording or exactly where
its pauses fall, so a test written against one only asserts that today's output equals today's
output. Everything below is built from a buzz with a chosen modulation rate and gaps of a chosen
length, so a wrong number is a wrong number rather than a changed one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("parselmouth", reason="the voice extra is optional")

from app import delivery  # noqa: E402

RATE = 16000


def buzz(seconds: float, f0: float = 120.0, syllables_per_second: float = 3.5) -> np.ndarray:
    """Voiced, and modulated so the intensity contour has countable peaks.

    Harmonics rather than a sine because the syllable count discards unvoiced peaks, and Praat
    finds no pitch in a pure tone's single partial often enough to make the test flaky.
    """
    t = np.arange(int(seconds * RATE)) / RATE
    sig = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 12))
    env = 0.5 + 0.5 * np.abs(np.sin(2 * np.pi * (syllables_per_second / 2) * t))
    return (sig / np.abs(sig).max() * env * 0.6).astype(np.float32)


def hush(seconds: float) -> np.ndarray:
    """Not digital zero: a real room has a noise floor, and a silence detector that only works
    on perfect zeros is not one."""
    rng = np.random.default_rng(0)
    return rng.normal(0, 1e-4, int(seconds * RATE)).astype(np.float32)


# --- pauses ---------------------------------------------------------------------------------

def test_pauses_are_found_where_they_are_and_last_as_long_as_they_do():
    x = np.concatenate([buzz(2.0), hush(0.5), buzz(2.0), hush(0.8), buzz(2.0)])
    d = delivery.analyse(x, RATE)

    assert len(d.pauses) == 2
    assert [p.seconds for p in d.pauses] == pytest.approx([0.5, 0.8], abs=0.05)
    # Timed from the first sound, so a pause is where the candidate hears it, not where it sits
    # in a file that began when they pressed the button.
    assert [p.at for p in d.pauses] == pytest.approx([2.0, 4.5], abs=0.1)


def test_a_gap_under_two_hundred_milliseconds_is_not_a_pause():
    """11.5 sets the floor at 200 ms against the 100 ms most tools default to, because L2
    fluency research found it the better predictor on monologic tasks."""
    assert delivery.PAUSE_MIN == 0.20
    x = np.concatenate([buzz(2.0), hush(0.12), buzz(2.0)])
    assert delivery.analyse(x, RATE).pauses == []


def test_a_gap_just_over_the_floor_is_a_pause():
    """The pair with the test above. Praat measures intensity over a window, so an uncorrected
    reading loses ~75 ms per gap and this 0.26 s pause would fall under the floor and vanish --
    silently, and only for the short hesitations that matter most."""
    x = np.concatenate([buzz(2.0), hush(0.26), buzz(2.0)])
    d = delivery.analyse(x, RATE)
    assert len(d.pauses) == 1
    assert d.pauses[0].seconds == pytest.approx(0.26, abs=0.05)


def test_the_recording_tail_is_not_counted_as_a_pause():
    """Recording starts on the press and runs 700 ms past the release (12.6), and my own rig
    left twelve seconds of it. That silence is the interface, not the candidate."""
    x = np.concatenate([hush(1.0), buzz(3.0), hush(4.0)])
    d = delivery.analyse(x, RATE)
    assert d.pauses == []
    assert d.seconds == pytest.approx(3.0, abs=0.2), "duration must span the speech, not the file"


# --- rates ----------------------------------------------------------------------------------

def test_syllables_track_the_rate_they_were_modulated_at():
    """Not an exact count: De Jong and Wempe's method agrees with hand annotation 85-90% of the
    time, so the assertion is the band that claim supports."""
    d = delivery.analyse(buzz(6.0, syllables_per_second=4.0), RATE)
    assert 18 <= d.syllables <= 30
    assert d.speech_rate == pytest.approx(d.syllables / 6.0, abs=0.2)


def test_articulation_rate_exceeds_speech_rate_when_there_are_pauses():
    """The two differ only by whether pauses count, which is the whole reason both are reported:
    a candidate can speak quickly and still sound slow because they stop so often."""
    x = np.concatenate([buzz(2.0), hush(1.0), buzz(2.0)])
    d = delivery.analyse(x, RATE)
    assert d.articulation_rate > d.speech_rate
    assert d.speaking_seconds == pytest.approx(d.seconds - d.pause_seconds, abs=0.01)


def test_mean_length_of_run_counts_runs_not_pauses():
    """Two pauses make three runs. Off by one here would overstate fluency by a third."""
    x = np.concatenate([buzz(2.0), hush(0.5), buzz(2.0), hush(0.5), buzz(2.0)])
    d = delivery.analyse(x, RATE)
    assert len(d.pauses) == 2
    assert d.mean_run_syllables == pytest.approx(d.syllables / 3.0)


def test_words_per_minute_is_the_one_figure_that_needs_a_transcript():
    """11.5's claim is that fluency survives a recogniser that mangles the candidate's accent,
    so everything else must be computable without one."""
    x = buzz(6.0)
    assert delivery.analyse(x, RATE).wpm is None
    d = delivery.analyse(x, RATE, words=15)
    assert d.wpm == pytest.approx(15 / d.speaking_seconds * 60.0, abs=0.1)
    assert d.syllables == delivery.analyse(x, RATE).syllables, "words must not move anything else"


# --- where the pause falls, which is the differentiator -------------------------------------

def test_a_pitch_reset_across_a_pause_reads_as_a_clause_boundary():
    """11.5's differentiator: where someone pauses matters more than how much. English marks a
    clause boundary with a reset -- F0 jumps back up to start the next clause."""
    x = np.concatenate([buzz(2.0, f0=110.0), hush(0.5), buzz(2.0, f0=155.0)])
    d = delivery.analyse(x, RATE)
    assert len(d.pauses) == 1
    p = d.pauses[0]
    assert p.reset_st == pytest.approx(12 * np.log2(155 / 110), abs=1.0)
    assert not p.mid_clause


def test_resuming_at_the_same_pitch_reads_as_a_hesitation():
    x = np.concatenate([buzz(2.0, f0=120.0), hush(0.5), buzz(2.0, f0=120.0)])
    p = delivery.analyse(x, RATE).pauses[0]
    assert p.reset_st == pytest.approx(0.0, abs=1.0)
    assert p.mid_clause


def test_an_unmeasurable_reset_is_reported_as_such_and_read_as_hesitation():
    """A pause with nothing voiced on one side cannot be classified. It is counted as
    mid-clause, and `reset_st` is None so a reader can tell the guess from the measurement."""
    x = np.concatenate([buzz(2.0), hush(0.5), hush(0.5)])
    for p in delivery.analyse(x, RATE).pauses:
        if p.reset_st is None:
            assert p.mid_clause
            break


# --- refusing to measure what it cannot -----------------------------------------------------

@pytest.mark.parametrize("x, rate", [
    (np.zeros(RATE, dtype=np.float32), RATE),
    (np.zeros(0, dtype=np.float32), RATE),
    (buzz(0.1), RATE),
    (hush(3.0), RATE),
])
def test_unmeasurable_audio_says_why_instead_of_raising(x, rate):
    """These arrive from a live socket. A metric that raises on a silent turn takes the report
    with it, and a silent turn is the most likely turn of all."""
    d = delivery.analyse(x, rate)
    assert d.why, "an unmeasurable answer must say why"
    assert d.syllables == 0 and d.pauses == []


def test_the_summary_survives_json():
    """It is written beside the turn, so anything numpy leaves in it fails at write time --
    after the interview, when the recording is the only copy."""
    x = np.concatenate([buzz(2.0), hush(0.5), buzz(2.0)])
    blob = json.dumps(delivery.analyse(x, RATE, words=12).summary())
    assert json.loads(blob)["pause_count"] == 1
    assert json.loads(blob)["words"] == 12


def test_nothing_here_returns_a_score():
    """FR-36: delivery is reported as observation and never as a score contributor, because it
    is the measurement most biased against non-native speakers. The guard that matters is that
    the scoring path cannot import this at all -- see `test_nfr.py` -- and this is the reminder
    that no field here is a grade.
    """
    fields = delivery.analyse(buzz(3.0), RATE).summary()
    assert not [k for k in fields if any(w in k for w in ("score", "grade", "rating", "band"))]


# --- a whole session, measured from the recordings its turns point at -----------------------

def write(path: Path, x: np.ndarray) -> None:
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def test_only_turns_that_were_spoken_are_measured(tmp_path):
    """A typed answer has no recording, and an interview mixes the two freely."""
    write(tmp_path / "a.wav", buzz(3.0))
    turns = [
        {"question_id": "q1", "utterance": "spoken", "audio": "a.wav"},
        {"question_id": "q2", "utterance": "typed", "audio": None},
        {"question_id": "q3", "utterance": "typed too"},
    ]
    got = delivery.for_session(turns, tmp_path)
    assert got["spoken"] == 1
    assert [a["question_id"] for a in got["answers"]] == ["q1"]


def test_session_totals_are_weighted_by_speaking_time(tmp_path):
    """Recomputed from the parts, never averaged from the per-answer rates. A mean of rates
    would let a two-second answer pull the session figure as hard as a thirty-second one."""
    write(tmp_path / "short.wav", buzz(2.0, syllables_per_second=8.0))
    write(tmp_path / "long.wav", buzz(30.0, syllables_per_second=3.0))
    turns = [{"question_id": "q1", "utterance": "x", "audio": "short.wav"},
             {"question_id": "q2", "utterance": "y", "audio": "long.wav"}]

    got = delivery.for_session(turns, tmp_path)
    rates = [a["articulation_rate"] for a in got["answers"]]
    naive = sum(rates) / 2
    assert got["articulation_rate"] == pytest.approx(min(rates), abs=0.8), (
        "the session rate should sit near the long answer, not between the two")
    assert abs(got["articulation_rate"] - naive) > 0.3, "this is not a mean of the two rates"


def test_a_recording_that_is_gone_costs_its_answer_and_nothing_else(tmp_path):
    """Files get moved, and a report built minutes after an interview must not die of it."""
    write(tmp_path / "there.wav", buzz(3.0))
    turns = [{"question_id": "q1", "utterance": "a", "audio": "missing.wav"},
             {"question_id": "q2", "utterance": "b", "audio": "there.wav"}]
    got = delivery.for_session(turns, tmp_path)
    assert got["spoken"] == 1 and [a["question_id"] for a in got["answers"]] == ["q2"]


def test_a_session_with_nothing_spoken_measures_nothing(tmp_path):
    got = delivery.for_session([{"question_id": "q1", "utterance": "typed"}], tmp_path)
    assert got["spoken"] == 0 and got["answers"] == []
    assert got["articulation_rate"] is None and got["wpm"] is None


# --- how it reads ---------------------------------------------------------------------------

def test_the_report_section_states_that_none_of_it_is_scored():
    """FR-36 in the output, not only in a docstring: a reader who sees numbers under a score
    will assume they contributed to it unless told otherwise."""
    from app import report

    text = chr(10).join(report._delivery_lines({
        "spoken": 2, "speaking_seconds": 40.0, "articulation_rate": 4.2, "wpm": 138.0,
        "pause_count": 17, "mid_clause_pauses": 12, "mid_clause_share": 0.706}))
    assert "not scores" in text
    assert "4.2 syllables per second" in text
    assert "138" in text and "120-150" in text
    assert "12 of 17 were mid-clause" in text


def test_no_delivery_section_when_the_interview_was_typed():
    from app import report

    assert report._delivery_lines({}) == []
    assert report._delivery_lines({"spoken": 0}) == []
