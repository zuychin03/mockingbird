"""V1.2_PLAN P1: the fields, the prompt arms, and the software prompts pinned."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import contract, fields, planner, provenance  # noqa: E402

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
