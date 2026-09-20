from __future__ import annotations

import math

import pytest

from polymer_lab.aligned import (
    AlignedChainJob,
    AlignedChainMetrics,
    AlignedChainProtocol,
    AlignedChainResult,
    AlignedPreparationCriteria,
    analyze_aligned_preparation,
    analyze_stress_strain,
    chain_orientation_and_slip,
    extract_forcefield_preamble,
    final_equilibration_files,
    lammps_box_lengths,
    read_aligned_diagnostic_result,
    read_aligned_result,
    render_lammps_phase,
)
from polymer_lab.fiber import default_fiber_v1_candidates
from polymer_lab.models import JobState, PhysicsJob, SimulationSpec
from polymer_lab.validation import BasicPSmilesValidator


def _job(tmp_path, *, profile: str = "protocol_validation") -> AlignedChainJob:
    candidate = default_fiber_v1_candidates()[0]
    polymer = BasicPSmilesValidator().validate("[*]CC[*]")
    preparation = PhysicsJob(
        campaign_id="fiber-v1-test",
        candidate=polymer,
        spec=SimulationSpec(
            profile="production",
            target_atoms_per_chain=200,
            chain_count=4,
            rdkit_version="environment",
            psi4_version="environment",
            lammps_version="stable",
            extra={"mpi": 2},
        ),
        artifact_uri=f"file://{tmp_path / 'preparation'}",
        estimated_core_hours=10,
        state=JobState.APPROVED,
    )
    return AlignedChainJob(
        campaign_id="fiber-v1-test",
        candidate=candidate,
        preparation_job=preparation,
        protocol=AlignedChainProtocol(profile=profile, mpi_ranks=2),
        artifact_uri=f"file://{tmp_path}",
        estimated_core_hours=20,
        approved_by="test",
        approval_rationale="test fixture",
    )


def test_protocol_step_counts_and_manifest_identity(tmp_path) -> None:
    protocol = AlignedChainProtocol(
        draw_ratio=2,
        draw_true_strain_rate_s=5e9,
        tensile_true_strain_rate_s=5e9,
        tensile_max_true_strain=0.05,
    )
    job = _job(tmp_path)

    assert protocol.draw_steps == math.ceil(math.log(2) / 5e-6)
    assert protocol.tensile_steps == 10_000
    assert job.preparation_job.candidate.canonical_psmiles == "[*]CC[*]"
    assert len(job.manifest_hash) == 64


def test_forcefield_extraction_box_and_restartable_phase_rendering(tmp_path) -> None:
    preamble = extract_forcefield_preamble(
        """
        units real
        atom_style full
        boundary p p p
        pair_style lj/cut/coul/long 10.0
        pair_modify mix arithmetic
        kspace_style pppm 1.0e-4
        read_data ignored.data
        fix old all nvt temp 300 300 100
        """
    )
    data = tmp_path / "cell.data"
    data.write_text(
        "LAMMPS data\n\n0 atoms\n\n0 10 xlo xhi\n-1 11 ylo yhi\n2 22 zlo zhi\n"
    )
    protocol = AlignedChainProtocol(mpi_ranks=2)
    rendered = render_lammps_phase(
        phase="tensile",
        source=data,
        source_is_restart=False,
        preamble=preamble,
        destination=tmp_path,
        protocol=protocol,
        initial_lz=20,
    )
    restarted = render_lammps_phase(
        phase="draw",
        source=tmp_path / "checkpoints" / "draw.25000.restart",
        source_is_restart=True,
        preamble=preamble,
        destination=tmp_path,
        protocol=protocol,
        initial_lz=20,
    )

    assert lammps_box_lengths(data) == (10, 12, 20)
    assert "fix integrator all npt" in rendered
    assert "fix constraints all shake 0.0001 1000 0 m 1.0" in rendered
    assert "couple xy" in rendered
    assert "fix axial all deform 1 z trate" in rendered
    assert "remap x units box" in rendered
    assert "fix trace all ave/time" in rendered
    assert "variable true_strain equal ln(lz/v_initial_lz)" in rendered
    assert f"run {protocol.tensile_steps} upto" in rendered
    assert "read_restart" in restarted
    assert "read_data" not in restarted

    legacy = render_lammps_phase(
        phase="tensile",
        source=data,
        source_is_restart=False,
        preamble=preamble,
        destination=tmp_path,
        protocol=protocol.model_copy(update={"version": "aligned-chain-v1"}),
        initial_lz=20,
    )
    assert "variable true_strain equal log(lz/v_initial_lz)" in legacy


