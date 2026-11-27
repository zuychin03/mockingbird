"""Deterministic depth signals -- the observations a probe decision could rest on.

T1.27 failed because "is there anything worth asking about" is a judgement, and this model
judges badly (§7.10). These are OBSERVATIONS instead: computed in Python, no model, perfectly
reproducible, and each one corresponds to a move a real interviewer makes.

No thresholds or probe rules live here. This module only reports what it finds, so the
question "do these separate a complete answer from an incomplete one" can be asked before any
rule is built on top.
"""

from __future__ import annotations

import functools
import re

from . import fields

# A figure is "verified" when the candidate says how they know it.
_MEASURED = (r"measur|benchmark|profil|trac(e|ed|ing)|logg|logs|monitor|instrument|"
             r"test(ed|ing)?|count(ed)?|track(ed)?|showed|verif|check(ed)?|explain analyze|"
             r"p9\d|percentile|dashboard|metric|a/b|experiment")
MEASURED = re.compile(r"\b(" + _MEASURED + r")\w*", re.I)

# A spelled-out number is only a FIGURE when a unit follows it. Without that, "one layer up",
# "no one else" and "seven years" of service all read as unverified claims, and the focus
# selector asks a candidate how they measured their own job title (log 8.19). Digits count
# alone -- nobody writes "42" incidentally.
_UNITS = (r"%|percent|ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|"
          r"years?|k|m|x|thousand|million|billion|times|requests?|users?|people|engineers?|"
          r"services?|rows?|queries|deploys?|jobs?|gb|mb|kb|tb|a day|an hour|a week")
_SPELLED = (r"one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|"
            r"sixty|seventy|eighty|ninety|hundred|thousand|million")


def _number(units: str, more: str = "") -> re.Pattern:
    unit = "(?:" + units + ")"
    # A field's own units take no "one": "one patient's rhythm changed" names a person.
    extra = (r"|(?:" + _SPELLED.replace("one|", "", 1) + r")\s+(?:" + more + ")") if more else ""
    return re.compile(r"\b(\d+(?:[.,]\d+)?\s*" + unit + r"?|(?:" + _SPELLED + r")\s+" + unit
                      + extra + r")\b", re.I)


NUMBER = _number(_UNITS)


@functools.cache
def patterns(field: str | None = None) -> tuple[re.Pattern, re.Pattern]:
    """NUMBER and MEASURED for a field: software's, with the field's own words added. Software
    and an unknown field get the two above unchanged."""
    f = fields.FIELDS.get(field or fields.SOFTWARE)
    if f is None or not (f.units or f.measured):
        return NUMBER, MEASURED
    return (_number(_UNITS, "|".join(f.units)),
            re.compile(r"\b(" + _MEASURED + "".join("|" + m for m in f.measured) + r")\w*",
                       re.I))


VAGUE = re.compile(
    r"\b(a lot|lots|loads|plenty|quite a few|quite a bit|several|many|most|a bit|a while|"
    r"pretty|fairly|somewhat|kind of|sort of|a fair amount|big|huge|massive|tiny|"
    r"much (?:faster|slower|better|worse|bigger)|way (?:faster|slower|better))\b", re.I)

ASSERTED = re.compile(
    r"\b(it worked|worked (?:out |well|fine)|went (?:well|fine|smoothly)|was (?:great|good|fine|"
    r"better|successful)|no (?:problems|issues)|all good|turned out (?:well|fine)|"
    r"was the right call|it was fine)\b", re.I)

SKIPPED = re.compile(
    r"\b(so we|so i just|and then it|eventually|in the end|ended up|anyway|"
    r"basically (?:we|i)|we just|i just)\b", re.I)

FIRST_SG = re.compile(r"\b(i|my|me|mine)\b", re.I)
FIRST_PL = re.compile(r"\b(we|our|us|ours)\b", re.I)

_DENIAL = re.compile(r"\b(?:never|not|no|without|nobody|none|nothing)\b|n['’]t\b", re.I)


def is_measured(text, field=None):
    """MEASURED, less a match denied in its own clause ("there's no measurement", "our analytics
    didn't track it"): 4 of 466 stored answers (25/11). Pacing only: `observe.deterministic`
    still scores `measurement_stated` with MEASURED, so reports and their cache do not move."""
    t = text or ""
    for m in patterns(field)[1].finditer(t):
        clause = re.split(r"[.!?;,]", t[:m.start()])[-1].split()[-4:]
        if not _DENIAL.search(" ".join(clause)):
            return True
    return False


# A measure stated in so many words, which spends the MEASURE follow-up. Narrower than
# MEASURED, which also credits "checked", "tested", "counted" and "showed": a loose match here
# would skip a follow-up still owed. Over the stored sessions it fired before 3 of 16 MEASURE
# follow-ups, each one asked after a measure had been given (27/11/2026).
_STATED = (r"measur|benchmark|profil(?:ed|ing|er)|monitor(?:ed|ing)?\b|instrument(?:ed|ing)|"
           r"track(?:ed|ing)|metrics?\b|dashboards?\b|p9\d|percentiles?|a/b test")


@functools.cache
def _stated(field: str | None) -> re.Pattern:
    f = fields.FIELDS.get(field or fields.SOFTWARE)
    extra = "".join("|" + re.escape(m) for m in (f.measured if f else ()))
    return re.compile(r"\b(?:" + _STATED + extra + ")", re.I)


def states_measure(text, field=None):
    """A measure named and not denied in its own clause, as `is_measured` reads one."""
    t = text or ""
    for m in _stated(field).finditer(t):
        clause = re.split(r"[.!?;,]", t[:m.start()])[-1].split()[-4:]
        if not _DENIAL.search(" ".join(clause)):
            return True
    return False


def signals(text, field=None):
    """Return {signal_name: count}. Pure function of the text and the field."""
    t = text or ""
    numbers = patterns(field)[0].findall(t)
    measured = is_measured(t, field)
    sg, pl = len(FIRST_SG.findall(t)), len(FIRST_PL.findall(t))
    return {
        # a figure stated with no account of how it was established
        "unverified": len(numbers) if (numbers and not measured) else 0,
        "vague": len(VAGUE.findall(t)),
        "asserted": len(ASSERTED.findall(t)),
        "skipped": len(SKIPPED.findall(t)),
        # credited to the team with the candidate's own part unstated
        "attribution": pl if (pl > 0 and sg == 0) else 0,
    }


def total(text):
    return sum(signals(text).values())


def describe(text):
    s = signals(text)
    return ", ".join("%s=%d" % (k, v) for k, v in s.items() if v) or "none"
