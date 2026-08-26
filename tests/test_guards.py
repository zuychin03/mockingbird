"""Guard behaviour. Plan section 6.4.

Each guard exists because of an observed production defect, so each test names the defect
rather than the mechanism.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import guards  # noqa: E402


def g(act, say="", ok=True, ask=""):
    return {"act": act, "say": say, "ok": ok, "ask": ask}


# --------------------------------------------------------------- invalid input
def test_unparseable_becomes_probe():
    r = guards.apply(None, "anything", [])
    assert r.act == "probe" and r.needs_regeneration


def test_unknown_action_becomes_probe():
    assert guards.apply(g("ponder"), "anything", []).act == "probe"


# --------------------------------------------------- 1. invented-question strip
def test_advance_with_question_and_not_ok_becomes_probe():
    r = guards.apply(g("advance", "Good. What did you measure?", ok=False), "we shipped it", [])
    assert r.act == "probe"
    assert "invented-question->probe" in r.applied


def test_advance_with_question_but_ok_keeps_advance_and_drops_question():
    r = guards.apply(g("advance", "Great. What next?", ok=True), "we shipped it", [])
    assert r.act == "advance"
    assert "?" not in r.say


def test_a_grounded_end_with_a_stray_question_keeps_its_end():
    """`ok` decides guard 1 for `advance` only. On `end` it means nothing -- it asks whether
    the reply answered the QUESTION, and "I need to stop, sorry" never does -- so reading it
    as self-contradiction turned a grounded stop request into a probe. Whether an `end`
    stands is guard 2's call (9.19)."""
    r = guards.apply(g("end", "Of course. Shall we rearrange?", ok=False),
                     "Sorry, I need to stop the interview here.", [])
    assert r.act == "end"
    assert "?" not in r.say
    assert "invented-question->probe" not in r.applied


def test_an_ungrounded_end_with_a_question_is_still_downgraded():
    """The safety property that change must not cost: guard 2 still owns it."""
    r = guards.apply(g("end", "Right. What next?", ok=False),
                     "We shipped it behind a flag and it went fine.", [])
    assert r.act == "probe"
    assert "end-ungrounded->probe" in r.applied


# ------------------------------------------------------------------ 2. end gate
def test_end_without_the_users_own_words_downgrades():
    r = guards.apply(g("end", "We'll stop there."), "that's all I can remember", [])
    assert r.act == "probe"
    assert "end-ungrounded->probe" in r.applied


def test_end_is_honoured_when_the_user_asked_to_stop():
    r = guards.apply(g("end", "Of course."), "sorry, I need to stop here", [])
    assert r.act == "end"


def test_end_gate_reads_the_utterance_not_the_model_line():
    # The model wanting to end is not evidence. Only the candidate's words are.
    r = guards.apply(g("end", "You asked to finish, so we'll stop."), "it went fine", [])
    assert r.act == "probe"


# --------------------------------------------------------------- 3. repetition
def test_near_identical_probe_asks_for_regeneration():
    prev = ["Could you tell me more about the outcome?"]
    r = guards.apply(g("probe", "Could you tell me more about the outcome?"), "hmm", prev)
    assert r.needs_regeneration


def test_a_genuinely_different_probe_is_accepted():
    prev = ["Could you tell me more about the outcome?"]
    r = guards.apply(g("probe", "What did the numbers look like afterwards?"), "hmm", prev)
    assert not r.needs_regeneration


# ------------------------------------------------------------------- 4. length
def test_the_closing_actions_never_speak_the_model_line(tmp_path=None):
    """50 stored `advance` lines held 14 distinct strings and not one was a sentence."""
    for act, said in (("advance", "we shipped it and it worked"),
                      ("skip", "I'd rather not answer that one"),
                      ("end", "I need to stop the interview here")):
        r = guards.apply(g(act, "project management experience"), said, [])
        assert r.act == act, (act, r.act)
        assert r.say == "", act
        assert "closing-say-dropped" in r.applied


