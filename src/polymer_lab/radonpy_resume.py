"""Durable substage checkpoints for RadonPy's EQ21step equilibration.

RadonPy 1.0b2 runs packing (eq1), compression/decompression (eq2), and
sampling (eq3) inside one Python call.  This wrapper preserves RadonPy's
protocol while allowing a restarted Slurm job to load the last completely
written RDKit molecule instead of repeating an already completed substage.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_RUN_LINE = re.compile(r"^\s*run\s+(\d+)\s*$")
_THERMO_STEP = re.compile(r"^\s*(\d+)\s+")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_lammps_resume_input(
    original: str,
    *,
    restart_file: str,
    restart_step: int,
    log_file: str = "eq2.log",
    max_resume_steps: int | None = None,
) -> tuple[str, int]:
    """Build the remaining portion of a sequential RadonPy LAMMPS input."""

    lines = original.splitlines()
    runs: list[tuple[int, int, int]] = []
    cumulative = 0
    for index, line in enumerate(lines):
        match = _RUN_LINE.match(line)
        if not match:
            continue
        steps = int(match.group(1))
        runs.append((index, cumulative, cumulative + steps))
        cumulative += steps
    if not runs:
        raise ValueError("LAMMPS input contains no fixed-length run commands")
    if restart_step <= 0 or restart_step >= cumulative:
        raise ValueError(f"restart step {restart_step} is outside resumable range 1..{cumulative - 1}")

    run_index = -1
    run_end = 0
    for index, _, end in runs:
        if restart_step < end:
            run_index, run_end = index, end
            break
    if run_index < 0:
        raise ValueError("could not locate interrupted LAMMPS run block")

    first_run_index = runs[0][0]
    first_stage_start = first_run_index
    while first_stage_start >= 0 and not lines[first_stage_start].lstrip().startswith("timestep "):
        first_stage_start -= 1
    if first_stage_start < 0:
        raise ValueError("could not locate timestep command for first LAMMPS run block")

    stage_start = run_index
    while stage_start >= 0 and not lines[stage_start].lstrip().startswith("timestep "):
        stage_start -= 1
    if stage_start < 0:
        raise ValueError("could not locate timestep command for interrupted LAMMPS run block")
    restart_command = next((line for line in lines if line.lstrip().startswith("restart ")), None)
    if restart_command is None:
        raise ValueError("LAMMPS input does not define restart output")
    # LAMMPS binary restarts preserve force-field styles and coefficients but
    # intentionally do not preserve the long-range solver and several global
    # neighbor/mixing settings. Reapply those from the audited original input.
    restore_prefixes = (
        "kspace_style ",
        "dielectric ",
        "special_bonds ",
        "pair_modify ",
        "neighbor ",
        "neigh_modify ",
        "comm_modify ",
    )
    restore_commands = [
        line for line in lines if line.lstrip().startswith(restore_prefixes)
    ]
    data_index = next(
        (
            index
            for index, line in enumerate(lines[:first_stage_start])
            if line.lstrip().startswith(("read_data ", "read_restart "))
        ),
        None,
    )
    if data_index is None:
        raise ValueError("could not locate original LAMMPS data-loading command")
    # Recreate run-time outputs and thermo settings that binary restart files
    # intentionally do not retain.  Stage-specific computes/fixes are restored
    # separately below, beginning at the interrupted stage's timestep command.
    runtime_preamble = [
        line
        for line in lines[data_index + 1 : first_stage_start]
        if not line.lstrip().startswith("restart ")
    ]

    remaining_steps = run_end - restart_step
    if max_resume_steps is not None:
        if max_resume_steps <= 0:
            raise ValueError("max_resume_steps must be positive")
        remaining_steps = min(remaining_steps, max_resume_steps)

    stage_lines = lines[stage_start:run_index]
    full_msd_thermo = next(
        (
            line
            for line in reversed(stage_lines)
            if line.lstrip().startswith("thermo_style ") and "v_msd" in line.split()
        ),
        None,
    )
    warmup_steps = min(1000, remaining_steps) if full_msd_thermo else 0
    if full_msd_thermo:
        warmup_thermo = " ".join(token for token in full_msd_thermo.split() if token != "v_msd")
        stage_lines = [warmup_thermo if line == full_msd_thermo else line for line in stage_lines]

    run_lines: list[str]
    if full_msd_thermo:
        run_lines = [
            "# Warm up resumed ave/time fixes before exposing their values to thermo output.",
            f"run {warmup_steps}",
        ]
        if remaining_steps > warmup_steps:
            run_lines.extend(
                (
                    full_msd_thermo,
                    "thermo_modify flush yes",
                    "thermo 1000",
                    f"run {remaining_steps - warmup_steps}",
                )
            )
    else:
        run_lines = [f"run {remaining_steps}"]

    resumed = [
        "# Generated by polymer-lab from a validated LAMMPS binary restart.",
        f"log {log_file} append",
        f"read_restart {restart_file}",
        *restore_commands,
        restart_command,
        "",
        *runtime_preamble,
        *stage_lines,
        *run_lines,
        *lines[run_index + 1 :],
        "",
    ]
    return "\n".join(resumed), cumulative


def _latest_thermo_step(log_path: Path) -> int:
    latest = 0
    with log_path.open(errors="replace") as handle:
        for line in handle:
            match = _THERMO_STEP.match(line)
            if match:
                latest = max(latest, int(match.group(1)))
    return latest


def _restart_step(lammps_executable: str, restart_path: Path, work_dir: Path) -> int:
    inspect_input = work_dir / ".polymer_lab_restart_inspect.in"
    inspect_input.write_text(
        "\n".join(
            (
                "log none",
                f"read_restart {restart_path.name}",
                "variable polymer_lab_step equal step",
                'print "POLYMER_LAB_RESTART_STEP=${polymer_lab_step}"',
                "quit",
                "",
            )
        )
    )
    completed = subprocess.run(
        [lammps_executable, "-in", inspect_input.name],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    match = re.search(r"POLYMER_LAB_RESTART_STEP=(\d+)", f"{completed.stdout}\n{completed.stderr}")
    if completed.returncode != 0 or match is None:
        raise RuntimeError(f"could not inspect LAMMPS restart {restart_path}: {completed.stderr[-1000:]}")
    return int(match.group(1))


def _select_partial_restart(
    work_dir: Path,
    input_path: Path,
    log_path: Path,
    lammps_executable: str,
) -> tuple[Path, int] | None:
    if not input_path.is_file() or not log_path.is_file():
        return None
    latest_log_step = _latest_thermo_step(log_path)
    if latest_log_step <= 0:
        return None
    candidates: list[tuple[int, Path]] = []
    for restart_path in work_dir.glob("radon_md_*.rst"):
        # Exclude stale restart files from an earlier RadonPy substage.
        if restart_path.stat().st_mtime <= input_path.stat().st_mtime:
            continue
        step = _restart_step(lammps_executable, restart_path, work_dir)
        if 0 < step <= latest_log_step:
            candidates.append((step, restart_path))
    if not candidates:
        return None
    step, path = max(candidates, key=lambda item: item[0])
    return path, step


def _atomic_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _archive_partial_outputs(work_dir: Path, names: tuple[str, ...], restart_step: int) -> dict[str, str]:
    """Preserve pre-restart trajectory evidence before LAMMPS opens new outputs."""

    archived: dict[str, str] = {}
    for name in names:
        source = work_dir / name
        if not source.is_file() or source.stat().st_size == 0:
            continue
        destination = source.with_name(f"{source.stem}.pre_resume_{restart_step}{source.suffix}")
        if destination.exists():
            raise RuntimeError(f"refusing to overwrite archived partial trajectory: {destination}")
        source.replace(destination)
        archived[destination.name] = _sha256(destination)
    return archived


def install_equilibration_resume() -> None:
    """Patch RadonPy 1.0b2's EQ21step executor with safe substage resume."""

    from radonpy.core import calc, utils
    from radonpy.sim import lammps
    from radonpy.sim.preset import eq
    from rdkit import Geometry as Geom

    if not getattr(eq.Equilibration.sampling, "_polymer_lab_output_control", False):
        original_sampling = eq.Equilibration.sampling

        def sampling_with_output_control(self, *args, **kwargs):
            md = original_sampling(self, *args, **kwargs)
            dump_frequency = int(os.environ.get("PolymerLab_EQ_Dump_Frequency", "1000"))
            if dump_frequency < 1000 or dump_frequency % 1000:
                raise ValueError(
                    "PolymerLab_EQ_Dump_Frequency must be a multiple of 1000 and at least 1000"
                )
            md.dump_freq = dump_frequency
            return md

        sampling_with_output_control._polymer_lab_output_control = True
        eq.Equilibration.sampling = sampling_with_output_control

    if getattr(eq.EQ21step.exec, "_polymer_lab_resume", False):
        return

    def exec_with_resume(
        self,
        confId: int = 0,
        f_density: float = 0.8,
        max_temp: float = 600.0,
        temp: float = 300.0,
        press: float = 1.0,
        max_press: float = 50000,
        step_list=None,
        press_ratio=None,
        time_step: float = 1.0,
        eq_step: int = 5,
        omp: int = 1,
        mpi: int = 1,
        gpu: int = 0,
        intel: str = "auto",
        opt: str = "auto",
        **kwargs,
    ):
        work_dir = Path(self.work_dir)
        save_dir = Path(self.save_dir)
        checkpoint_dir = save_dir / ".polymer_lab_checkpoints"
        lmp = lammps.LAMMPS(work_dir=self.work_dir, solver_path=self.solver_path)

        def checkpoint(stage: str) -> Path:
            return checkpoint_dir / f"{stage}.json"

        def completed(stage: str, required: tuple[Path, ...]) -> bool:
            return checkpoint(stage).is_file() and all(path.is_file() and path.stat().st_size > 0 for path in required)

        def mark(stage: str, required: tuple[Path, ...]) -> None:
            missing = [str(path) for path in required if not path.is_file() or path.stat().st_size == 0]
            if missing:
                raise RuntimeError(f"cannot checkpoint incomplete RadonPy {stage}: {missing}")
            _atomic_checkpoint(
                checkpoint(stage),
                {
                    "stage": stage,
                    "completed_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "required_files": [str(path) for path in required],
                },
            )

        eq1_required = (
            save_dir / self.pickle_file1,
            save_dir / self.json_file1,
            work_dir / self.last_data1,
            work_dir / self.log_file1,
        )
        if completed("eq1", eq1_required):
            utils.radon_print("Resuming after completed packing simulation (eq1).", level=1)
            self.mol = utils.pickle_load(str(save_dir / self.pickle_file1))
        else:
            utils.MolToPDBFile(self.mol, os.path.join(self.work_dir, self.pdb_file))
            lmp.make_dat(self.mol, file_name=self.dat_file1, confId=confId)
            started = datetime.datetime.now()
            utils.radon_print("Packing simulation (eq1) by LAMMPS is running...", level=1)
            md1 = self.packing(
                f_density=f_density,
                comm_cutoff=kwargs.get("comm_cutoff", 8.0),
                **kwargs,
            )
            self.mol = lmp.run(
                md1,
                mol=self.mol,
                confId=confId,
                input_file=self.in_file1,
                last_str=self.last_str1,
                last_data=self.last_data1,
                omp=omp,
                mpi=mpi,
                gpu=gpu,
                intel=intel,
                opt=opt,
            )
            utils.MolToJSON(self.mol, str(save_dir / self.json_file1))
            utils.pickle_dump(self.mol, str(save_dir / self.pickle_file1))
            mark("eq1", eq1_required)
            utils.radon_print(
                f"Complete packing simulation (eq1). Elapsed time = {datetime.datetime.now() - started}",
                level=1,
            )

        eq2_required = (
            save_dir / self.pickle_file2,
            save_dir / self.json_file2,
            work_dir / self.last_data2,
            work_dir / self.log_file2,
        )
        if completed("eq2", eq2_required):
            utils.radon_print("Resuming after completed compression/decompression equilibration (eq2).", level=1)
            self.mol = utils.pickle_load(str(save_dir / self.pickle_file2))
        else:
            started = datetime.datetime.now()
            utils.radon_print(
                "Larsen's 21 step compression/decompression equilibration (eq2) by LAMMPS is running...",
                level=1,
            )
            md2 = self.eq21step(
                max_temp=max_temp,
                temp=temp,
                press=press,
                max_press=max_press,
                step_list=step_list,
                press_ratio=press_ratio,
                time_step=time_step,
                set_init_velocity=True,
                **kwargs,
            )
            input_path = work_dir / self.in_file2
            partial = _select_partial_restart(
                work_dir,
                input_path,
                work_dir / self.log_file2,
                lmp.solver_path,
            )
            if partial is None:
                self.mol = lmp.run(
                    md2,
                    mol=self.mol,
                    confId=confId,
                    input_file=self.in_file2,
                    last_str=self.last_str2,
                    last_data=self.last_data2,
                    omp=omp,
                    mpi=mpi,
                    gpu=gpu,
                    intel=intel,
                    opt=opt,
                )
            else:
                restart_path, restart_step = partial
                resume_input, total_steps = build_lammps_resume_input(
                    input_path.read_text(),
                    restart_file=restart_path.name,
                    restart_step=restart_step,
                    log_file=self.log_file2,
                )
                resume_path = work_dir / "eq2_resume.in"
                resume_path.write_text(resume_input)
                _atomic_checkpoint(
                    checkpoint_dir / "eq2_partial_resume.json",
                    {
                        "stage": "eq2_partial_resume",
                        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
                        "original_input_sha256": _sha256(input_path),
                        "restart_file": restart_path.name,
                        "restart_sha256": _sha256(restart_path),
                        "restart_step": restart_step,
                        "total_steps": total_steps,
                        "requested_mpi": mpi,
                        "requested_omp": omp,
                    },
                )
                utils.radon_print(
                    f"Resuming eq2 from binary restart step {restart_step}/{total_steps} with MPI={mpi}.",
                    level=1,
                )
                completed_run = lmp.exec(
                    input_file=resume_path.name,
                    output_file="eq2_resume.out",
                    omp=omp,
                    mpi=mpi,
                    gpu=gpu,
                    intel=intel,
                    opt=opt,
                )
                if completed_run.returncode != 0:
                    raise RuntimeError(
                        f"LAMMPS eq2 partial resume failed with return code {completed_run.returncode}"
                    )
                last_dump = work_dir / self.last_str2
                if not last_dump.is_file():
                    raise RuntimeError("LAMMPS eq2 partial resume did not write the required final dump")
                uwstr, _, cell, vel, _ = lmp.read_traj_simple(str(last_dump))
                for atom_index in range(self.mol.GetNumAtoms()):
                    self.mol.GetConformer(confId).SetAtomPosition(
                        atom_index,
                        Geom.Point3D(*uwstr[atom_index]),
                    )
                    atom = self.mol.GetAtomWithIdx(atom_index)
                    atom.SetDoubleProp("vx", vel[atom_index, 0])
                    atom.SetDoubleProp("vy", vel[atom_index, 1])
                    atom.SetDoubleProp("vz", vel[atom_index, 2])
                if hasattr(self.mol, "cell"):
                    self.mol.cell = utils.Cell(
                        cell[0, 1],
                        cell[0, 0],
                        cell[1, 1],
                        cell[1, 0],
                        cell[2, 1],
                        cell[2, 0],
                    )
                    self.mol = calc.mol_trans_in_cell(self.mol, confId=confId)
            utils.MolToJSON(self.mol, str(save_dir / self.json_file2))
            utils.pickle_dump(self.mol, str(save_dir / self.pickle_file2))
            mark("eq2", eq2_required)
            utils.radon_print(
                "Complete Larsen 21 step compression/decompression equilibration "
                f"(eq2). Elapsed time = {datetime.datetime.now() - started}",
                level=1,
            )

        eq3_required = (
            save_dir / self.pickle_file,
            save_dir / self.json_file,
            work_dir / self.last_data,
            work_dir / self.log_file,
        )
        if completed("eq3", eq3_required):
            utils.radon_print("Resuming after completed sampling simulation (eq3).", level=1)
            self.mol = utils.pickle_load(str(save_dir / self.pickle_file))
        else:
            started = datetime.datetime.now()
            utils.radon_print("Sampling simulation (eq3) by LAMMPS is running...", level=1)
            md3 = self.sampling(temp=temp, press=press, step=int(1_000_000 * eq_step), **kwargs)
            input_path = work_dir / self.in_file
            partial = _select_partial_restart(
                work_dir,
                input_path,
                work_dir / self.log_file,
                lmp.solver_path,
            )
            if partial is None:
                self.mol = lmp.run(
                    md3,
                    mol=self.mol,
                    confId=confId,
                    input_file=self.in_file,
                    last_str=self.last_str,
                    last_data=self.last_data,
                    omp=omp,
                    mpi=mpi,
                    gpu=gpu,
                    intel=intel,
                    opt=opt,
                )
            else:
                restart_path, restart_step = partial
                resume_input, total_steps = build_lammps_resume_input(
                    input_path.read_text(),
                    restart_file=restart_path.name,
                    restart_step=restart_step,
                    log_file=self.log_file,
                )
                resume_path = work_dir / "eq3_resume.in"
                resume_path.write_text(resume_input)
                archived_outputs = _archive_partial_outputs(
                    work_dir,
                    tuple(name for name in (self.dump_file, self.xtc_file, self.rg_file) if name),
                    restart_step,
                )
                _atomic_checkpoint(
                    checkpoint_dir / "eq3_partial_resume.json",
                    {
                        "stage": "eq3_partial_resume",
                        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
                        "original_input_sha256": _sha256(input_path),
                        "restart_file": restart_path.name,
                        "restart_sha256": _sha256(restart_path),
                        "restart_step": restart_step,
                        "total_steps": total_steps,
                        "requested_mpi": mpi,
                        "requested_omp": omp,
                        "archived_outputs": archived_outputs,
                    },
                )
                utils.radon_print(
                    f"Resuming eq3 from binary restart step {restart_step}/{total_steps} with MPI={mpi}.",
                    level=1,
                )
                completed_run = lmp.exec(
                    input_file=resume_path.name,
                    output_file="eq3_resume.out",
                    omp=omp,
                    mpi=mpi,
                    gpu=gpu,
                    intel=intel,
                    opt=opt,
                )
                if completed_run.returncode != 0:
                    raise RuntimeError(
                        f"LAMMPS eq3 partial resume failed with return code {completed_run.returncode}"
                    )
                last_dump = work_dir / self.last_str
                if not last_dump.is_file():
                    raise RuntimeError("LAMMPS eq3 partial resume did not write the required final dump")
                uwstr, _, cell, vel, _ = lmp.read_traj_simple(str(last_dump))
                for atom_index in range(self.mol.GetNumAtoms()):
                    self.mol.GetConformer(confId).SetAtomPosition(
                        atom_index,
                        Geom.Point3D(*uwstr[atom_index]),
                    )
                    atom = self.mol.GetAtomWithIdx(atom_index)
                    atom.SetDoubleProp("vx", vel[atom_index, 0])
                    atom.SetDoubleProp("vy", vel[atom_index, 1])
                    atom.SetDoubleProp("vz", vel[atom_index, 2])
                if hasattr(self.mol, "cell"):
                    self.mol.cell = utils.Cell(
                        cell[0, 1],
                        cell[0, 0],
                        cell[1, 1],
                        cell[1, 0],
                        cell[2, 1],
                        cell[2, 0],
                    )
                    self.mol = calc.mol_trans_in_cell(self.mol, confId=confId)
            utils.MolToJSON(self.mol, str(save_dir / self.json_file))
            utils.pickle_dump(self.mol, str(save_dir / self.pickle_file))
            mark("eq3", eq3_required)
            utils.radon_print(
                f"Complete sampling simulation (eq3). Elapsed time = {datetime.datetime.now() - started}",
                level=1,
            )

        return self.mol

    exec_with_resume._polymer_lab_resume = True
    eq.EQ21step.exec = exec_with_resume
