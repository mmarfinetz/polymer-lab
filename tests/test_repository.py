from __future__ import annotations

import pytest

from polymer_lab.errors import InvalidStateTransition
from polymer_lab.models import CampaignConfig, CampaignRecord, CampaignState
from polymer_lab.repository import SQLiteRepository


def test_campaign_state_transitions_are_enforced(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "test.sqlite3")
    campaign = CampaignRecord(config=CampaignConfig(name="test"))
    repository.save_campaign(campaign)
    running = campaign.model_copy(update={"state": CampaignState.RUNNING})
    repository.save_campaign(running)
    with pytest.raises(InvalidStateTransition):
        repository.save_campaign(running.model_copy(update={"state": CampaignState.CREATED}))


def test_candidate_identity_is_deduplicated(tmp_path) -> None:
    from polymer_lab.validation import BasicPSmilesValidator

    repository = SQLiteRepository(tmp_path / "test.sqlite3")
    validator = BasicPSmilesValidator()
    first = validator.validate("[*]CC[*]")
    second = validator.validate("[*] CC [*]")
    assert repository.save_candidate(first).id == repository.save_candidate(second).id


def test_candidate_can_survive_into_multiple_generations(tmp_path) -> None:
    from polymer_lab.validation import BasicPSmilesValidator

    repository = SQLiteRepository(tmp_path / "test.sqlite3")
    campaign = CampaignRecord(config=CampaignConfig(name="test"))
    repository.save_campaign(campaign)
    candidate = BasicPSmilesValidator().validate("[*]CC[*]")
    repository.attach_candidates(campaign.id, [candidate], generation=0)
    repository.attach_candidates(campaign.id, [candidate], generation=1)
    assert repository.campaign_candidates(campaign.id, generation=0)[0].id == candidate.id
    assert repository.campaign_candidates(campaign.id, generation=1)[0].id == candidate.id
    assert len(repository.campaign_candidates(campaign.id)) == 1