def test_a_plausible_closing_line_is_dropped_too():
    """Not a length rule: the handler's own line is better than any the model writes."""
    r = guards.apply(g("advance", "Good example."), "...", [])
    assert r.say == ""


def test_probe_is_truncated_at_a_sentence_boundary():
    long = "First sentence here. " + ("Padding sentence. " * 40)
    r = guards.apply(g("probe", long), "...", [])
    assert len(r.say) <= guards.MAX_SAY_CHARS
    assert r.say.endswith(".")


# ------------------------------------------------------- 5. prompt-label strip
def test_prompt_label_is_stripped():
    r = guards.apply(g("probe", "CURRENT QUESTION: tell me more. What happened next?"), "...", [])
    assert "CURRENT QUESTION" not in r.say
    assert "prompt-label-stripped" in r.applied


def test_real_acronyms_survive_the_label_strip():
    r = guards.apply(g("probe", "API: which one did you use?"), "...", [])
    assert "API" in r.say


# ----------------------------------------------------- 3b. echo guard (live find)
def test_say_lifted_from_the_utterance_is_dropped():
    # Observed live: candidate "I'd rather not go into that one, if that's alright"
    # produced say="if that's alright".
    r = guards.apply(g("skip", "if that's alright"),
                     "I'd rather not go into that one, if that's alright.", [])
    assert r.say == ""
    assert "echoed-utterance-dropped" in r.applied


def test_a_genuine_line_sharing_a_word_is_not_an_echo():
    r = guards.apply(g("probe", "What did that cost you in the end?"),
                     "we lost about a week in the end", [])
    assert r.say != ""
    assert "echoed-utterance-dropped" not in r.applied


def test_single_word_overlap_is_not_treated_as_an_echo():
    r = guards.apply(g("probe", "Understood, and then?"), "understood the tradeoff there", [])
    assert r.say == "Understood, and then?"


# --------------------------------------------- guard 2b: the clarify gate (log 8.17)
def test_clarify_without_a_question_becomes_a_probe():
    """Unguarded, clarify is an UNBUDGETED probe -- it does not consume the follow-up cap."""
    g = guards.apply({"act": "clarify", "say": "Can you elaborate?", "ok": False, "ask": ""},
                     "I built a dashboard nobody opened.", [])
    assert g.act == "probe"
    assert "clarify-ungrounded->probe" in g.applied


def test_clarify_survives_when_the_candidate_actually_asked():
    g = guards.apply({"act": "clarify", "say": "A specific example from your own work.",
                      "ok": False, "ask": "Do you mean a technology choice?"},
                     "Do you mean a technology choice, or how I decided?", [])
    assert g.act == "clarify"


def test_a_question_mark_alone_is_enough_evidence():
    g = guards.apply({"act": "clarify", "say": "Either is fine.", "ok": False, "ask": ""},
                     "Sorry, which one did you want?", [])
    assert g.act == "clarify"


def test_a_spoken_question_without_punctuation_still_counts():
    """Speech-to-text does not reliably punctuate, and this runs on transcribed audio."""
    g = guards.apply({"act": "clarify", "say": "Either is fine.", "ok": False, "ask": ""},
                     "sorry what do you mean by that", [])
    assert g.act == "clarify"


def test_the_gate_does_not_fire_on_other_actions():
    g = guards.apply({"act": "probe", "say": "Why?", "ok": False, "ask": ""},
                     "We used Redis.", [])
    assert g.act == "probe" and "clarify-ungrounded->probe" not in g.applied


# ------------------------------------ guard 3c: directness (log 8.17)
def test_a_hedged_opening_becomes_an_imperative():
    g = guards.apply({"act": "probe", "say": "Can you describe the context of that decision?",
                      "ok": False, "ask": ""}, "We picked Redis.", [])
    assert g.say == "Describe the context of that decision."
    assert "hedge-stripped" in g.applied


