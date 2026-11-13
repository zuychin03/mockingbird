"""The interview fields (V1.2_PLAN D1), read from `config/fields.json`.

Closed for the reason the competency vocabulary is: an id outside this set has no prompt, no
bank view and no template, so it is refused rather than quietly run as software.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "fields.json"

SOFTWARE = "software"
GENERAL = "general"


@dataclass(frozen=True)
class Kind:
    """A standard plan: no job description, a fixed ranked list and a phase shape (FR-4)."""
    id: str
    label: str
    note: str
    ranked: tuple[str, ...]
    shape: dict[str, int]


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    # The phrase the turn and speech prompts name, in place of "a software-engineering job
    # interview".
    interview: str
    template: Path
    prompt_arm: str
    kinds: tuple[Kind, ...]
    # Shown where the interviewer was not measured on this field; None where it was.
    measured_note: str | None = None

    def kind(self, kind_id: str) -> Kind:
        for k in self.kinds:
            if k.id == kind_id:
                return k
        raise KeyError("unknown stock plan %r; known: %s"
                       % (kind_id, ", ".join(sorted(k.id for k in self.kinds))))


def _load(path: Path) -> dict[str, Field]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for f in raw["fields"]:
        kinds = tuple(Kind(k["id"], k["label"], k["note"], tuple(k["ranked"]), dict(k["shape"]))
                      for k in f["kinds"])
        out[f["id"]] = Field(f["id"], f["label"], f["interview"], ROOT / f["template"],
                             f["prompt_arm"], kinds, f.get("measured_note"))
    return out


FIELDS: dict[str, Field] = _load(CONFIG)

IDS = tuple(FIELDS)


def get(field_id: str) -> Field:
    try:
        return FIELDS[field_id]
    except KeyError:
        raise KeyError("unknown field %r; known: %s" % (field_id, ", ".join(IDS))) from None


def templates() -> dict[str, Path]:
    """Every field's template, keyed by field, for validating each bank view against it."""
    return {f.id: f.template for f in FIELDS.values()}
