"""V1.2_PLAN P1 and P2: the fields and their config, the arms, the software prompts pinned."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import bank, contract, fields, planner, provenance  # noqa: E402

NEW = [f for f in fields.IDS if f != fields.SOFTWARE]

# 1.1.0's value (4f9b7f6). Every measured turn result rests on these prompts.
SOFTWARE_HASH = "a94730b75622"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def test_the_fields_are_closed():
    assert fields.IDS == ("software", "data_analytics", "product_management", "ux_design",
                          "project_management", "general")
    with pytest.raises(KeyError):
        fields.get("nursing")


@pytest.mark.parametrize("arm", contract.ARMS)
def test_software_gets_the_constants_themselves_whatever_the_arm(arm):
    assert contract.system_for("software", arm) is contract.SYSTEM
    assert contract.speech_for("software", arm) is contract.SPEECH_SYSTEM


@pytest.mark.parametrize("field", NEW)
def test_arm_a_is_the_software_prompt_word_for_word(field):
    assert contract.system_for(field, "A") is contract.SYSTEM
    assert contract.speech_for(field, "A") is contract.SPEECH_SYSTEM


def test_each_arm_has_exactly_one_place_to_change():
    """A prompt edit that drops or doubles these would make the arms silently equal."""
    named = fields.FIELDS["software"].interview
    assert contract.SYSTEM.count(named) == 1
    assert contract.SPEECH_SYSTEM.count(named) == 1
    assert contract.SYSTEM.count(contract._EXAMPLE) == 1


@pytest.mark.parametrize("field", NEW)
def test_arm_b_names_the_field_and_changes_nothing_else(field):
    b = contract.system_for(field, "B")
    named = fields.FIELDS[field].interview
    assert b == contract.SYSTEM.replace(fields.FIELDS["software"].interview, named)
    assert "software" not in b
    assert contract._EXAMPLE in b
    assert contract.speech_for(field, "B") == contract.SPEECH_SYSTEM.replace(
        fields.FIELDS["software"].interview, named)


@pytest.mark.parametrize("field", NEW)
def test_arm_c_swaps_only_the_example(field):
    b, c = contract.system_for(field, "B"), contract.system_for(field, "C")
    assert contract._EXAMPLE not in c
    assert c == b.replace(contract._EXAMPLE, contract.NEUTRAL_EXAMPLE)
    assert contract.speech_for(field, "C") == contract.speech_for(field, "B")


def test_general_is_named_a_job_interview():
    assert contract.system_for("general", "B").startswith("You are conducting a job interview.")


def test_unknown_arm_or_field_is_refused():
    with pytest.raises(ValueError):
        contract.system_for("ux_design", "D")
    with pytest.raises(KeyError):
        contract.speech_for("nursing", "B")


def test_the_software_contract_hash_is_pinned():
    assert provenance.contract_hash() == SOFTWARE_HASH
    for arm in contract.ARMS:
        assert provenance.contract_hash("software", arm) == SOFTWARE_HASH


def test_the_hash_follows_the_prompts_actually_used():
    for field in NEW:
        assert provenance.contract_hash(field, "A") == SOFTWARE_HASH
        assert provenance.contract_hash(field, "B") != SOFTWARE_HASH
        assert provenance.contract_hash(field, "C") != provenance.contract_hash(field, "B")


def test_an_unresolvable_hash_records_unknown_rather_than_raising():
    assert provenance.contract_hash("nursing", "B") == "unknown"
    assert provenance.contract_hash("ux_design", "D") == "unknown"


def test_the_software_planner_prompts_are_pinned():
    """V1.2_PLAN D5: SWE planning changes only through the vocabulary, never its prompts."""
    assert _sha(planner.SYSTEM) == "9387534e96c3"
    assert _sha(planner.PROPOSE_SYSTEM) == "b15293508977"


# --- config/fields.json (V1.2_PLAN P2) -------------------------------------------------------

# 1.1's `planner.STOCK`, moved to the config unchanged.
STOCK_1_1 = {
    "behavioural": {
        "ranked": ("collaboration", "ownership", "incident_response", "mentoring",
                   "learning", "technical_judgement"),
        "shape": {"warmup": 2, "behavioural_core": 5, "technical_experience": 1,
                  "design": 0, "collaboration": 3, "closing": 1},
    },
    "technical": {
        "ranked": ("data_modelling", "performance", "system_design", "testing_quality",
                   "incident_response", "technical_judgement"),
        "shape": {"warmup": 1, "behavioural_core": 1, "technical_experience": 6,
                  "design": 2, "collaboration": 1, "closing": 1},
    },
    "mixed": {
        "ranked": ("collaboration", "data_modelling", "ownership", "performance",
                   "system_design", "mentoring", "testing_quality", "learning"),
        "shape": {"warmup": 2, "behavioural_core": 3, "technical_experience": 3,
                  "design": 1, "collaboration": 2, "closing": 1},
    },
}
ROUNDS = {"data_analytics": "analytics", "product_management": "product", "ux_design": "ux",
          "project_management": "delivery"}


def test_the_software_stock_plans_are_1_1s():
    sw = fields.get(fields.SOFTWARE)
    assert {k.id: {"ranked": k.ranked, "shape": k.shape} for k in sw.kinds} == STOCK_1_1
    assert planner.STOCK == STOCK_1_1
    assert sw.template == planner.TEMPLATE
    assert sw.template.name == "interview_swe_general.json"


def test_the_labels_and_phrases_are_p1s():
    assert {f.id: (f.label, f.interview) for f in fields.FIELDS.values()} == {
        "software": ("Software engineering", "a software-engineering job interview"),
        "data_analytics": ("Data analytics", "a data-analytics job interview"),
        "product_management": ("Product management", "a product-management job interview"),
        "ux_design": ("UX design", "a UX-design job interview"),
        "project_management": ("Project management", "a project-management job interview"),
        "general": ("General", "a job interview"),
    }


def test_every_field_runs_on_arm_a_unlabelled():
    """P1's decision 11/11: all five ship on arm A with no "not measured" label."""
    for f in fields.FIELDS.values():
        assert f.prompt_arm == "A" and f.measured_note is None, f.id