def test_a_question_word_remainder_takes_tell_me():
    """"explain why you thought X" is a subordinate clause, not a question -- stripping
    the hedge alone would leave the fragment "Why you thought X?"."""
    for said, want in [
        ("Can you explain why you thought Postgres was problematic?",
         "Tell me why you thought Postgres was problematic."),
        ("Can you elaborate on what you measured?", "Tell me what you measured."),
        ("Can you give an example of how that helped?",
         "Tell me how that helped."),
    ]:
        g = guards.apply({"act": "probe", "say": said, "ok": False, "ask": ""}, "ok", [])
        assert g.say == want, g.say


def test_a_direct_question_is_left_alone():
    g = guards.apply({"act": "probe", "say": "Why did you disagree?", "ok": False, "ask": ""},
                     "We argued about it.", [])
    assert g.say == "Why did you disagree?"
    assert "hedge-stripped" not in g.applied


def test_directness_never_changes_the_action():
    """Cosmetic by construction: it rewrites speech, never a decision."""
    g = guards.apply({"act": "reask", "say": "Can you describe a time you shipped late?",
                      "ok": False, "ask": ""}, "Nothing comes to mind.", [])
    assert g.act == "reask"


def test_advance_is_not_rewritten():
    """Directness only reshapes speech that is actually spoken."""
    r = guards.apply({"act": "advance", "say": "Can you describe it?", "ok": True, "ask": ""},
                     "done", [])
    assert r.say == "" and "hedge-stripped" not in r.applied


def test_only_the_first_sentence_is_spoken():
    """Two questions in a turn is one of the faults; the second is a second sentence."""
    r = guards.apply(g("probe", "What did you measure? And how did that land?"), "...", [])
    assert r.say == "What did you measure?"
    assert "extra-sentences-dropped" in r.applied


def test_a_single_sentence_is_untouched():
    r = guards.apply(g("probe", "What did you measure?"), "...", [])
    assert r.say == "What did you measure?"
    assert "extra-sentences-dropped" not in r.applied


# ------------------------------- the unverified-figure signal (log 8.19)
def test_a_spelled_number_without_a_unit_is_not_a_figure():
    """"one layer up" and "seven years" of service made the agent ask how they measured it."""
    from app.depth_signals import signals
    assert signals("one layer up, and regulated")["unverified"] == 0
    assert signals("no one else was around")["unverified"] == 0


def test_a_real_unverified_figure_still_fires():
    from app.depth_signals import signals
    assert signals("it took three weeks")["unverified"] > 0
    assert signals("we do forty deploys a day")["unverified"] > 0


def test_a_measured_figure_does_not_fire():
    from app.depth_signals import signals
    assert signals("p95 went from 8 seconds to 400ms, we traced it")["unverified"] == 0


def test_an_abbreviation_is_not_a_sentence_boundary():
    """A line was cut to "...and any other factors (e." live (log 8.20)."""
    r = guards.apply(g("probe", "Which factors (e.g. load, latency) did you weigh?"),
                     "...", [])
    assert r.say == "Which factors (e.g. load, latency) did you weigh?"


def test_a_real_second_sentence_is_still_dropped():
    r = guards.apply(g("probe", "What did you measure? And how did it land?"), "...", [])
    assert r.say == "What did you measure?"


# ------------------------------------- guard 2c: the skip gate (log 8.20)
def test_no_experience_is_a_reask_not_a_refusal():
    """A junior candidate's "I haven't done that" was recorded as a REFUSAL."""
    for said in ("I haven't done that, the seniors do migrations.",
                 "No experience with that one.",
                 "I can't think of one, I'm quite junior."):
        r = guards.apply(g("skip", ""), said, [])
        assert r.act == "reask", said
        assert "skip-ungrounded->reask" in r.applied


def test_a_real_refusal_still_skips():
    for said in ("I'd rather not go into that one, if that's alright.",
                 "Pass on that please.",
                 "I'd rather move on from that."):
        r = guards.apply(g("skip", ""), said, [])
        assert r.act == "skip", said



