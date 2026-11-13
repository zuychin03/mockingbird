"""The interview fields (V1.2_PLAN D1).

Closed for the reason the competency vocabulary is: an id outside this set has no prompt, no
bank view and no template, so it is refused rather than quietly run as software. P2 moves the
table into `config/fields.json`; the ids do not change.
"""

from __future__ import annotations

from dataclasses import dataclass

SOFTWARE = "software"
GENERAL = "general"


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    # The phrase the turn and speech prompts name, in place of "a software-engineering job
    # interview".
    interview: str


FIELDS: dict[str, Field] = {f.id: f for f in (
    Field(SOFTWARE, "Software engineering", "a software-engineering job interview"),
    Field("data_analytics", "Data analytics", "a data-analytics job interview"),
    Field("product_management", "Product management", "a product-management job interview"),
    Field("ux_design", "UX design", "a UX-design job interview"),
    Field("project_management", "Project management", "a project-management job interview"),
    Field(GENERAL, "General", "a job interview"),
)}

IDS = tuple(FIELDS)


def get(field_id: str) -> Field:
    try:
        return FIELDS[field_id]
    except KeyError:
        raise KeyError("unknown field %r; known: %s" % (field_id, ", ".join(IDS))) from None
