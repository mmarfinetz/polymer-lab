# Polymer Lab

Polymer Lab is a closed-loop computational materials platform. Its original chemistry
screen generates linear amorphous homopolymers, predicts glass-transition temperature
and density, selects a Pareto-diverse physics batch, requires a recorded compute
approval, executes RadonPy/Psi4/LAMMPS, admits only converged results, retrains the
surrogate, and starts the next generation. The active engineering campaign is
`fiber-v1`, where the design object includes chemistry, molecular weight, segment and
core/sheath composition, spinning, drawing, crystallinity, filament geometry, and
bundle construction.

The LLM is an experiment planner. It cannot write property observations, approve
compute, mark a job converged, or call a shell. Scientific evidence comes from datasets
and simulation workers.

## Fiber V1

The current UHMWPE laboratory-test candidate has a
[fabrication and validation plan](docs/fiber-v1/fiber-bbd827e465e62664-fabrication-plan.md).
It is a process hypothesis, not a measured or production-qualified fiber.

Initialize the new design space without claiming any candidate-specific result:

```bash
uv run polymer-lab fiber-v1 init --root runs/fiber-v1
uv run polymer-lab fiber-v1 status --root runs/fiber-v1
```

The generated manifest contains two concrete first DOE points plus three unresolved
families. `uhmwpe-gel-draw-100-doe-001` fixes linear PE, Mn 1.5 M g/mol, Mw 3.0 M
g/mol, 5 wt% in paraffin oil, 170 C spinning, air quench/n-hexane extraction, draw
ratio 100 at 148 C, and an initial 20 um x 3,200-filament bundle design.
`ppta-dry-jet-wet-doe-001` fixes PPTA, Mn 20 kg/mol, Mw 40 kg/mol, 15 wt% in sulfuric
acid, 60 C spinning, a 6 mm air gap/water bath, draw ratio 3.5, and 300 C tension
annealing. These are literature-seeded experimental settings and explicit DOE
assumptions—not measurements or optimized formulations. The segmented
polyurethane-urea, silk-inspired multiblock, and prior 70/30 MaSp entries remain
unresolved hypotheses. The MaSp mean-baseline strength estimate is not evidence.

The evaluation plan is gated by fidelity:

1. Thermophysical screening for density, Tg, cohesion, and processability. The existing
   RadonPy worker applies only to compatible synthetic repeat-unit models.
2. Draw-ratio-specific aligned-chain simulation for axial modulus, peak-stress proxy,
   chain orientation, and non-affine chain slip.
3. Validated reactive-potential fracture simulation for strength, failure strain, and
   toughness.
4. Mesoscale filament/bundle simulation for defects, interfaces, twist, fatigue, knots,
   and anchors.
5. Spinning plus mechanical and environmental experiments for final admission.

The thermophysical and aligned-chain backends exist today. The aligned workflow uses
RadonPy/Psi4 to prepare a converged cell, then restartable LAMMPS uniaxial draw,
transverse-pressure relaxation, and small-strain tensile phases. Protocol-validation
runs are diagnostic and cannot emit measurements. Production admission requires exact
job/design/protocol identity, recorded software versions, temperature and transverse
pressure control, completed strain, increased orientation, a positive high-quality
modulus fit, sufficient samples, and checksummed raw artifacts. Fracture, bundle, and
experimental stages remain blocked rather than being silently replaced by estimates.
The diagnostic preparation gate audits the actual final RadonPy stage, thermo/Rg
sample counts, block stationarity, and source checksums; it is structurally forbidden
from production jobs. Production equilibration runs one 5 ns sampling block at a time,
uses durable eq1/eq2/eq3 and binary-restart checkpoints, and stops with a non-admissible
review artifact if RadonPy's full convergence gate fails. Additional sampling therefore
requires an explicit review instead of running silently. Sampling trajectories are
retained at reduced cadence while thermo and Rg cadence remains unchanged.
The fiber qualification gate ignores surrogate values,
requires exact candidate/design identity and converged stage-appropriate evidence, and
requires matching-design experimental measurements for every engineering objective.
It also checks that measured strength, filament count/diameter, and knot efficiency can
carry the 1 kN reference load within the measured bundle cross-section.

## What is implemented

- Immutable Pydantic contracts for candidates, predictions, observations, simulation
  protocols, jobs, approvals, campaigns, and agent proposals.
- SQLite development persistence and PostgreSQL production persistence with matching
  migrations and audited state transitions.
- Basic syntax validation for dependency-free tests and strict RDKit validation for
  scientific operation.
- PI1M seed ingestion and explicit-unit experimental CSV ingestion with checksums,
  rejected-row reports, provenance, and deduplication.
- Auditable genetic mutation, bootstrapped XGBoost/RDKit surrogates, uncertainty,
  non-dominated sorting, crowding, and active-learning acquisition.
- Elitist parent-plus-offspring population updates: every proposal is retained for
  audit, while only NSGA-II survivors become the next generation.
