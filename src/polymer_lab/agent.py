"""Budget-aware researcher policies; neither adapter can create scientific observations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import DependencyUnavailable, ValidationError
from .models import AgentProposal, CampaignRecord, CampaignState


class DeterministicResearchAgent:
    """Reproducible control policy for tests, baselines, and no-key operation."""

    def propose(self, campaign: CampaignRecord, evidence: Mapping[str, Any]) -> AgentProposal:
        evidence_ids = tuple(str(item) for item in evidence.get("evidence_ids", ()))
        if campaign.state == CampaignState.CREATED:
            return AgentProposal(
                action="advance_generation",
                rationale="The campaign must establish baseline surrogate predictions.",
                evidence_ids=evidence_ids,
            )
        if campaign.state == CampaignState.RUNNING:
            if evidence.get("completed_physics_jobs", 0) > evidence.get("last_retrain_job_count", 0):
                return AgentProposal(
                    action="retrain",
                    rationale="New converged physics evidence is available for the emulator.",
                    evidence_ids=evidence_ids,
                )
            return AgentProposal(
                action="request_physics",
                rationale="Evaluate the highest-value Pareto-diverse candidates within the configured batch budget.",
                evidence_ids=evidence_ids,
                parameters={"count": campaign.config.physics_batch_size},
            )
        if campaign.state in {CampaignState.WAITING_APPROVAL, CampaignState.WAITING_PHYSICS}:
            return AgentProposal(
                action="stop",
                rationale="The campaign is waiting on an external approval or physics job; do not duplicate work.",
                evidence_ids=evidence_ids,
            )
        return AgentProposal(
            action="stop",
            rationale=f"Campaign state {campaign.state} is terminal or not actionable.",
            evidence_ids=evidence_ids,
        )


PROPOSAL_TOOL = {
    "type": "function",
    "name": "submit_research_proposal",
    "description": (
        "Submit exactly one bounded next action. This proposes orchestration only and cannot create "
        "measurements, approve compute, or mark a simulation converged."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["advance_generation", "request_physics", "retrain", "stop"],
            },
            "rationale": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "anyOf": [
                            {"type": "integer", "minimum": 1},
                            {"type": "null"},
                        ]
                    },
                    "preferred_mutations": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "phenyl_to_pyridyl",
                                "pyridyl_to_phenyl",
                                "ether_to_methylene",
                                "methylene_to_ether",
                                "methyl_to_fluoro",
                                "fluoro_to_methyl",
                                "carbonyl_to_sulfone",
                                "sulfone_to_carbonyl",
                                "phenylene_rigidification",
                            ],
                        },
                    },
                },
                "required": ["count", "preferred_mutations"],
                "additionalProperties": False,
            },
        },
        "required": ["action", "rationale", "evidence_ids", "parameters"],
        "additionalProperties": False,
    },
    "strict": True,
}


class OpenAIResearchAgent:
    def __init__(
        self,
        *,
        model: str = "gpt-5.6-terra",
        client: Any | None = None,
        reasoning_effort: str = "medium",
    ) -> None:
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise DependencyUnavailable("OpenAI agent support requires polymer-lab[agent]") from exc
            client = OpenAI()
        self.client = client
        self.model = model
        self.reasoning_effort = reasoning_effort

    def propose(self, campaign: CampaignRecord, evidence: Mapping[str, Any]) -> AgentProposal:
        allowed_evidence_ids = {str(item) for item in evidence.get("evidence_ids", ())}
        response = self.client.responses.create(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            instructions=(
                "You orchestrate a polymer research campaign. Treat stored surrogate and converged physics "
                "records as the only property evidence. Never invent measurements. Choose one bounded action "
                "consistent with campaign state and budgets. For retraining, you may prefer only mutation names "
                "listed in the evidence. Expensive physics still requires external approval."
            ),
            input=json.dumps(
                {
                    "campaign": campaign.model_dump(mode="json"),
                    "evidence": dict(evidence),
                },
                sort_keys=True,
                default=str,
            ),
            tools=[PROPOSAL_TOOL],
            tool_choice={"type": "function", "name": "submit_research_proposal"},
        )
        calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
        if len(calls) != 1 or calls[0].name != "submit_research_proposal":
            raise ValidationError("research agent did not return exactly one proposal tool call")
        proposal = AgentProposal.model_validate_json(calls[0].arguments)
        unknown = set(proposal.evidence_ids) - allowed_evidence_ids
        if unknown:
            raise ValidationError(f"agent cited unknown evidence ids: {sorted(unknown)}")
        if proposal.action == "request_physics":
            requested = proposal.parameters.count or campaign.config.physics_batch_size
            if requested < 1 or requested > campaign.config.physics_batch_size:
                raise ValidationError("agent requested a physics batch outside configured limits")
        available_mutations = set(evidence.get("available_mutations", ()))
        unknown_mutations = set(proposal.parameters.preferred_mutations) - available_mutations
        if unknown_mutations:
            raise ValidationError(f"agent requested unknown mutation strategies: {sorted(unknown_mutations)}")
        return proposal
