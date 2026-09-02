"""Small source checks for review findings that are easy to regress."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "ui" / "src" / "routes" / "+page.svelte"
HISTORY = ROOT / "ui" / "src" / "routes" / "history" / "+page.svelte"


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
