"""Closed-loop computational polymer research platform."""

from .fiber import FiberCandidate, FiberV1Manifest, FiberV1Target
from .lab import PolymerLab
from .models import AgentStepResult, CampaignConfig, Objective, PolymerCandidate, SimulationSpec

__all__ = [
    "AgentStepResult",
    "CampaignConfig",
    "FiberCandidate",
    "FiberV1Manifest",
    "FiberV1Target",
    "Objective",
    "PolymerCandidate",
    "PolymerLab",
    "SimulationSpec",
]

__version__ = "0.1.0"