# --------------- guard 2b, provenance: `ask` must be the candidate's (log 8.21)
def test_a_model_authored_ask_does_not_satisfy_the_clarify_gate():
    """Measured live: the model wrote its OWN question into `ask` and walked the gate."""
    r = guards.apply({"act": "clarify", "say": "Tell me what you mean by that?", "ok": False,
                      "ask": "Can you explain what you mean by 'schema change on a live "
                             "system'? Are you referring to modifying database tables?"},
                     "I haven't done a schema change on a live system. That's not been my "
                     "work.", [])
    # The gate did its job: the forged `ask` is discarded and clarify does not survive.
    assert "ask-not-theirs-dropped" in r.applied
    assert "clarify-ungrounded->probe" in r.applied
    # It settles on `reask`, not `probe`, because "I haven't done that" is a cannot-answer
    # and section 6.3 says that is a reask. This line used to assert `probe`, which was what
    # happened rather than what the contract asks for (9.20).
    assert r.act == "reask"


def test_the_candidates_own_question_still_counts():
    r = guards.apply({"act": "clarify", "say": "Either is fine.", "ok": False,
                      "ask": "Do you mean a technology choice or how I decided?"},
                     "Do you mean a technology choice, or how I decided?", [])
    assert r.act == "clarify"
    assert "ask-not-theirs-dropped" not in r.applied


def test_a_lightly_tidied_quote_still_counts():
    """Speech-to-text and the model both tidy punctuation; verbatim is too strict."""
    r = guards.apply({"act": "clarify", "say": "Both.", "ok": False,
                      "ask": "did you mean the database schema or the API schema"},
                     "sorry, did you mean the database schema or the API schema?", [])
    assert r.act == "clarify"


# ------------------------------------- cannot-answer is the FIRST sentence (log 9.23)
def test_a_gap_named_after_a_real_answer_is_not_a_cannot_answer():
    """Found live: this reply was upgraded to `reask` and the candidate got their own good
    answer put to them again. Naming what you have not done is part of answering."""
    for said in ("Honestly the scale. My current pipeline is big but it's all fire-and-forget "
                 "- I've never had to think hard about delivery guarantees.",
                 "Multi-region under audit constraints. I've made deploys fast; I've never "
                 "had to make them fast and provable at the same time.",
                 "If I had to, I'd write tests against the current output first so I'd know "
                 "when I'd changed something. I just haven't had a real one.",
                 "Mostly I picked up bug tickets and followed the code. I never really sat "
                 "down and learned it properly."):
        assert not guards.cannot_answer(said), said


def test_the_inability_still_counts_when_it_opens_the_reply():
    for said in ("I haven't done a schema change on a live system. That's not been my work.",
                 "I can't really think of one. I'm quite junior so I go along with the seniors.",
                 "There isn't anything to measure, I just haven't had that come up. Sorry.",
                 "Nothing comes to mind, honestly. We don't have much scale."):
        assert guards.cannot_answer(said), said


def test_a_filler_sentence_does_not_hide_the_reply():
    """"Hmm." punctuates as a sentence of its own and would otherwise BE the first one."""
    assert guards.cannot_answer("Hmm. I can't really think of one, to be honest.")
    assert guards.cannot_answer("Well. I haven't done that.")


def test_the_upgrade_leaves_a_substantive_answer_alone():
    """The end-to-end shape of the live failure: guards must not rewrite the model here."""
    r = guards.apply(
        g("advance", "", ok=True),
        "Honestly the scale. I've never had to think hard about delivery guarantees.", [])
    assert r.act == "advance", r.guards


def _raw(act, ok=True, say="", ask=""):
    return {"act": act, "ok": ok, "say": say, "ask": ask}


def test_advance_with_ok_false_is_a_contradiction():
    """9.42. Guard 1 encoded this already but only inside the invented-question branch, so it
    fired only for a model that also wrote a question. granite writes one every time, llama
    writes none, and the identical error went uncaught on the model that stays quiet."""
    g = guards.apply(_raw("advance", ok=False), "I had to pick up a legacy Java service.", [])
    assert g.act == "probe"
    assert "advance-not-ok->probe" in g.applied


def test_an_honest_advance_still_advances():
    g = guards.apply(_raw("advance", ok=True), "We split the table live. I wrote the "
                                               "backfill, ran it in batches, zero downtime.", [])
    assert g.act == "advance"


