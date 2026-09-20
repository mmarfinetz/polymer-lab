"""Small operational CLI; the Python API remains the primary interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .fiber import initialize_fiber_v1, summarize_fiber_v1
from .lab import PolymerLab
from .models import CampaignConfig
from .predictor import XGBoostEnsemble
from .public_surrogate import train_public_surrogate
from .validation import BasicPSmilesValidator, RDKitPSmilesValidator

DEMO_SEEDS = (
    "[*]CC[*]",
    "[*]CC([*])c1ccccc1",
    "[*]COC[*]",
    "[*]CC([*])(C)C(=O)OC",
    "[*]CC(F)([*])",
    "[*]Cc1ccc(cc1)C[*]",
    "[*]COc1ccc(cc1)OC[*]",
)


def _demo(args: argparse.Namespace) -> int:
    lab = PolymerLab.development(args.root)
    seeds = [lab.candidate(psmiles) for psmiles in DEMO_SEEDS]
    config = CampaignConfig(
        name="deterministic-demo",
        population_size=len(seeds),
        offspring_size=4,
        physics_batch_size=2,
        max_generations=2,
        max_candidates=50,
        max_physics_jobs=4,
        max_core_hours=100,
    )
    campaign = lab.create_campaign(config, seeds)
    campaign = lab.engine.start(campaign.id)
    ranked = lab.engine.ranked_population(campaign.id)
    payload = {
        "campaign_id": campaign.id,
        "state": campaign.state,
        "warning": "deterministic demo predictions are non-scientific",
        "top_candidates": [
            {
                "candidate_id": item.candidate.id,
                "psmiles": item.candidate.canonical_psmiles,
                "pareto_rank": item.pareto_rank,
                "feasible": item.feasible,
                "predictions": {
                    prediction.property.value: {
                        "mean": prediction.mean,
                        "uncertainty": prediction.uncertainty,
                        "unit": prediction.unit,
                    }
                    for prediction in item.predictions
                },
            }
            for item in ranked[:5]
        ],
        "agent_proposal": lab.engine.agent_proposal(campaign.id).model_dump(mode="json"),
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _validate(args: argparse.Namespace) -> int:
    validator = BasicPSmilesValidator() if args.basic else RDKitPSmilesValidator()
    candidate = validator.validate(args.psmiles)
    print(candidate.model_dump_json(indent=2))
    return 0


def _train_public(args: argparse.Namespace) -> int:
    report = train_public_surrogate(
        openpoly_csv=args.openpoly,
        radonpy_csv=args.radonpy,
        model_dir=args.model_dir,
        ensemble_size=args.ensemble_size,
        random_seed=args.random_seed,
        holdout_fraction=args.holdout_fraction,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _scientific_demo(args: argparse.Namespace) -> int:
    predictor = XGBoostEnsemble.load(args.model_dir)
    lab = PolymerLab.scientific_local(
        args.root,
        predictor=predictor,
        research_agent=args.agent,
        openai_model=args.openai_model,
        reasoning_effort=args.reasoning_effort,
        executor=args.executor,
    )
    seeds = [lab.candidate(psmiles) for psmiles in DEMO_SEEDS]
    config = CampaignConfig(
        name="public-surrogate-demo",
        population_size=len(seeds),
        offspring_size=4,
        physics_batch_size=2,
        max_generations=2,
        max_candidates=50,
        max_physics_jobs=4,
        max_core_hours=100,
    )
    campaign = lab.create_campaign(config, seeds)
    campaign = lab.engine.start(campaign.id)
    ranked = lab.engine.ranked_population(campaign.id)
    payload = {
        "campaign_id": campaign.id,
        "state": campaign.state,
        "prediction_status": predictor.model_metadata.get("status", "model-derived surrogate estimates"),
        "model_version": predictor.version,
        "held_out_metrics": predictor.model_metadata.get("held_out_metrics", {}),
        "top_candidates": [
            {
                "candidate_id": item.candidate.id,
                "psmiles": item.candidate.canonical_psmiles,
                "pareto_rank": item.pareto_rank,
                "feasible": item.feasible,
                "predictions": {
                    prediction.property.value: {
                        "mean": prediction.mean,
                        "uncertainty": prediction.uncertainty,
                        "unit": prediction.unit,
                    }
                    for prediction in item.predictions
                },
            }
            for item in ranked[:5]
        ],
        "agent_proposal": lab.engine.agent_proposal(campaign.id).model_dump(mode="json"),
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _fiber_v1_init(args: argparse.Namespace) -> int:
    manifest = initialize_fiber_v1(
        args.root,
        excluded_campaign_ids=tuple(args.exclude_campaign_id),
        force=args.force,
    )
    payload = summarize_fiber_v1(args.root)
    payload["manifest"] = str((args.root / "manifest.json").resolve())
    payload["candidate_ids"] = [candidate.id for candidate in manifest.candidates]
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _fiber_v1_status(args: argparse.Namespace) -> int:
    print(json.dumps(summarize_fiber_v1(args.root), indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="polymer-lab", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    smoke = subparsers.add_parser(
        "orchestration-smoke-test",
        help="run the deterministic test-only orchestration path",
    )
    smoke.add_argument("--root", type=Path, default=Path(".polymer-lab-smoke"))
    smoke.set_defaults(handler=_demo)
    validate = subparsers.add_parser("validate", help="validate one PSMILES repeat unit")
    validate.add_argument("psmiles")
    validate.add_argument("--basic", action="store_true", help="use syntax-only validation")
    validate.set_defaults(handler=_validate)
    train_public = subparsers.add_parser(
        "train-public-surrogate",
        help="train Tg/density models from OpenPoly and RadonPy PI1070",
    )
    train_public.add_argument("--openpoly", type=Path, required=True)
    train_public.add_argument("--radonpy", type=Path, required=True)
    train_public.add_argument("--model-dir", type=Path, required=True)
    train_public.add_argument("--ensemble-size", type=int, default=5)
    train_public.add_argument("--random-seed", type=int, default=42)
    train_public.add_argument("--holdout-fraction", type=float, default=0.2)
    train_public.set_defaults(handler=_train_public)
    scientific_demo = subparsers.add_parser(
        "scientific-demo",
        help="run a campaign with a fitted provenance-backed surrogate",
    )
    scientific_demo.add_argument("--root", type=Path, required=True)
    scientific_demo.add_argument("--model-dir", type=Path, required=True)
    scientific_demo.add_argument(
        "--agent",
        choices=("deterministic", "openai"),
        default="deterministic",
        help="orchestration policy; OpenAI requires polymer-lab[agent] and OPENAI_API_KEY",
    )
    scientific_demo.add_argument("--openai-model", default="gpt-5.6-terra")
    scientific_demo.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="medium")
    scientific_demo.add_argument(
        "--executor",
        choices=("recording", "local"),
        default="recording",
        help="record jobs or launch the scientific worker locally",
    )
    scientific_demo.set_defaults(handler=_scientific_demo)
    demo = subparsers.add_parser(
        "demo",
        help="run a campaign with a fitted provenance-backed surrogate",
    )
    demo.add_argument("--root", type=Path, required=True)
    demo.add_argument("--model-dir", type=Path, required=True)
    demo.add_argument(
        "--agent",
        choices=("deterministic", "openai"),
        default="deterministic",
        help="orchestration policy; OpenAI requires polymer-lab[agent] and OPENAI_API_KEY",
    )
    demo.add_argument("--openai-model", default="gpt-5.6-terra")
    demo.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="medium")
    demo.add_argument(
        "--executor",
        choices=("recording", "local"),
        default="recording",
        help="record jobs or launch the scientific worker locally",
    )
    demo.set_defaults(handler=_scientific_demo)
    fiber = subparsers.add_parser(
        "fiber-v1",
        help="initialize or inspect the scientifically gated fiber-v1 campaign",
    )
    fiber_actions = fiber.add_subparsers(dest="fiber_action", required=True)
    fiber_init = fiber_actions.add_parser("init", help="write the fiber-v1 target, seeds, and stage gates")
    fiber_init.add_argument("--root", type=Path, default=Path("runs/fiber-v1"))
    fiber_init.add_argument(
        "--exclude-campaign-id",
        action="append",
        default=[],
        help="record an obsolete campaign that must not continue into fiber-v1",
    )
    fiber_init.add_argument(
        "--force",
        action="store_true",
        help="rewrite an existing generated fiber-v1 manifest from the current reviewed contracts",
    )
    fiber_init.set_defaults(handler=_fiber_v1_init)
    fiber_status = fiber_actions.add_parser("status", help="show fiber-v1 readiness without inventing evidence")
    fiber_status.add_argument("--root", type=Path, default=Path("runs/fiber-v1"))
    fiber_status.set_defaults(handler=_fiber_v1_status)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
