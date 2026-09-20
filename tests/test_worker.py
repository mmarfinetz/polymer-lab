from __future__ import annotations

from types import SimpleNamespace

import pytest

from polymer_lab.radonpy_analysis import (
    _compact_diagnostics,
    _json_value,
    adaptive_trajectory_window,
)
from polymer_lab.worker import _detect_lammps_version, _radonpy_environment


def test_lammps_version_uses_first_nonempty_banner_line(monkeypatch) -> None:
    monkeypatch.setattr("polymer_lab.worker.shutil.which", lambda executable: "/env/bin/lmp")
    monkeypatch.setattr(
        "polymer_lab.worker.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="\nLarge-scale Atomic/Molecular Massively Parallel Simulator - 22 Jul 2025 - Update 5\n\nUsage",
            stderr="",
        ),
    )

    assert _detect_lammps_version("/env/bin/lmp") == (
        "Large-scale Atomic/Molecular Massively Parallel Simulator - 22 Jul 2025 - Update 5"
    )


def test_lammps_version_rejects_empty_or_failed_help(monkeypatch) -> None:
    monkeypatch.setattr("polymer_lab.worker.shutil.which", lambda executable: "/env/bin/lmp")
    monkeypatch.setattr(
        "polymer_lab.worker.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="\n", stderr=""),
    )
    assert _detect_lammps_version("lmp") == "unknown"

    monkeypatch.setattr(
        "polymer_lab.worker.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failure"),
    )
    assert _detect_lammps_version("lmp") == "missing"


def test_radonpy_environment_declares_sampling_output_cadence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LAMMPS_EXEC", "/worker/bin/lmp")
    spec = SimpleNamespace(
        extra={
            "mpi": 16,
            "retry_equilibration": 0,
            "no_trajectory": True,
            "sampling_dump_frequency_steps": 10_000,
        },
        target_atoms_per_chain=1000,
        chain_count=10,
        initial_density_g_cm3=0.05,
        tacticity="atactic",
        force_field="GAFF2_mod",
        charge_method="RESP",
        temperature_k=300,
        pressure_atm=1,
        random_seed=11,
    )
    job = SimpleNamespace(
        id="production-test",
        candidate=SimpleNamespace(canonical_psmiles="[*]CC[*]", structure_hash="a" * 64),
        spec=spec,
    )

    environment = _radonpy_environment(job, tmp_path)

    assert environment["RadonPy_RetryEQ"] == "0"
    assert environment["RadonPy_No_Traj"] == "True"
    assert environment["PolymerLab_EQ_Dump_Frequency"] == "10000"


def test_adaptive_trajectory_window_preserves_requested_window_when_possible() -> None:
    assert adaptive_trajectory_window(5001) == (2000, 2000)
    assert adaptive_trajectory_window(501) == (500, 500)

    with pytest.raises(ValueError, match="at least three"):
        adaptive_trajectory_window(2)


def test_radonpy_analysis_json_value_supports_numpy_arrays_and_complex() -> None:
    import numpy as np

    assert _json_value(np.asarray([1.0, np.nan])) == [1.0, None]
    assert _json_value(np.complex128(1.5 + 0.25j)) == {
        "real": 1.5,
        "imaginary": 0.25,
    }


def test_radonpy_analysis_compacts_per_frame_diagnostics() -> None:
    assert _compact_diagnostics(
        {"mean": 0.5, "width": 500, "director": [[1.0, 0.0, 0.0]]}
    ) == {"mean": 0.5, "width": 500}