def test_the_reask_vocabulary_added_in_942():
    for said in ("I've mostly worked on things I built myself, so not really.",
                 "Hmm. Not really, no. Nothing that stands out anyway.",
                 "That's not something I've personally owned, I don't think.",
                 "I don't think I've hit anything at that kind of scale, to be honest."):
        assert guards.cannot_answer(said), said


def test_the_two_phrases_rejected_on_corpus_evidence_stay_out():
    """Both were candidates for the same six fixtures and both took a real answer with them:
    a bare "not really" mid-sentence, and "didn't really have" in front of a noun phrase."""
    for said in ("It's not really fair on whoever notices the email first.",
                 "I didn't really have a good argument for it other than I know React better.",
                 "It's hard to say exactly, but we cut p95 from eight seconds to 300ms."):
        assert not guards.cannot_answer(said), said


def test_a_disjunctive_question_is_a_clarification_request():
    """`offers_a_choice` covers 9 of the 10 gold=clarify fixtures against `asks_what_i_meant`'s
    5, and was never consulted as a detector -- only to pick the reply once already clarify."""
    for said in ("Are you after the measurement process, or the actual fix?",
                 "Do you want my general checklist or a specific recent change?",
                 "Differently as in a different technology, or a different process?"):
        assert guards.offers_a_choice(said), said
    assert not guards.offers_a_choice("We used Redis, or Memcached before that.")
    # The tenth historically escaped this detector because its alternatives are separate
    # questions. The regression below pins the broader segmented-choice form.


def test_a_segmented_choice_is_still_a_clarification_request():
    """Granite 4.2 exposed the tenth clarify fixture: speech often puts the second
    alternative in its own short question instead of joining the two with `or`."""
    for said in ("Quickly meaning what, a few days? A sprint?",
                 "By soon, meaning how long, a week? A month?"):
        assert guards.offers_a_choice(said), said


def test_a_declarative_meaning_phrase_is_not_a_clarification_request():
    for said in (
            "The sample was stable, meaning what we measured was representative.",
            "I mean what we measured was representative. Does that answer your question?",
            "I mean what we measured was representative? Is that clear?"):
        assert not guards.asks_what_i_meant(said), said
        assert not guards.offers_a_choice(said), said


def test_a_detail_free_dependency_or_missing_process_is_a_cannot_answer():
    """Granite 4.2 probes these, but neither supplies a usable answer to follow up."""
    for said in ("It depends a lot on the team, so it's hard to say.",
                 "That varies by organisation, so it is difficult to say.",
                 "There is too much context missing, so it is impossible to say.",
                 "We didn't really have a formal on-call where I worked.",
                 "I did not really have an incident process in that role."):
        assert guards.cannot_answer(said), said
        guarded = guards.apply(_raw("probe", ok=False, say="Can you give an example?"),
                               said, [])
        assert guarded.act == "reask", said
        assert "cannot->reask" in guarded.applied


def test_a_missing_process_followed_by_a_real_action_stays_an_answer():
    for said in ("We didn't really have a runbook, so I wrote one.",
                 "We didn't really have alerts, but I added them after an outage.",
                 "We didn't really have dashboards; instead, I queried the logs.",
                 "We didn't really have a formal rotation; support was shared across the team.",
                 "I didn't really have a good argument for it other than I know React better.",
                 "It's hard to say exactly, but we cut p95 from eight seconds to 300ms.",
                 "It is hard to say. We cut p95 from eight seconds to 300 ms.",
                 "We did not really have a runbook where I worked. I wrote one after an outage."):
        assert not guards.cannot_answer(said), said


def test_an_explicit_refusal_outranks_a_trailing_uncertainty_phrase():
    said = "I would rather not answer because it is hard to say."
    assert not guards.cannot_answer(said)
    assert guards.refuses(said)
    assert guards.skip_requested(said)
    guarded = guards.apply(_raw("probe", ok=False, say="Can you give an example?"), said, [])
    assert guarded.act == "skip"
    assert "refusal->skip" in guarded.applied


