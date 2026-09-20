from pathlib import Path

import pytest

from polymer_lab import PolymerLab
from polymer_lab.executors import SlurmConfig, SlurmExecutor
from polymer_lab.predictor import DeterministicSurrogate


def test_scientific_slurm_factory_uses_shared_workdir(tmp_path: Path) -> None:
    lab = PolymerLab.scientific_slurm(
        tmp_path,
        predictor=DeterministicSurrogate(),
        slurm=SlurmConfig(workdir=tmp_path),
    )
    assert isinstance(lab.engine.executor, SlurmExecutor)
    assert lab.engine.work_root == tmp_path / "jobs"


def test_scientific_slurm_factory_rejects_non_shared_workdir(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="same shared path"):
        PolymerLab.scientific_slurm(
            tmp_path,
            predictor=DeterministicSurrogate(),
            slurm=SlurmConfig(workdir=tmp_path / "cluster"),
        )