- Budget and approval-gated physics batches, local/recording and Slurm executors,
  content-addressed manifests, and strict result admission.
- A worker around RadonPy's supported `0_qm.py -> 1_eq.py -> 4_tg.py` AutoMD sequence.
- Deterministic and OpenAI Responses API researcher policies.

## Quick start

Install the scientific feature stack, train property-specific models from the
user-supplied OpenPoly and RadonPy CSVs, and run a campaign:

```bash
cd /Users/mitch/polymer-lab
uv sync --extra science --extra dev
uv run polymer-lab train-public-surrogate \
  --openpoly data/raw/openpoly_properties.csv \
  --radonpy data/raw/radonpy_pi1070.csv \
  --model-dir models/public-v1
uv run polymer-lab demo \
  --root /tmp/polymer-lab-demo \
  --model-dir models/public-v1
uv run pytest
```

The default agent is a local deterministic orchestration policy, so this path does
not need an OpenAI API key. To let an OpenAI model choose the next bounded action,
install the optional adapter and provide `OPENAI_API_KEY`:

```bash
uv sync --extra science --extra agent
export OPENAI_API_KEY=...
uv run polymer-lab demo \
  --root /tmp/polymer-lab-openai-demo \
  --model-dir models/public-v1 \
  --agent openai
```

The OpenAI adapter can propose orchestration only. It cannot create observations,
approve compute, or mark a simulation converged.

If Slurm is unavailable, use the local scientific executor on a machine with the
RadonPy/Psi4/LAMMPS worker environment:

```bash
uv run polymer-lab demo \
  --root /shared-or-local/polymer-lab-run \
  --model-dir models/public-v1 \
  --executor local
```

This launches `polymer_lab.worker` as a local subprocess. It is not a shortcut around
the science stack: the worker still requires RadonPy, Psi4, LAMMPS, RDKit, and the
reviewed AutoMD scripts, and results still pass the same convergence and provenance
checks. On this development machine RadonPy, Psi4, and LAMMPS are not installed, so
the local executor cannot produce scientific results until that environment is added.

The resulting values are provenance-backed surrogate estimates with held-out MAE/RMSE/R²
in `models/public-v1/model_card.json`. They are predictions, not direct measurements.
The deterministic path remains available only as `orchestration-smoke-test` for testing
state transitions without a scientific software stack.

Python API:

```python
from polymer_lab import CampaignConfig, PolymerLab
from polymer_lab.predictor import XGBoostEnsemble

predictor = XGBoostEnsemble.load("models/public-v1")
lab = PolymerLab.scientific_local("./run", predictor=predictor)
seeds = [
    lab.candidate("[*]CC[*]"),
    lab.candidate("[*]CC([*])c1ccccc1"),
    lab.candidate("[*]COc1ccc(cc1)OC[*]"),
]
campaign = lab.create_campaign(CampaignConfig(name="high-tg-low-density"), seeds)
campaign = lab.engine.start(campaign.id)
frontier = lab.engine.ranked_population(campaign.id)
proposal = lab.engine.agent_proposal(campaign.id)
```

The bounded agent runner executes safe orchestration actions, but never approves
compute. Its first call establishes the baseline; its next call prepares the proposed
physics batch and stops at the approval gate:

```python
from polymer_lab import SimulationSpec

step = lab.engine.run_agent_step(
    campaign.id,
    spec=SimulationSpec(),
    estimated_core_hours_per_job=20,
)

approval = lab.engine.approve(
    campaign.id,
    step.job_ids,
    approved_by="scientist@example.edu",
    rationale="reviewed active-learning batch",
)
lab.engine.submit_approved(campaign.id)
```

After the scheduler finishes, another agent step polls, admits valid results, retrains
on the full `D0 + new evidence` corpus, performs parent-plus-offspring selection, and
advances the generation. Invalid or unconverged results stop the loop with an explicit
scientific-result error. The research agent sees the recent Pareto frontier, admitted
observations, and audit events; it may bias the next generation only toward a fixed,
validated set of mutation operators. It cannot submit arbitrary chemistry code.

## Production services

Start development PostgreSQL and MinIO after reviewing the example credentials:

```bash
docker compose up -d postgres minio
```

Install the coordinator with the adapters it needs:

```bash
uv sync --extra science --extra postgres --extra s3 --extra agent --extra tracking --extra dev
```

The production factory accepts an already fitted `PropertyPredictor`, a
`SlurmConfig`, an S3-compatible artifact store, the PostgreSQL URL, and a shared work
directory. This makes an untrained surrogate or missing durable archive impossible to
hide inside infrastructure setup. `work_root` and the Slurm work directory must be the
same path on a filesystem mounted by both coordinator and workers. Admitted manifests,
results, logs, and simulation artifacts are streamed to object storage with SHA-256
metadata before observations enter the training corpus.