def test_final_equilibration_selection_and_stationarity_gate(tmp_path) -> None:
    for stage in (3, 5):
        (tmp_path / f"eq{stage}_last.data").write_text("data\n")
        (tmp_path / f"eq{stage}.in").write_text("input\n")
        (tmp_path / f"eq{stage}.log").write_text("log\n")
        (tmp_path / f"rg{stage}.profile").write_text("profile\n")
    stage, data, source_input, log, rg = final_equilibration_files(tmp_path)
    assert stage == 5
    assert data.name == "eq5_last.data"
    assert source_input.name == "eq5.in"
    assert log.name == "eq5.log"
    assert rg.name == "rg5.profile"

    def write_traces(*, drifting_density: bool) -> None:
        thermo_lines = []
        rg_lines = ["# test profile"]
        for index in range(31):
            step = index * 100
            density = 0.8 + (0.2 * index / 30 if drifting_density else 0.0001 * (index % 2))
            values = [0.0] * 28
            values[0] = step
            values[1] = step
            values[2] = 300 + 0.1 * (index % 2)
            values[3] = 1 + 2 * (index % 2)
            values[5] = 100 + 0.1 * (index % 2)
            values[7] = 50 + 0.1 * (index % 2)
            values[20] = density
            thermo_lines.append(" ".join(str(value) for value in values))
            if step:
                rg_lines.extend((f"{step} 2", f"1 {10 + 0.001 * (index % 2)}", "2 11.0"))
        log.write_text("\n".join(thermo_lines) + "\n")
        rg.write_text("\n".join(rg_lines) + "\n")

    criteria = AlignedPreparationCriteria(
        analysis_window_steps=3000,
        minimum_final_step=3000,
        minimum_samples=30,
    )
    write_traces(drifting_density=False)
    passing = analyze_aligned_preparation(
        stage=stage,
        log_path=log,
        rg_path=rg,
        temperature_k=300,
        pressure_atm=1,
        criteria=criteria,
    )
    assert passing.passed
    assert passing.sample_count == 31
    assert passing.rg_sample_count == 30
    assert passing.rg_final_step == passing.final_step

    write_traces(drifting_density=True)
    failing = analyze_aligned_preparation(
        stage=stage,
        log_path=log,
        rg_path=rg,
        temperature_k=300,
        pressure_atm=1,
        criteria=criteria,
    )
    assert not failing.passed
    assert "density_block_drift_fraction" in failing.failed_checks


def test_production_job_rejects_reused_diagnostic_preparation(tmp_path) -> None:
    pilot = _job(tmp_path)
    reused_preparation = pilot.preparation_job.model_copy(
        update={
            "spec": pilot.preparation_job.spec.model_copy(
                update={"extra": {"mpi": 2, "aligned_preparation_source": {"source": "test"}}}
            )
        }
    )
    with pytest.raises(ValueError, match="reused diagnostic preparation"):
        AlignedChainJob(
            campaign_id=pilot.campaign_id,
            candidate=pilot.candidate,
            preparation_job=reused_preparation,
            protocol=pilot.protocol.model_copy(update={"profile": "production"}),
            artifact_uri=f"file://{tmp_path / 'production'}",
            estimated_core_hours=20,
            approved_by="test",
            approval_rationale="test rejection",
        )


def test_stress_strain_and_chain_alignment_analysis(tmp_path) -> None:
    trace = tmp_path / "stress_strain.dat"
    trace.write_text(
        "# timestep strain stress_GPa temperature_K transverse_atm lx ly lz\n"
        + "\n".join(
            f"{index * 100} {index / 1000:.6f} {index / 10:.6f} 300 1 10 10 {20 + index / 10:.6f}"
            for index in range(51)
        )
        + "\n"
    )

    def dump(path, lengths, molecules) -> None:
        atoms = [(molecule, coordinate) for molecule, coordinates in molecules.items() for coordinate in coordinates]
        lines = [
            "ITEM: TIMESTEP",
            "0",
            "ITEM: NUMBER OF ATOMS",
            str(len(atoms)),
            "ITEM: BOX BOUNDS pp pp pp",
            f"0 {lengths[0]}",
            f"0 {lengths[1]}",
            f"0 {lengths[2]}",
            "ITEM: ATOMS id mol type xu yu zu",
        ]
        for atom_id, (molecule, coordinate) in enumerate(atoms, start=1):
            lines.append(f"{atom_id} {molecule} 1 {coordinate[0]} {coordinate[1]} {coordinate[2]}")
        path.write_text("\n".join(lines) + "\n")

    before = tmp_path / "before.dump"
    after = tmp_path / "after.dump"
    dump(before, (10, 10, 10), {1: [(1, 1, 2), (3, 1, 2)], 2: [(5, 5, 8), (7, 5, 8)]})
    dump(after, (10, 10, 20), {1: [(2, 2, 3), (2, 2, 5)], 2: [(6, 6, 15), (6, 6, 17)]})

    stress = analyze_stress_strain(trace)
    orientation_before, orientation_after, slip = chain_orientation_and_slip(before, after)

    assert stress["axial_modulus_gpa"] == pytest.approx(100)
    assert stress["modulus_fit_r2"] == pytest.approx(1)
    assert stress["peak_axial_stress_gpa"] == pytest.approx(4.9)
    assert orientation_before == pytest.approx(-0.5)
    assert orientation_after == pytest.approx(1.0)
    assert slip == pytest.approx(0.0)


def test_protocol_validation_result_cannot_be_admitted(tmp_path) -> None:
    job = _job(tmp_path)
    result = AlignedChainResult(
        job_id=job.id,
        campaign_id=job.campaign_id,
        candidate_id=job.candidate.id,
        design_hash=job.candidate.design_hash,
        protocol_hash=job.protocol.protocol_hash,
        profile="protocol_validation",
        converged=True,
        admissible_as_scientific_evidence=False,
        metrics=AlignedChainMetrics(
            axial_modulus_gpa=1,
            modulus_fit_r2=1,
            peak_axial_stress_gpa=0.1,
            peak_stress_true_strain=0.05,
            final_true_strain=0.05,
            mean_temperature_k=300,
            mean_transverse_pressure_atm=1,
            hermans_orientation_before=0,
            hermans_orientation_after_draw=0.5,
            nonaffine_chain_slip_fraction=0.01,
            sample_count=10,
        ),
        software_versions={"radonpy": "1", "rdkit": "1", "psi4": "1", "lammps": "1"},
        artifact_checksums={},
    )
    result_path = tmp_path / "result.json"
    result_path.write_text(result.model_dump_json())

    verified = read_aligned_diagnostic_result(job, result_path)
    assert verified.converged
    assert not verified.measurements

    with pytest.raises(ValueError, match="diagnostic"):
        read_aligned_result(job, result_path)
