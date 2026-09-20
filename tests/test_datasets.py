from __future__ import annotations

import pytest
from pydantic import ValidationError

from polymer_lab.datasets import (
    PropertyColumn,
    load_experimental_csv,
    load_radonpy_pi1070,
)
from polymer_lab.models import PropertyName, Provenance
from polymer_lab.validation import BasicPSmilesValidator


def test_experimental_loader_requires_explicit_units_and_preserves_provenance(tmp_path) -> None:
    source = tmp_path / "properties.csv"
    source.write_text("PSMILES,Tg_K,density\n[*]CC[*],250,0.9\n[*]COC[*],,1.1\ninvalid,300,1.0\n")
    batch = load_experimental_csv(
        source,
        BasicPSmilesValidator(),
        property_columns={
            "Tg_K": PropertyColumn(property=PropertyName.TG, unit="degC", offset=-273.15),
            "density": PropertyColumn(property=PropertyName.DENSITY, unit="g/cm^3"),
        },
        dataset_name="fixture",
    )
    assert len(batch.candidates) == 2
    assert len(batch.observations) == 3
    assert len(batch.report.rejected) == 1
    tg = next(item for item in batch.observations if item.property == PropertyName.TG)
    assert round(tg.value, 2) == -23.15
    assert tg.source_reference is None


def test_experimental_rows_are_ingested_atomically(tmp_path) -> None:
    source = tmp_path / "invalid-row.csv"
    source.write_text("PSMILES,Tg,density\n[*]CC[*],250,not-a-number\n")
    batch = load_experimental_csv(
        source,
        BasicPSmilesValidator(),
        property_columns={
            "Tg": PropertyColumn(property=PropertyName.TG, unit="degC"),
            "density": PropertyColumn(property=PropertyName.DENSITY, unit="g/cm^3"),
        },
    )
    assert batch.candidates == ()
    assert batch.observations == ()
    assert len(batch.report.rejected) == 1


def test_property_columns_require_canonical_output_units() -> None:
    with pytest.raises(ValidationError, match="canonical unit"):
        PropertyColumn(property=PropertyName.TG, unit="K")


def test_radonpy_density_loader_keeps_md_provenance(tmp_path) -> None:
    source = tmp_path / "pi1070.csv"
    source.write_text(
        "monomer_ID,smiles,density,density_std,temp,press,tacticity,DP\nPI1,*CC*,0.84,0.01,300,1,none,165\n"
    )
    batch = load_radonpy_pi1070(source, BasicPSmilesValidator())
    assert len(batch.candidates) == 1
    assert len(batch.observations) == 1
    assert batch.observations[0].provenance == Provenance.MD
