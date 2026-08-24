"""Deterministic depth signals -- the observations a probe decision could rest on.

T1.27 failed because "is there anything worth asking about" is a judgement, and this model
judges badly (§7.10). These are OBSERVATIONS instead: computed in Python, no model, perfectly
reproducible, and each one corresponds to a move a real interviewer makes.

No thresholds or probe rules live here. This module only reports what it finds, so the
question "do these separate a complete answer from an incomplete one" can be asked before any
rule is built on top.
"""

from __future__ import annotations

import re

# A figure is "verified" when the candidate says how they know it.
MEASURED = re.compile(
    r"\b(measur|benchmark|profil|trac(e|ed|ing)|logg|logs|monitor|instrument|"
    r"test(ed|ing)?|count(ed)?|track(ed)?|showed|verif|check(ed)?|explain analyze|"
    r"p9\d|percentile|dashboard|metric|a/b|experiment)\w*", re.I)

# A spelled-out number is only a FIGURE when a unit follows it. Without that, "one layer up",
# "no one else" and "seven years" of service all read as unverified claims, and the focus
# selector asks a candidate how they measured their own job title (log 8.19). Digits count
# alone -- nobody writes "42" incidentally.
_UNIT = (r"(?:%|percent|ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|"
         r"years?|k|m|x|thousand|million|billion|times|requests?|users?|people|engineers?|"
         r"services?|rows?|queries|deploys?|jobs?|gb|mb|kb|tb|a day|an hour|a week)")
_SPELLED = (r"one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|"
            r"sixty|seventy|eighty|ninety|hundred|thousand|million")
NUMBER = re.compile(
    r"\b(\d+(?:[.,]\d+)?\s*" + _UNIT + r"?|(?:" + _SPELLED + r")\s+" + _UNIT + r")\b", re.I)

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


def signals(text):
    """Return {signal_name: count}. Pure function of the text."""
    t = text or ""
    numbers = NUMBER.findall(t)
    measured = bool(MEASURED.search(t))
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
