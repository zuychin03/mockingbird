"""Release plumbing for `.github/workflows/release.yml`.

    python installer/release_notes.py check                 the pushed tag is v<pyproject version>
    python installer/release_notes.py notes EXE --out FILE  draft notes: the CHANGELOG section for
                                                            this version, then the checksum
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def version() -> str:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def section(changelog: str, ver: str) -> str:
    """The body under `## <ver>`, up to the next `## ` heading."""
    out, inside = [], False
    for line in changelog.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = re.match(r"## \[?%s\]?(\s|$)" % re.escape(ver), line) is not None
            continue
        if inside:
            out.append(line)
    body = "\n".join(out).strip()
    if not body:
        raise SystemExit("CHANGELOG.md has no section for %s" % ver)
    return body


def notes(exe: Path) -> str:
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    body = section((REPO / "CHANGELOG.md").read_text(encoding="utf-8"), version())
    return "%s\n\n## Checksum\n\n```\n%s  %s\n```\n" % (body, digest, exe.name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    n = sub.add_parser("notes")
    n.add_argument("exe", type=Path)
    n.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "check":
        tag, want = os.environ.get("GITHUB_REF_NAME", ""), "v" + version()
        if tag != want:
            raise SystemExit("tag %r does not match the version in pyproject.toml (%s)" % (tag, want))
        print("building %s" % want)
        return 0
    a.out.write_text(notes(a.exe), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
