"""PSMILES validation and canonical identity construction."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import DependencyUnavailable, ValidationError
from .models import PolymerCandidate, stable_hash

ATTACHMENT_RE = re.compile(r"\[(?:\*|\*:\d+)\]|(?<!\[)\*(?![^\[]*\])")


class BasicPSmilesValidator:
    """Dependency-free guardrail used by tests; production must use RDKitPSmilesValidator."""

    def __init__(self, *, max_length: int = 500) -> None:
        self.max_length = max_length

    def validate(
        self,
        psmiles: str,
        *,
        parent_ids: Sequence[str] = (),
        generation_method: str = "seed",
        generation: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> PolymerCandidate:
        cleaned = "".join(psmiles.split())
        if not cleaned:
            raise ValidationError("PSMILES cannot be empty")
        if len(cleaned) > self.max_length:
            raise ValidationError(f"PSMILES exceeds {self.max_length} characters")
        if "." in cleaned:
            raise ValidationError("v1 accepts one connected repeat unit, not mixtures")
        if len(ATTACHMENT_RE.findall(cleaned)) != 2:
            raise ValidationError("a linear homopolymer repeat unit requires exactly two attachment atoms")
        if cleaned.count("(") != cleaned.count(")") or cleaned.count("[") != cleaned.count("]"):
            raise ValidationError("unbalanced PSMILES delimiters")
        canonical = cleaned.replace("[*:1]", "[*]").replace("[*:2]", "[*]")
        structure_hash = stable_hash({"psmiles": canonical, "architecture": "linear_homopolymer"})
        return PolymerCandidate(
            psmiles=psmiles,
            canonical_psmiles=canonical,
            structure_hash=structure_hash,
            parent_ids=tuple(parent_ids),
            generation_method=generation_method,
            generation=generation,
            metadata={**(metadata or {}), "validator": "basic-non-scientific"},
        )


class RDKitPSmilesValidator:
    """Scientific candidate validator with valence, connectivity, and element checks."""

    def __init__(
        self,
        *,
        allowed_atomic_numbers: set[int] | None = None,
        max_heavy_atoms: int = 120,
    ) -> None:
        try:
            from rdkit import Chem
        except ImportError as exc:
            raise DependencyUnavailable(
                "RDKit is required for scientific validation; install polymer-lab[science]"
            ) from exc
        self.Chem = Chem
        self.allowed_atomic_numbers = allowed_atomic_numbers or {
            1,
            5,
            6,
            7,
            8,
            9,
            14,
            15,
            16,
            17,
            35,
        }
        self.max_heavy_atoms = max_heavy_atoms

    def validate(
        self,
        psmiles: str,
        *,
        parent_ids: Sequence[str] = (),
        generation_method: str = "seed",
        generation: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> PolymerCandidate:
        cleaned = "".join(psmiles.split())
        molecule = self.Chem.MolFromSmiles(cleaned, sanitize=True)
        if molecule is None:
            raise ValidationError("RDKit could not parse or sanitize PSMILES")
        fragments = self.Chem.GetMolFrags(molecule)
        if len(fragments) != 1:
            raise ValidationError("v1 accepts one connected repeat unit")
        attachments = [atom for atom in molecule.GetAtoms() if atom.GetAtomicNum() == 0]
        if len(attachments) != 2:
            raise ValidationError("a linear homopolymer repeat unit requires exactly two dummy atoms")
        if any(atom.GetDegree() != 1 for atom in attachments):
            raise ValidationError("each attachment atom must have exactly one bond")
        heavy_atoms = [atom for atom in molecule.GetAtoms() if atom.GetAtomicNum() > 1]
        if not heavy_atoms or len(heavy_atoms) > self.max_heavy_atoms:
            raise ValidationError(f"repeat unit must contain 1-{self.max_heavy_atoms} heavy atoms")
        unsupported = sorted({atom.GetAtomicNum() for atom in molecule.GetAtoms()} - self.allowed_atomic_numbers - {0})
        if unsupported:
            raise ValidationError(f"unsupported atomic numbers: {unsupported}")
        canonical = self.Chem.MolToSmiles(molecule, canonical=True)
        structure_hash = stable_hash({"psmiles": canonical, "architecture": "linear_homopolymer"})
        return PolymerCandidate(
            psmiles=psmiles,
            canonical_psmiles=canonical,
            structure_hash=structure_hash,
            parent_ids=tuple(parent_ids),
            generation_method=generation_method,
            generation=generation,
            metadata={**(metadata or {}), "validator": "rdkit"},
        )


def unique_candidates(candidates: Sequence[PolymerCandidate]) -> list[PolymerCandidate]:
    seen: set[str] = set()
    result: list[PolymerCandidate] = []
    for candidate in candidates:
        if candidate.structure_hash not in seen:
            seen.add(candidate.structure_hash)
            result.append(candidate)
    return result
