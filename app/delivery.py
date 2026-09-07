"""How an answer was delivered, measured from the waveform.

**These are observations and never score contributors (FR-36).** They are the measurements most
contaminated by ASR error and most biased against non-native speakers, which is the whole reason
the requirement singles them out. Nothing here returns a grade, and the report is expected to
show these beside a score rather than inside one.

**It works without a transcript, and that is the point (11.5).** Every fluency figure below comes
off the intensity and pitch contours, so none of 11.4's recognition problems reach it: a candidate
whose accent the recogniser mangles still gets accurate speech-rate and pause figures. Word count
is the single exception and it is optional -- pass it or don't.

Two numbers in here are research settings rather than taste, and both are easy to get wrong:

* **A pause is 200 ms, not the 100 ms most tools default to.** L2 fluency research found 200 ms
  best predicted proficiency on monologic tasks, which is what an interview answer is.
* **Syllables are intensity peaks flanked by a 2 dB dip, with unvoiced peaks discarded** -- De Jong
  and Wempe's method (Behavior Research Methods, 2009), which agrees with hand annotation about
  85-90% of the time. It is not a phoneme recogniser and does not need to be.

The differentiator is `mid_clause`, and it is a heuristic: see `_reset_semitones`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import parselmouth

PAUSE_MIN = 0.20        # 11.5, and deliberately not the common 0.10
SILENCE_DB = -25.0      # below the 99th-percentile intensity; Praat's own convention
DIP_DB = 2.0            # De Jong and Wempe's minimum dip flanking a syllable nucleus
PITCH_FLOOR = 60.0
PITCH_CEILING = 500.0
INTENSITY_PITCH = 50.0  # minimum pitch for the intensity contour, not for pitch tracking
TIME_STEP = 0.016
# Praat measures intensity over a Gaussian window of 3.2 / minimum_pitch, so a frame at the edge
# of a silence still contains speech and reads loud. Uncorrected, a true 500 ms gap measures
# ~430 ms and the 200 ms threshold above is really firing at ~270 ms, which quietly loses the
# short hesitations that are the most diagnostic ones. `tests/test_delivery.py` pins the
# correction against gaps of known length.
INTENSITY_WINDOW = 3.2 / INTENSITY_PITCH

# A pitch reset this large across a pause reads as a clause boundary. Boundary resets in English
# run 2-4 semitones; the threshold sits below that band so a clear reset is not missed, and the
# measured value is reported alongside so a reader is never asked to trust the label alone.
RESET_ST = 1.5

# Below this share of voiced frames there is no speech to describe. Conversational English runs
# well above half; a noise floor sits at essentially zero, so the threshold is nowhere near
# anything real and exists only to separate an answer from a dead microphone.
VOICED_MIN = 0.10


@dataclass
class Pause:
    at: float               # seconds from the first sound, not from the start of the file
    seconds: float
    reset_st: float | None  # pitch reset across it; None when either side is unvoiced
    mid_clause: bool


@dataclass
class Delivery:
    """One answer's delivery. Every duration is in seconds and excludes leading and trailing
    silence, which is recording, not speech -- see `_bounds`."""

    seconds: float = 0.0
    speaking_seconds: float = 0.0
    syllables: int = 0
    speech_rate: float = 0.0            # syllables per second including pauses
    articulation_rate: float = 0.0      # syllables per second of actual phonation
    words: int | None = None
    wpm: float | None = None
    pauses: list[Pause] = field(default_factory=list)
    pause_seconds: float = 0.0
    mean_run_syllables: float = 0.0
    pitch_median_hz: float | None = None
    pitch_range_st: float | None = None
    intensity_db: float | None = None
    # Recorded because 11.5 lists them, not interpreted: jitter, shimmer and HNR are clinical
    # voice-quality measures and carry no interview feedback anyone can act on.
    jitter: float | None = None
    shimmer: float | None = None
    hnr_db: float | None = None
    why: str | None = None              # why the answer could not be measured, if it could not

    @property
    def mid_clause_pauses(self) -> int:
        return sum(1 for p in self.pauses if p.mid_clause)

    @property
    def mid_clause_share(self) -> float | None:
        return self.mid_clause_pauses / len(self.pauses) if self.pauses else None

    def summary(self) -> dict:
        """What a session records. Flat and JSON-safe, because it is written beside the turn."""
        return {
            "seconds": round(self.seconds, 2),
            "speaking_seconds": round(self.speaking_seconds, 2),
            "syllables": self.syllables,
            "speech_rate": round(self.speech_rate, 2),
            "articulation_rate": round(self.articulation_rate, 2),
            "words": self.words,
            "wpm": round(self.wpm, 1) if self.wpm is not None else None,
            "pause_count": len(self.pauses),
            "pause_seconds": round(self.pause_seconds, 2),
            "mean_run_syllables": round(self.mean_run_syllables, 2),
            "mid_clause_pauses": self.mid_clause_pauses,
            "mid_clause_share": (round(self.mid_clause_share, 3)
                                 if self.mid_clause_share is not None else None),
            "pauses": [{"at": round(p.at, 2), "seconds": round(p.seconds, 2),
                        "reset_st": round(p.reset_st, 2) if p.reset_st is not None else None,
                        "mid_clause": p.mid_clause} for p in self.pauses],
            "pitch_median_hz": (round(self.pitch_median_hz, 1)
                                if self.pitch_median_hz is not None else None),
            "pitch_range_st": (round(self.pitch_range_st, 2)
                               if self.pitch_range_st is not None else None),
            "intensity_db": round(self.intensity_db, 1) if self.intensity_db is not None else None,
            "jitter": round(self.jitter, 4) if self.jitter is not None else None,
            "shimmer": round(self.shimmer, 4) if self.shimmer is not None else None,
            "hnr_db": round(self.hnr_db, 1) if self.hnr_db is not None else None,
            "why": self.why,
        }


def _bounds(db: np.ndarray, floor: float) -> tuple[int, int] | None:
    """The first and last sounding frame.

    Everything is measured between these. A recording starts when the button is pressed and runs
    700 ms past the release (12.6's tail), so without trimming every answer ends in a long
    "pause" that is the interface, not the candidate.
    """
    sounding = np.flatnonzero(db > floor)
    return (int(sounding[0]), int(sounding[-1])) if len(sounding) else None


def _reset_semitones(f0: np.ndarray, t: np.ndarray, before: float, after: float,
                     window: float = 0.30) -> float | None:
    """Pitch reset across a pause, in semitones.

    This is the differentiator 11.5 asks for, and it is a prosodic heuristic rather than a
    measurement. A clause boundary in English is normally marked by a fall and then a reset --
    F0 jumps back up to start the next clause -- while a hesitation in the middle of a clause
    resumes at about the pitch it left off. So the reset is the signal, and its size is reported
    with the label so the label can be argued with.

    **Its agreement with human judgement is unmeasured on this data.** The syllable method above
    carries a published 85-90%; this carries nothing of the sort, and it should be validated
    against annotated pauses before any report leans on it hard.
    """
    lhs = (t >= before - window) & (t < before) & (f0 > 0)
    rhs = (t > after) & (t <= after + window) & (f0 > 0)
    if lhs.sum() < 3 or rhs.sum() < 3:
        return None
    return float(12.0 * np.log2(np.median(f0[rhs]) / np.median(f0[lhs])))


def _voice_quality(snd: parselmouth.Sound) -> tuple[float | None, float | None, float | None]:
    """Jitter, shimmer, HNR. Guarded as one unit: they all need a periodic point process, and
    on a short or largely unvoiced answer Praat raises rather than returning nothing."""
    try:
        from parselmouth.praat import call

        point = call(snd, "To PointProcess (periodic, cc)", PITCH_FLOOR, PITCH_CEILING)
        jitter = call(point, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3)
        shimmer = call([snd, point], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6)
        h = call(snd, "To Harmonicity (cc)", 0.01, PITCH_FLOOR, 0.1, 1.0)
        values = np.asarray(h.values).ravel()
        voiced = values[values > -200]      # Praat's sentinel for an unvoiced frame
        hnr = float(voiced.mean()) if len(voiced) else None
    except Exception:
        return None, None, None
    ok = lambda v: None if v is None or not np.isfinite(v) else float(v)  # noqa: E731
    return ok(jitter), ok(shimmer), hnr


def analyse(samples: np.ndarray, rate: int, words: int | None = None) -> Delivery:
    """Measure one answer. `words` is optional and only feeds words-per-minute."""
    x = np.asarray(samples, dtype="float64").ravel()
    if len(x) < rate // 2:
        return Delivery(why="the answer is too short to measure")
    if not np.any(x):
        return Delivery(why="the recording is silent")

    snd = parselmouth.Sound(x, sampling_frequency=rate)
    intensity = snd.to_intensity(minimum_pitch=INTENSITY_PITCH, time_step=TIME_STEP)
    db = np.asarray(intensity.values).ravel()
    times = np.asarray(intensity.xs()).ravel()
    if len(db) < 3:
        return Delivery(why="the answer is too short to measure")

    # Relative to the 99th percentile rather than the maximum: one cough or a chair scrape sets
    # the maximum and drags the threshold above the speech with it.
    floor = max(float(np.percentile(db, 99)) + SILENCE_DB, float(db.min()))
    span = _bounds(db, floor)
    if span is None:
        return Delivery(why="no speech was found above the silence threshold")
    lo, hi = span
    db, times = db[lo:hi + 1], times[lo:hi + 1]
    start = float(times[0])
    total = float(times[-1] - times[0])
    if total <= 0:
        return Delivery(why="the answer is too short to measure")

    pitch = snd.to_pitch(time_step=0.01, pitch_floor=PITCH_FLOOR, pitch_ceiling=PITCH_CEILING)
    f0 = np.asarray(pitch.selected_array["frequency"]).ravel()
    pt = np.asarray(pitch.xs()).ravel()

    gaps = _pauses(db, times, floor)
    pauses = []
    for a, b in gaps:
        reset = _reset_semitones(f0, pt, a, b)
        pauses.append(Pause(at=a - start, seconds=b - a, reset_st=reset,
                            mid_clause=reset is None or reset < RESET_ST))

    # The silence threshold is relative, so a recording of nothing but room noise has its own
    # 99th percentile and every frame reads as "sounding". Voicing is the check that does not
    # move with the gain: speech is voiced much of the time and a noise floor is voiced never.
    # Without this, a muted microphone produced a delivery report with a plausible duration.
    in_span = (pt >= times[0]) & (pt <= times[-1])
    if in_span.sum() and (f0[in_span] > 0).mean() < VOICED_MIN:
        return Delivery(why="no voiced speech was found in the recording")

    nuclei = _syllables(db, times, floor, f0, pt)
    if not nuclei:
        return Delivery(why="no syllables could be found in the recording")
    pause_total = float(sum(p.seconds for p in pauses))
    speaking = max(total - pause_total, 1e-6)

    d = Delivery(
        seconds=total,
        speaking_seconds=speaking,
        syllables=len(nuclei),
        speech_rate=len(nuclei) / total,
        articulation_rate=len(nuclei) / speaking,
        words=words,
        wpm=(words / speaking * 60.0) if words else None,
        pauses=pauses,
        pause_seconds=pause_total,
        # Runs are the stretches between pauses, so there is always one more run than pause.
        mean_run_syllables=len(nuclei) / (len(pauses) + 1),
    )

    voiced = f0[(f0 > 0) & (pt >= times[0]) & (pt <= times[-1])]
    if len(voiced) >= 12:
        d.pitch_median_hz = float(np.median(voiced))
        # Semitones between the 10th and 90th percentile, not min to max: F0 tracking throws
        # octave errors and the extremes are where they land.
        lo_hz, hi_hz = np.percentile(voiced, [10, 90])
        d.pitch_range_st = float(12.0 * np.log2(hi_hz / lo_hz))
    d.intensity_db = float(db[db > floor].mean())
    d.jitter, d.shimmer, d.hnr_db = _voice_quality(snd)
    return d


def _pauses(db: np.ndarray, times: np.ndarray, floor: float) -> list[tuple[float, float]]:
    """Silent stretches of at least `PAUSE_MIN`, as (start, end) in file time.

    A run of k quiet frames spans k frames, not k-1 gaps between their centres, and the window
    smear above is added back at both ends. Both corrections push the same way -- without them
    every pause reads short, and the ones lost are the brief mid-clause hesitations.
    """
    quiet = db <= floor
    pad = INTENSITY_WINDOW / 2.0
    out: list[tuple[float, float]] = []
    i = 0
    while i < len(quiet):
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(quiet) and quiet[j + 1]:
            j += 1
        a = float(times[i]) - TIME_STEP / 2.0 - pad
        b = float(times[j]) + TIME_STEP / 2.0 + pad
        if b - a >= PAUSE_MIN:
            out.append((a, b))
        i = j + 1
    return out


def _syllables(db: np.ndarray, times: np.ndarray, floor: float,
               f0: np.ndarray, pt: np.ndarray) -> list[float]:
    """Syllable nuclei by De Jong and Wempe: intensity peaks above the silence threshold, each
    separated from the last by a dip of at least `DIP_DB`, and voiced.

    The dip is what stops a single long vowel counting several times, and the voicing check is
    what stops a fricative burst counting at all.
    """
    peaks = [i for i in range(1, len(db) - 1)
             if db[i] > db[i - 1] and db[i] >= db[i + 1] and db[i] > floor]
    kept: list[float] = []
    last = None
    for i in peaks:
        if last is not None and db[last:i + 1].min() > min(db[last], db[i]) - DIP_DB:
            # No real dip since the last nucleus: the same syllable still ringing.
            if db[i] > db[last]:
                kept[-1] = float(times[i])
                last = i
            continue
        near = np.abs(pt - times[i])
        if len(near) and f0[int(np.argmin(near))] > 0:
            kept.append(float(times[i]))
            last = i
    return kept


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as w:
        rate, n = w.getframerate(), w.getnframes()
        raw = np.frombuffer(w.readframes(n), dtype="<i2")
    return raw.astype(np.float32) / 32768.0, rate


def for_session(turns: list[dict], root: Path) -> dict:
    """Measure every answer in a session that was spoken aloud.

    Computed when the report is built rather than when the answer was given. The turn already
    names its recording, so the measurement can be made once, late, and **retroactively for
    sessions recorded before this existed** -- which storing it at submit time could not do. At
    150-220x realtime it costs a few seconds against a report build that spends minutes on
    extraction and scoring, so it is not worth a cache of its own.

    Totals are recomputed from the parts, never averaged from the per-answer figures: a mean of
    rates weights a four-second answer the same as a ninety-second one.
    """
    answers, syllables, speaking, words = [], 0, 0.0, 0
    pauses, mid = 0, 0
    for t in turns:
        rel = t.get("audio")
        if not rel:
            continue
        path = root / rel
        try:
            x, rate = _read_wav(path)
        except (OSError, EOFError, ValueError):
            continue
        said = len((t.get("utterance") or "").split()) or None
        d = analyse(x, rate, words=said)
        answers.append({"question_id": t.get("question_id"), "audio": rel, **d.summary()})
        if d.why:
            continue
        syllables += d.syllables
        speaking += d.speaking_seconds
        words += said or 0
        pauses += len(d.pauses)
        mid += d.mid_clause_pauses

    measured = [a for a in answers if not a["why"]]
    return {
        "answers": answers,
        "spoken": len(measured),
        "articulation_rate": round(syllables / speaking, 2) if speaking else None,
        "wpm": round(words / speaking * 60.0, 1) if speaking and words else None,
        "pause_count": pauses,
        "mid_clause_pauses": mid,
        "mid_clause_share": round(mid / pauses, 3) if pauses else None,
        "speaking_seconds": round(speaking, 1),
    }