For a smaller deployment, `PolymerLab.scientific_slurm` uses SQLite and local artifacts
while sending approved jobs to Slurm:

```python
from pathlib import Path

from polymer_lab import PolymerLab
from polymer_lab.executors import SlurmConfig
from polymer_lab.predictor import XGBoostEnsemble

root = Path("/shared/polymer-lab")
lab = PolymerLab.scientific_slurm(
    root,
    predictor=XGBoostEnsemble.load("models/public-v1"),
    slurm=SlurmConfig(
        workdir=root,
        partition="compute",
        account="materials",
        qos="normal",
        time_limit="48:00:00",
        ntasks=16,
        cpus_per_task=1,
        memory="64G",
        python_executable="/shared/envs/polymer-lab/bin/python",
        environment_setup="source /shared/envs/polymer-lab/bin/activate",
    ),
)
```

Create the campaign and call `engine.approve(...)` explicitly before
`engine.submit_approved(...)`. The Slurm worker writes `result.json`; polling only
admits results that pass identity, protocol, convergence, software-version, unit,
plausibility, and artifact-checksum validation.

XGBoost training requires an explicit provenance domain. Train separate models for
experimental labels and for the RadonPy MD emulator; do not silently blend them:

```python
from polymer_lab.models import PropertyName, Provenance
from polymer_lab.predictor import XGBoostEnsemble

emulator = XGBoostEnsemble(
    training_domains={
        PropertyName.TG: {Provenance.EXPERIMENTAL},
        PropertyName.DENSITY: {Provenance.MD},
    }
)
emulator.fit(repository.training_examples())
emulator.save("./models/radonpy-emulator")
emulator = XGBoostEnsemble.load("./models/radonpy-emulator")
```

## Scientific worker

RadonPy currently requires Python 3.9-3.13 and recommends installing Psi4 and LAMMPS
from conda-forge. The coordinator and worker are intentionally separate.

```bash
conda env create -f environments/radonpy-worker.yml
conda activate polymer-lab-radonpy
export RADONPY_SOURCE_DIR=/reviewed/path/to/RadonPy
bash scripts/install-radonpy-worker.sh
export RADONPY_AUTOMD_DIR="$RADONPY_SOURCE_DIR/AutoMD_scripts"
```

The project does not clone RadonPy or silently select a revision. Pin and review the
checkout used by the cluster, then record its revision in the simulation configuration.
The worker refuses to run if RadonPy, RDKit, Psi4, LAMMPS, or the AutoMD scripts are
missing. A `smoke` profile may check dependencies but cannot emit scientific
observations. Results record package versions and SHA-256 hashes of the three AutoMD
scripts.

Prepare the full PE/aPS/PMMA three-seed validation suite after RDKit is installed:

```bash
PYTHONPATH=src python scripts/prepare_reference_validation.py --output ./validation
```

Review the nine-job estimate, then create the approval record and rewrite only those
manifests as approved:

```bash
PYTHONPATH=src python scripts/approve_reference_validation.py \
  --index ./validation/validation_jobs.csv \
  --approved-by scientist@example.edu \
  --rationale "reviewed reference validation" \
  --max-core-hours 2250
```

After execution, summarize only results that pass full identity, convergence, version,
unit, plausibility, and checksum admission:

```bash
PYTHONPATH=src python scripts/summarize_reference_validation.py --root ./validation
```

Each manifest must receive explicit approval before Slurm submission. A result is
admitted only if identities and protocol hashes match at both result and observation
level; density and Tg are finite, plausible, unique, and in canonical units; provenance
is MD; declared software versions match; artifacts pass checksum verification; and
RadonPy reports successful equilibration.

## Data policy

PI1M is not downloaded or redistributed. Its repository describes the dataset as
academic-use only even though the repository contains an MIT license. Users provide the
CSV explicitly, and every imported candidate records its source checksum and row.

Experimental CSV loading never guesses units. Callers map every property column to a
canonical property, unit, scale, and offset. Experimental, surrogate, MD, and DFT values
remain distinct provenance classes. Rows are atomic: one malformed value rejects the
entire row instead of leaking a partial observation into training.

## Operational boundaries

- The legacy chemistry loop supports connected linear homopolymer repeat units with
  exactly two attachments; Tg and density are its only optimization objectives.
- `fiber-v1` is a separate fiber-system contract so amorphous Tg/density results cannot
  be mistaken for tensile qualification.
- RadonPy thermophysical evidence cannot satisfy aligned-chain, fracture, bundle, or
  experimental fiber gates.
- Genetic mutation is the shipped generator. POLYT5 and polyRETRO remain external
  adapters because their model weights/data terms must be reviewed separately.
- Full RadonPy production runs are external, expensive jobs and are not part of CI.
- PostgreSQL and S3-compatible storage are production requirements; SQLite and local
  artifacts are development adapters.
- MLflow is optional tracking infrastructure and never acts as the system of record.
- Secrets are read from the environment and are not stored in manifests or audit events.
