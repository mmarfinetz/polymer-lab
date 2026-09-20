from pathlib import Path

from polymer_lab.executors import LocalExecutor, SlurmConfig, SlurmExecutor
from polymer_lab.models import JobState, PhysicsJob, SimulationSpec
from polymer_lab.validation import BasicPSmilesValidator


def test_local_executor_reconciles_dead_pid_after_coordinator_restart() -> None:
    executor = LocalExecutor()
    assert executor.status("local:999999999") == JobState.FAILED


def test_slurm_executor_writes_qos_and_memory_per_cpu(tmp_path: Path) -> None:
    candidate = BasicPSmilesValidator().validate("[*]CC[*]")
    job = PhysicsJob(
        campaign_id="campaign",
        candidate=candidate,
        spec=SimulationSpec(),
        artifact_uri=tmp_path.as_uri(),
        estimated_core_hours=1,
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    executor = SlurmExecutor(
        SlurmConfig(
            workdir=tmp_path,
            qos="normal",
            ntasks=16,
            cpus_per_task=1,
            memory_per_cpu="5632M",
        )
    )

    script = executor._write_script(job, manifest).read_text()

    assert "#SBATCH --qos=normal" in script
    assert "#SBATCH --ntasks=16" in script
    assert "#SBATCH --cpus-per-task=1" in script
    assert "#SBATCH --mem-per-cpu=5632M" in script
    assert "#SBATCH --mem=" not in script
