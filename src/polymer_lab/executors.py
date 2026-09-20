"""Local subprocess and Slurm executors."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import DependencyUnavailable
from .models import JobState, PhysicsJob


class LocalExecutor:
    def __init__(self, *, python_executable: str = sys.executable) -> None:
        self.python_executable = python_executable
        self.processes: dict[str, subprocess.Popen[bytes]] = {}

    def submit(self, job: PhysicsJob, manifest_path: Path) -> str:
        command = [
            self.python_executable,
            "-m",
            "polymer_lab.worker",
            "--manifest",
            str(manifest_path),
        ]
        log_path = manifest_path.with_suffix(".worker.log")
        with log_path.open("ab") as log_handle:
            process = subprocess.Popen(command, cwd=manifest_path.parent, stdout=log_handle, stderr=subprocess.STDOUT)
        external_id = f"local:{process.pid}"
        self.processes[external_id] = process
        return external_id

    def status(self, external_id: str) -> JobState:
        process = self.processes.get(external_id)
        if process is None:
            # Coordinator restarts lose Popen handles. Reattach by PID rather
            # than leaving a durable job falsely marked as running.
            try:
                pid = int(external_id.removeprefix("local:"))
            except ValueError as exc:
                raise KeyError(f"unknown local process {external_id}") from exc
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return JobState.FAILED
            except PermissionError:
                return JobState.RUNNING
            return JobState.RUNNING
        return_code = process.poll()
        if return_code is None:
            return JobState.RUNNING
        return JobState.SUCCEEDED if return_code == 0 else JobState.FAILED

    def cancel(self, external_id: str) -> None:
        process = self.processes.get(external_id)
        if process and process.poll() is None:
            process.terminate()


@dataclass(frozen=True)
class SlurmConfig:
    workdir: Path
    partition: str | None = None
    account: str | None = None
    qos: str | None = None
    time_limit: str = "48:00:00"
    ntasks: int = 1
    cpus_per_task: int = 16
    memory: str = "64G"
    memory_per_cpu: str | None = None
    python_executable: str = "python"
    remote_host: str | None = None
    environment_setup: str = ""


class SlurmExecutor:
    JOB_ID_RE = re.compile(r"Submitted batch job (\d+)")

    def __init__(self, config: SlurmConfig) -> None:
        self.config = config

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        if self.config.remote_host:
            command = ["ssh", self.config.remote_host, shlex.join(command)]
        try:
            return subprocess.run(command, check=True, text=True, capture_output=True)
        except FileNotFoundError as exc:
            raise DependencyUnavailable(f"scheduler command is unavailable: {command[0]}") from exc

    def _write_script(self, job: PhysicsJob, manifest_path: Path) -> Path:
        script_path = manifest_path.with_suffix(".sbatch")
        directives = [
            "#!/bin/bash",
            f"#SBATCH --job-name=polymer-{job.id[:8]}",
            f"#SBATCH --time={self.config.time_limit}",
            f"#SBATCH --ntasks={self.config.ntasks}",
            f"#SBATCH --cpus-per-task={self.config.cpus_per_task}",
            f"#SBATCH --output={manifest_path.with_suffix('.slurm-%j.out')}",
        ]
        if self.config.memory_per_cpu:
            directives.append(f"#SBATCH --mem-per-cpu={self.config.memory_per_cpu}")
        else:
            directives.append(f"#SBATCH --mem={self.config.memory}")
        if self.config.partition:
            directives.append(f"#SBATCH --partition={self.config.partition}")
        if self.config.account:
            directives.append(f"#SBATCH --account={self.config.account}")
        if self.config.qos:
            directives.append(f"#SBATCH --qos={self.config.qos}")
        body = [
            "set -euo pipefail",
            self.config.environment_setup,
            shlex.join(
                [
                    self.config.python_executable,
                    "-m",
                    "polymer_lab.worker",
                    "--manifest",
                    str(manifest_path),
                ]
            ),
        ]
        script_path.write_text("\n".join(directives + body) + "\n")
        return script_path

    def submit(self, job: PhysicsJob, manifest_path: Path) -> str:
        try:
            manifest_path.resolve().relative_to(self.config.workdir.resolve())
        except ValueError as exc:
            raise ValueError("Slurm manifests must live under the configured shared workdir") from exc
        script = self._write_script(job, manifest_path)
        completed = self._run(["sbatch", str(script)])
        match = self.JOB_ID_RE.search(completed.stdout)
        if not match:
            raise RuntimeError(f"could not parse sbatch output: {completed.stdout!r}")
        return match.group(1)

    def status(self, external_id: str) -> JobState:
        active = self._run(["squeue", "-h", "-j", external_id, "-o", "%T"])
        state = active.stdout.strip().upper()
        if state:
            return self._map_state(state)
        history = self._run(["sacct", "-n", "-X", "-j", external_id, "-o", "State"])
        state = history.stdout.strip().split()[0].upper() if history.stdout.strip() else "UNKNOWN"
        return self._map_state(state)

    @staticmethod
    def _map_state(state: str) -> JobState:
        if state in {"PENDING", "CONFIGURING"}:
            return JobState.SUBMITTED
        if state in {"RUNNING", "COMPLETING"}:
            return JobState.RUNNING
        if state == "COMPLETED":
            return JobState.SUCCEEDED
        if state in {"PREEMPTED", "REQUEUED", "REQUEUE_FED"}:
            return JobState.PREEMPTED
        if state in {"CANCELLED", "TIMEOUT"}:
            return JobState.CANCELLED
        return JobState.FAILED

    def cancel(self, external_id: str) -> None:
        self._run(["scancel", external_id])


class RecordingExecutor:
    """Test executor that records submissions without claiming scientific success."""

    def __init__(self) -> None:
        self.submissions: dict[str, tuple[PhysicsJob, Path]] = {}
        self.states: dict[str, JobState] = {}

    def submit(self, job: PhysicsJob, manifest_path: Path) -> str:
        external_id = f"recording:{len(self.submissions) + 1}"
        self.submissions[external_id] = (job, manifest_path)
        self.states[external_id] = JobState.SUBMITTED
        return external_id

    def status(self, external_id: str) -> JobState:
        return self.states[external_id]

    def cancel(self, external_id: str) -> None:
        self.states[external_id] = JobState.CANCELLED
