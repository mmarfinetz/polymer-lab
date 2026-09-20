from __future__ import annotations

from types import SimpleNamespace

import pytest

from polymer_lab.agent import OpenAIResearchAgent
from polymer_lab.errors import ValidationError
from polymer_lab.models import CampaignConfig, CampaignRecord, CampaignState


class FakeResponses:
    def __init__(self, arguments: str) -> None:
        self.arguments = arguments
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        call = SimpleNamespace(
            type="function_call",
            name="submit_research_proposal",
            arguments=self.arguments,
        )
        return SimpleNamespace(output=[call])


def test_openai_agent_validates_tool_output_and_evidence_ids() -> None:
    responses = FakeResponses(
        '{"action":"request_physics","rationale":"uncertain frontier",'
        '"evidence_ids":["event-1"],"parameters":{"count":2,"preferred_mutations":[]}}'
    )
    client = SimpleNamespace(responses=responses)
    agent = OpenAIResearchAgent(client=client)
    campaign = CampaignRecord(
        config=CampaignConfig(name="test", physics_batch_size=2),
        state=CampaignState.RUNNING,
    )
    proposal = agent.propose(
        campaign,
        {"evidence_ids": ["event-1"], "available_mutations": []},
    )
    assert proposal.parameters.count == 2
    assert responses.kwargs["model"] == "gpt-5.6-terra"


def test_openai_agent_rejects_fabricated_evidence() -> None:
    responses = FakeResponses(
        '{"action":"stop","rationale":"done","evidence_ids":["made-up"],'
        '"parameters":{"count":null,"preferred_mutations":[]}}'
    )
    agent = OpenAIResearchAgent(client=SimpleNamespace(responses=responses))
    campaign = CampaignRecord(config=CampaignConfig(name="test"), state=CampaignState.RUNNING)
    with pytest.raises(ValidationError, match="unknown evidence"):
        agent.propose(campaign, {"evidence_ids": []})
