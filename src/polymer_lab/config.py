"""Environment configuration without implicit secret loading."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_url: str = "sqlite:///polymer_lab.sqlite3"
    artifact_uri: str = "file://./artifacts"
    s3_endpoint: str | None = None
    openai_model: str = "gpt-5.6-terra"
    slurm_host: str | None = None
    slurm_workdir: Path | None = None

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            database_url=os.environ.get("POLYMER_LAB_DATABASE_URL", "sqlite:///polymer_lab.sqlite3"),
            artifact_uri=os.environ.get("POLYMER_LAB_ARTIFACT_URI", "file://./artifacts"),
            s3_endpoint=os.environ.get("POLYMER_LAB_S3_ENDPOINT"),
            openai_model=os.environ.get("POLYMER_LAB_OPENAI_MODEL", "gpt-5.6-terra"),
            slurm_host=os.environ.get("POLYMER_LAB_SLURM_HOST"),
            slurm_workdir=(
                Path(os.environ["POLYMER_LAB_SLURM_WORKDIR"]) if os.environ.get("POLYMER_LAB_SLURM_WORKDIR") else None
            ),
        )
