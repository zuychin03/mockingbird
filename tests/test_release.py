"""Release plumbing (V1.1_PLAN P7): the workflow's pins, the notes it drafts, and one version."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from installer import release_notes  # noqa: E402

WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def test_every_action_is_pinned_to_a_commit():
    uses = re.findall(r"uses:\s*(\S+)", WORKFLOW)
    assert uses, "the workflow uses no actions?"
    for u in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u), "%s is not pinned by commit" % u


def test_inno_setup_is_pinned_by_checksum():
    url = re.search(r"INNO_URL:\s*(\S+)", WORKFLOW).group(1)
    digest = re.search(r"INNO_SHA256:\s*(\S+)", WORKFLOW).group(1)
    assert url.startswith("https://github.com/jrsoftware/issrc/releases/download/")
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_the_release_is_drafted_never_published_by_the_workflow():
    assert "--draft" in WORKFLOW and "gh release create" in WORKFLOW
    assert "gh release edit" not in WORKFLOW and "--draft=false" not in WORKFLOW


def test_one_version_everywhere():
    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    pkg = json.loads((ROOT / "ui" / "package.json").read_text(encoding="utf-8"))["version"]
    lock = json.loads((ROOT / "ui" / "package-lock.json").read_text(encoding="utf-8"))
    assert py == pkg == lock["version"] == lock["packages"][""]["version"]
    assert release_notes.version() == py


def test_the_changelog_has_a_section_for_this_version():
    body = release_notes.section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
                                 release_notes.version())
    assert body and not body.startswith("## ")


def test_a_section_stops_at_the_next_heading_and_a_missing_one_is_refused():
    text = "# Changelog\n\n## 2.0.0 - soon\n\nNew.\n\n### Added\n\n- x\n\n## 1.9.0 - then\n\nOld.\n"
    assert release_notes.section(text, "2.0.0") == "New.\n\n### Added\n\n- x"
    assert release_notes.section(text, "1.9.0") == "Old."
    with pytest.raises(SystemExit):
        release_notes.section(text, "2.0")


def test_the_notes_end_with_the_installer_checksum(tmp_path):
    exe = tmp_path / "Mockingbird-Setup-9.9.9.exe"
    exe.write_bytes(b"not really an installer")
    notes = release_notes.notes(exe)
    assert notes.rstrip().endswith(
        "110499c3d4d34a94a1ea70ae7e7353d32708e043bc0ccee13ec9fbdb7a9d20b1  "
        "Mockingbird-Setup-9.9.9.exe\n```")


def test_the_tag_check(monkeypatch):
    monkeypatch.setenv("GITHUB_REF_NAME", "v" + release_notes.version())
    monkeypatch.setattr(sys, "argv", ["release_notes.py", "check"])
    assert release_notes.main() == 0
    monkeypatch.setenv("GITHUB_REF_NAME", "v0.0.1")
    with pytest.raises(SystemExit):
        release_notes.main()


def test_nothing_the_installer_ships_from_config_is_gitignored():
    """The workflow builds from a clean checkout, so an ignored file the app needs would be
    missing from every released installer while a local build still had it."""
    import shutil
    import subprocess
    git = shutil.which("git")
    if not git or not (ROOT / ".git").exists():
        pytest.skip("needs a git checkout")
    files = [str(p.relative_to(ROOT)) for p in (ROOT / "config").rglob("*") if p.is_file()]
    got = subprocess.run([git, "check-ignore", "--no-index", *files], cwd=ROOT,
                         capture_output=True, text=True)
    assert got.stdout.strip() == "", "ignored but shipped: %s" % got.stdout.split()


def test_the_installer_carries_product_metadata():
    iss = (ROOT / "installer" / "mockingbird.iss").read_text(encoding="utf-8")
    for key in ("VersionInfoVersion", "VersionInfoProductName", "VersionInfoCompany",
                "VersionInfoDescription"):
        assert re.search(r"^%s=\S" % key, iss, re.M), key
