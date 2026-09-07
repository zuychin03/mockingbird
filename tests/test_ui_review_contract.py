"""Small source checks for review findings that are easy to regress."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "ui" / "src" / "routes" / "+page.svelte"
HISTORY = ROOT / "ui" / "src" / "routes" / "history" / "+page.svelte"
PLAYBACK = ROOT / "ui" / "src" / "lib" / "Playback.svelte"


def test_inline_question_textareas_have_contextual_names():
    source = PLAN.read_text(encoding="utf-8")
    assert re.search(r'<textarea[^>]*aria-label="Edit question \{row\.n\}"', source, re.S)
    assert re.search(
        r'<textarea[^>]*aria-label="Add a question to '
        r'\{row\.phase\.id\.replace\(/_/g, \' \'\)\}"',
        source,
        re.S,
    )


def test_report_retry_rebuilds_the_open_report():
    source = HISTORY.read_text(encoding="utf-8")
    assert "if (opened) build(opened);" in source
    assert "<Problem {problem} onretry={retry}" in source


def test_report_does_not_claim_certification():
    source = HISTORY.read_text(encoding="utf-8")
    assert "Certified" not in source
    assert "Evidence limits" in source


def test_playback_uses_one_audio_element_for_the_whole_list():
    """One element is what guarantees starting an answer stops the one before it. Giving each
    answer its own player is the obvious refactor and it lets two answers talk over each other,
    which is the single thing playback must never do."""
    source = PLAYBACK.read_text(encoding="utf-8")
    assert source.count("<audio") == 1
    assert "{#each spoken as a" in source, "the element must sit outside the per-answer loop"
    assert source.index("<audio") < source.index("{#each spoken as a")


def test_playback_caps_the_jump_list_and_says_what_it_left_out():
    """One 84-second answer has 56 pauses. Listing them all is a wall nobody reads; listing
    six without saying so pretends there were six."""
    source = PLAYBACK.read_text(encoding="utf-8")
    assert "const JUMPS = 6;" in source
    assert "longest of {a.pauses.length}" in source
    assert "{#each notable(a.pauses)" in source, "the chips must come from the capped list"
    assert "{#each a.pauses as p, i (i)}" in source, "every pause still belongs on the track"


def test_playback_controls_are_reachable_without_a_mouse():
    """The scrubber is a real range input rather than a styled div precisely so that seeking
    works from the keyboard; both it and the play button need names to go with it."""
    source = PLAYBACK.read_text(encoding="utf-8")
    assert 'type="range"' in source
    assert 'aria-label="Seek within' in source
    assert 'aria-label="Play' in source
