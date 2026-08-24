"""Is a quote offered as a `result` actually a result? Log section 9.10.

Section 9.9 found two ways the `result` part goes wrong, and both survive quote grounding,
because grounding asks *did they say this* and never *is this a result*:

    scale-as-result    "it's about eight million rows a day, retained for two weeks"
    filler-as-result   "It was a fairly tense couple of weeks, people had strong opinions."

Both were scored as `states_outcome` met in real reports, and both would let an adaptive stop
rule close a question with no outcome in it.

The rule: a result states a CHANGE or a COMPLETION. That is a fact about text, the kind
section 7.36 concluded this pipeline can check, as opposed to an abstract quality like "was
this a good outcome", which it cannot.

Deliberately not a list of GOOD outcomes. "It got worse" and "we never shipped it" are results,
and a rule that only recognised improvement would quietly score honesty down.

**It is used for PACING ONLY, and deliberately not for scoring.** Measured by
`tools/tier2_result_check.py` over 22 quotes: 9 of 9 non-results rejected, but 5 of 13 genuine
results dropped too, because a result can state a state of affairs rather than name a change
-- "Row counts matched exactly, so the cutover was uneventful". A looser variant that rejected
only number-heavy text kept 12 of 13 genuine results and let all six pieces of filler back in.
Neither is good enough for the report.

The two uses have opposite cost asymmetries, which is what settles it:

    scoring   dropping a real result lowers an honest candidate's score, and 8.23 calls
              understating the candidate the worst direction for a coach to be wrong in
    pacing    failing to recognise a result costs one more probe, which is the direction
              1c.5 explicitly wants a phantom to err in

So `states_change` gates the adaptive STOP only. `observe.py` is untouched, and the
scale-as-result defect in `states_outcome` (9.9) stays open rather than being papered over
with a rule that costs more than it fixes.
"""

from __future__ import annotations

import re

CHANGE = re.compile(
    r"\b(?:"
    r"end(?:ed)? up|ended|came? down|come down|went (?:from|down|up)|down to|up to|"
    r"drop(?:ped)?|fell|rose|cut|reduc(?:e|ed)|improv(?:e|ed)|halv(?:e|ed)|doubl(?:e|ed)|"
    r"fix(?:ed)?|stopp?(?:ed)?|resolv(?:e|ed)|clear(?:ed)?|shipp?(?:ed)?|land(?:ed)?|"
    r"launch(?:ed)?|deliver(?:ed)?|finish(?:ed)?|complet(?:e|ed)|"
    r"turn(?:ed)? out|work(?:ed)?|fail(?:ed)?|broke|didn'?t work|never (?:did|happened)|"
    r"now |since then|after that|these days|in the end|eventually|finally|"
    r"took (?:about |roughly |around )?\w+ (?:minutes?|hours?|days?|weeks?|months?)|"
    r"no longer|stopped being|went away|disappear(?:ed)?|"
    r"agreed|convinc(?:e|ed)|kept our|we kept|switch(?:ed)?|mov(?:e|ed) to"
    r")\b"
    # No trailing boundary: "got reviewed" has no break between the stem and its suffix.
    r"|\bgot \w*(?:review|merg|approv|fix|shipp|sign)\w*", re.I)


def states_change(quote: str) -> bool:
    """Does this text say something changed or completed?"""
    return bool(CHANGE.search(quote or ""))
