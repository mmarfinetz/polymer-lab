from __future__ import annotations

from polymer_lab.models import CampaignConfig, Prediction, PropertyName
from polymer_lab.optimization import rank_candidates
from polymer_lab.validation import BasicPSmilesValidator


def _predictions(candidate_id: str, tg: float, density: float) -> list[Prediction]:
    return [
        Prediction(
            candidate_id=candidate_id,
            property=PropertyName.TG,
            mean=tg,
            uncertainty=5,
            unit="degC",
            model_version="test",
        ),
        Prediction(
            candidate_id=candidate_id,
            property=PropertyName.DENSITY,
            mean=density,
            uncertainty=0.02,
            unit="g/cm^3",
            model_version="test",
        ),
    ]


def test_pareto_ranking_and_feasibility() -> None:
    validator = BasicPSmilesValidator()
    best = validator.validate("[*]Cc1ccc(cc1)C[*]")
    tradeoff = validator.validate("[*]COc1ccc(cc1)OC[*]")
    dominated = validator.validate("[*]CC[*]")
    predictions = (
        _predictions(best.id, 210, 1.0) + _predictions(tradeoff.id, 230, 1.1) + _predictions(dominated.id, 100, 1.3)
    )
    ranked = rank_candidates([best, tradeoff, dominated], predictions, CampaignConfig(name="test"))
    by_id = {item.candidate.id: item for item in ranked}
    assert by_id[best.id].pareto_rank == 0
    assert by_id[tradeoff.id].pareto_rank == 0
    assert by_id[dominated.id].pareto_rank > 0
    assert by_id[best.id].feasible
    assert not by_id[dominated.id].feasible


def test_constraint_distance_precedes_uncertainty_and_diversity() -> None:
    validator = BasicPSmilesValidator()
    near = validator.validate("[*]Cc1ccc(cc1)C[*]")
    far = validator.validate("[*]CC([*])c1ccccc1")
    predictions = _predictions(near.id, 175, 1.1) + [
        Prediction(
            candidate_id=far.id,
            property=PropertyName.TG,
            mean=90,
            uncertainty=500,
            unit="degC",
            model_version="test",
        ),
        Prediction(
            candidate_id=far.id,
            property=PropertyName.DENSITY,
            mean=0.9,
            uncertainty=5,
            unit="g/cm^3",
            model_version="test",
        ),
    ]
    config = CampaignConfig(
        name="constraint-first",
        uncertainty_weight=100,
        diversity_weight=100,
    )

    ranked = rank_candidates([far, near], predictions, config)

    assert ranked[0].candidate.id == near.id
    assert not ranked[0].feasible
    assert ranked[0].constraint_violation == (180 - 175) / 180


def test_feasible_candidate_precedes_infeasible_pareto_tradeoff() -> None:
    validator = BasicPSmilesValidator()
    feasible = validator.validate("[*]Cc1ccc(cc1)C[*]")
    density_violation = validator.validate("[*]CC(F)([*])")
    predictions = _predictions(feasible.id, 181, 1.19) + _predictions(density_violation.id, 300, 1.21)

    ranked = rank_candidates(
        [density_violation, feasible],
        predictions,
        CampaignConfig(name="feasible-first"),
    )

    assert ranked[0].candidate.id == feasible.id
    assert ranked[0].feasible
    assert ranked[0].constraint_violation == 0
