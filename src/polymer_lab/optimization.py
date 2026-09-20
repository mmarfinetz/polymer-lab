"""Multi-objective Pareto ranking and active-learning acquisition."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from .models import CampaignConfig, PolymerCandidate, Prediction, RankedCandidate


def _prediction_map(predictions: Sequence[Prediction]) -> dict[str, dict[str, Prediction]]:
    result: dict[str, dict[str, Prediction]] = defaultdict(dict)
    for prediction in predictions:
        result[prediction.candidate_id][prediction.property.value] = prediction
    return result


def _dominates(
    left: PolymerCandidate,
    right: PolymerCandidate,
    prediction_map: dict[str, dict[str, Prediction]],
    config: CampaignConfig,
) -> bool:
    no_worse = True
    strictly_better = False
    for objective in config.objectives:
        a = prediction_map[left.id][objective.property.value].mean
        b = prediction_map[right.id][objective.property.value].mean
        if objective.direction == "maximize":
            no_worse &= a >= b
            strictly_better |= a > b
        else:
            no_worse &= a <= b
            strictly_better |= a < b
    return no_worse and strictly_better


def non_dominated_sort(
    candidates: Sequence[PolymerCandidate],
    predictions: Sequence[Prediction],
    config: CampaignConfig,
) -> list[list[PolymerCandidate]]:
    prediction_map = _prediction_map(predictions)
    required = {objective.property.value for objective in config.objectives}
    eligible = [candidate for candidate in candidates if required <= set(prediction_map[candidate.id])]
    dominated_count: dict[str, int] = {candidate.id: 0 for candidate in eligible}
    dominates: dict[str, list[PolymerCandidate]] = defaultdict(list)
    first: list[PolymerCandidate] = []
    for left in eligible:
        for right in eligible:
            if left.id == right.id:
                continue
            if _dominates(left, right, prediction_map, config):
                dominates[left.id].append(right)
            elif _dominates(right, left, prediction_map, config):
                dominated_count[left.id] += 1
        if dominated_count[left.id] == 0:
            first.append(left)
    fronts: list[list[PolymerCandidate]] = [first] if first else []
    while fronts and fronts[-1]:
        next_front: list[PolymerCandidate] = []
        for candidate in fronts[-1]:
            for dominated in dominates[candidate.id]:
                dominated_count[dominated.id] -= 1
                if dominated_count[dominated.id] == 0:
                    next_front.append(dominated)
        if next_front:
            fronts.append(next_front)
        else:
            break
    return fronts


def _crowding(
    front: Sequence[PolymerCandidate],
    prediction_map: dict[str, dict[str, Prediction]],
    config: CampaignConfig,
) -> dict[str, float]:
    if not front:
        return {}
    distances = {candidate.id: 0.0 for candidate in front}
    if len(front) <= 2:
        return {candidate.id: float(len(config.objectives)) for candidate in front}
    for objective in config.objectives:
        ordered = sorted(front, key=lambda c: prediction_map[c.id][objective.property.value].mean)
        values = [prediction_map[c.id][objective.property.value].mean for c in ordered]
        span = max(values) - min(values)
        # Accumulate one boundary contribution per objective. Assigning here
        # would erase a boundary contribution from an earlier objective and
        # could make an interior point appear more diverse than a true corner.
        distances[ordered[0].id] += 1.0
        distances[ordered[-1].id] += 1.0
        if span == 0:
            continue
        for index in range(1, len(ordered) - 1):
            distances[ordered[index].id] += min(1.0, (values[index + 1] - values[index - 1]) / span)
    return distances


def _constraint_violation(
    candidate: PolymerCandidate,
    prediction_map: dict[str, dict[str, Prediction]],
    config: CampaignConfig,
) -> float:
    """Return a unitless sum of threshold violations.

    Constraint distance must be compared before Pareto crowding when no
    candidate is feasible. Otherwise a diverse but clearly off-target
    candidate can consume an expensive physics evaluation.
    """

    total = 0.0
    for objective in config.objectives:
        value = prediction_map[candidate.id][objective.property.value].mean
        scale = max(abs(objective.threshold), 1.0)
        if objective.direction == "maximize":
            total += max(0.0, objective.threshold - value) / scale
        else:
            total += max(0.0, value - objective.threshold) / scale
    return total


def rank_candidates(
    candidates: Sequence[PolymerCandidate],
    predictions: Sequence[Prediction],
    config: CampaignConfig,
) -> list[RankedCandidate]:
    prediction_map = _prediction_map(predictions)
    fronts = non_dominated_sort(candidates, predictions, config)
    ranked: list[RankedCandidate] = []
    violations: dict[str, float] = {}
    for rank, front in enumerate(fronts):
        crowding = _crowding(front, prediction_map, config)
        for candidate in front:
            candidate_predictions = tuple(prediction_map[candidate.id].values())
            violation = _constraint_violation(candidate, prediction_map, config)
            violations[candidate.id] = violation
            feasible = violation == 0.0
            normalized_uncertainty = sum(
                prediction_map[candidate.id][objective.property.value].uncertainty
                / max(abs(objective.threshold), 1.0)
                for objective in config.objectives
            ) / len(config.objectives)
            uncertainty_score = normalized_uncertainty / (1.0 + normalized_uncertainty)
            constraint_score = 1.0 / (1.0 + violation)
            acquisition = (
                (2.0 if feasible else 0.0)
                + constraint_score
                + 1.0 / (1.0 + rank)
                + config.uncertainty_weight * uncertainty_score
                + config.diversity_weight * crowding[candidate.id]
            )
            ranked.append(
                RankedCandidate(
                    candidate=candidate,
                    predictions=candidate_predictions,
                    pareto_rank=rank,
                    crowding_distance=crowding[candidate.id],
                    constraint_violation=violation,
                    acquisition_score=acquisition,
                    feasible=feasible,
                )
            )
    # Feasibility and normalized threshold distance are strict priorities.
    # Acquisition breaks ties between candidates with equivalent constraint
    # status; it cannot override the campaign's stated scientific objective.
    return sorted(
        ranked,
        key=lambda item: (
            item.feasible,
            -violations[item.candidate.id],
            item.acquisition_score,
        ),
        reverse=True,
    )


def select_population(ranked: Sequence[RankedCandidate], count: int) -> list[PolymerCandidate]:
    return [item.candidate for item in ranked[:count]]
