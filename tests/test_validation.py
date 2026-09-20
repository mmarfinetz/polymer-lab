from __future__ import annotations

import pytest

from polymer_lab.errors import ValidationError
from polymer_lab.validation import BasicPSmilesValidator, unique_candidates


def test_basic_validator_requires_two_attachment_points() -> None:
    validator = BasicPSmilesValidator()
    with pytest.raises(ValidationError, match="exactly two"):
        validator.validate("[*]CC")
    with pytest.raises(ValidationError, match="exactly two"):
        validator.validate("[*]C([*])C[*]")


def test_basic_validator_rejects_mixtures_and_creates_stable_identity() -> None:
    validator = BasicPSmilesValidator()
    with pytest.raises(ValidationError, match="mixtures"):
        validator.validate("[*]CC[*].O")
    first = validator.validate("[*] CC [*]")
    second = validator.validate("[*]CC[*]")
    assert first.structure_hash == second.structure_hash
    assert len(unique_candidates([first, second])) == 1