def test_trust_ok_false_resolves_the_contradiction_the_other_way():
    """9.43. The two resolutions are mutually exclusive and each model wants the other one.
    granite's act is right on 10 of 11 advances and its `ok` on 7 of 10, so it advances; the
    invented question is stripped rather than promoted into the decision."""
    raw = {"act": "advance", "ok": False, "say": "What did you measure?", "ask": ""}
    said = "We split the users table live. I wrote the backfill and ran it in batches."
    assert guards.apply(dict(raw), said, [], True).act == "probe"
    g = guards.apply(dict(raw), said, [], False)
    assert g.act == "advance"
    assert "?" not in g.say


def test_the_knob_defaults_to_the_probing_side():
    """An unknown model errs toward keeping the question open (1c.5), so the default is the
    resolution that downgrades rather than the one that advances."""
    from app.runner import Speech
    assert Speech().trust_ok is True
    assert Speech.for_model("granite-4.1-3b").trust_ok is False
    assert Speech.for_model("llama-3.2-3b-instruct").trust_ok is True
    assert Speech.for_model("").trust_ok is True


def test_the_one_sentence_guard_keeps_the_question_not_the_first_sentence():
    """9.46. It kept parts[0], which is the question for granite every time and an
    acknowledgement for any model that acknowledges before asking. exaone-3.5 shipped a
    probe that asked nothing in 52% of its turns."""
    r = guards.apply(g("probe", "That sounds interesting! Could you elaborate on the "
                                "bottlenecks you hit?"), "we shipped a caching layer", [])
    assert "extra-sentences-dropped" in r.applied
    # And the surviving sentence is then rewritten, which it was not before 9.50: `direct()`
    # runs earlier in the chain and saw the acknowledgement, so a hedge on the sentence that
    # actually survives went unstripped.
    assert r.say == "Tell me about the bottlenecks you hit."
    assert "hedge-stripped" in r.applied


def test_it_still_drops_a_second_question():
    """The fault the guard was built for: two questions in one turn. The FIRST question
    survives, so this must not become "keep the last"."""
    r = guards.apply(g("probe", "What did you measure? And who else was involved?"),
                     "we shipped it", [])
    assert r.say == "What did you measure?"


def test_a_say_with_no_question_still_keeps_its_first_sentence():
    r = guards.apply(g("probe", "Tell me about the rollout. It matters for the next part."),
                     "we shipped it", [])
    assert r.say == "Tell me about the rollout."


def test_exaone_gets_granites_resolution_not_the_default():
    """9.45 measured it at 38/49 under the default and 45/49 under the other, recovering nine
    of its ten correct advances. Without a profile it would be benched at its worse one."""
    from app.runner import Speech
    assert Speech.for_model("exaone-3.5-2.4b-instruct@q5_k_m").trust_ok is False
    assert Speech.for_model("hermes-3-llama-3.2-3b").trust_ok is True


def test_the_could_you_mirrors_rewrite_like_their_can_you_twins():
    """9.50. The hedge table was built from granite's phrasings, so forms granite never uses
    were absent: "could you elaborate MORE on" is one word off an entry that is present, and
    seven of ten exaone lines opened with it."""
    for said, want in (
            ("Could you elaborate more on the bottlenecks?", "Tell me about the bottlenecks."),
            ("Could you tell me about the rollout?", "Tell me about the rollout."),
            ("Could you share the numbers you saw?", "Tell me about the numbers you saw."),
    ):
        r = guards.apply(g("probe", said), "we shipped it", [])
        assert r.say == want, (said, r.say)
        assert "hedge-stripped" in r.applied


def test_the_length_trigger_is_off_unless_a_profile_asks_for_it():
    """9.51. Measured once on granite it cost 3 decision items through history feedback, so
    it does not default on; exaone gains 3.4 words a line for nothing."""
    from app.runner import Speech
    assert Speech().max_say_words is None
    assert Speech.for_model("granite-4.1-3b").max_say_words is None
    assert Speech.for_model("exaone-3.5-2.4b-instruct@q4_k_m").max_say_words == 15