@pytest.mark.parametrize("field", NEW)
def test_each_new_field_has_its_kinds_shaped_to_its_template(field):
    f = fields.get(field)
    want = ["behavioural"] if field == fields.GENERAL else \
        ["behavioural", "mixed", ROUNDS[field]]
    assert [k.id for k in f.kinds] == want
    phases = [ph["id"] for ph in json.loads(f.template.read_text(encoding="utf-8"))["phases"]]
    for k in f.kinds:
        assert list(k.shape) == phases, k.id
        assert k.note and k.label, k.id


@pytest.mark.parametrize("field", NEW)
def test_a_ranked_list_holds_no_more_than_its_phases_can_ask(field):
    """onet_rank gives each phase only as many competencies as it has slots, so a stock plan's
    notes never list competencies it could not have asked as not covered."""
    f = fields.get(field)
    v = bank.load(bank.SHIPPED, templates=fields.templates()).view(field)
    for k in f.kinds:
        assert k.ranked and set(k.ranked) <= set(v.competencies), k.id
        for phase, slots in k.shape.items():
            assert sum(v.phase_affinity[c] == phase for c in k.ranked) <= slots, (k.id, phase)


def test_the_onet_ranks_are_recorded():
    raw = json.loads(fields.CONFIG.read_text(encoding="utf-8"))
    assert raw["onet_database"]["version"] == "31.0" and raw["onet_database"]["scale"] == "IM"
    by_id = {f["id"]: f for f in raw["fields"]}
    assert by_id["general"]["onet_mean_of"] == list(ROUNDS)
    for fid in fields.IDS:
        assert by_id[fid]["onet_importance"], fid
