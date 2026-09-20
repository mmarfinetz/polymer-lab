"""Capped finite PE segments for chain-end physics reference tests.

The default C32 chains are oligomers, not million-Da UHMWPE. These simulations
probe chain ends and validate the finite-chain workflow only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .models import stable_hash
from .pe_reference import (
    CARBON_MASS_AMU,
    HYDROGEN_MASS_AMU,
    PECrystalStructure,
    _wyckoff_positions,
    file_sha256,
)


def _unit(values: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(value * value for value in values))
    if length <= 0:
        raise ValueError("zero-length bond")
    return tuple(value / length for value in values)


def _minimum_image(value: float, length: float) -> float:
    return value - round(value / length) * length


def _bond_direction(
    other: dict[str, float | int], anchor: dict[str, float | int], box_x: float, box_y: float
) -> tuple[float, float, float]:
    return _unit((
        _minimum_image(float(other["x"]) - float(anchor["x"]), box_x),
        _minimum_image(float(other["y"]) - float(anchor["y"]), box_y),
        float(other["z"]) - float(anchor["z"]),
    ))


def generate_finite_chain_data(
    path: Path, repeats: int = 16, replicate_a: int = 4, replicate_b: int = 6
) -> dict[str, Any]:
    """Generate C(2N)H(4N+2) strands in an open-z PE crystalline slab."""
    if repeats < 4:
        raise ValueError("finite-chain reference requires at least four repeat cells")
    structure = PECrystalStructure(
        replicate_a=replicate_a, replicate_b=replicate_b, replicate_c=repeats
    )
    box_x = replicate_a * structure.lattice_a_angstrom
    box_y = replicate_b * structure.lattice_b_angstrom
    margin = 4.0
    box_z = repeats * structure.lattice_c_angstrom + 2 * margin
    sites = (
        (1, _wyckoff_positions(*structure.carbon_xy)),
        (2, _wyckoff_positions(*structure.hydrogen_1_xy)),
        (2, _wyckoff_positions(*structure.hydrogen_2_xy)),
    )
    atoms: list[dict[str, float | int]] = []
    carbons: dict[int, list[dict[str, float | int]]] = {}
    hydrogens: dict[tuple[int, int, int], list[dict[str, float | int]]] = {}
    for ia in range(replicate_a):
        for ib in range(replicate_b):
            for ic in range(repeats):
                for atom_type, positions in sites:
                    for op, (fx, fy, fz) in enumerate(positions):
                        # The first strand crosses the x/y crystallographic cell.
                        origin_a, origin_b = (
                            ((ia + 1) % replicate_a, (ib - 1) % replicate_b)
                            if op == 1 else (ia, ib)
                        )
                        strand = 0 if op in (0, 1) else 1
                        molecule = 2 * (origin_a * replicate_b + origin_b) + strand + 1
                        atom: dict[str, float | int] = {
                            "id": len(atoms) + 1,
                            "type": atom_type,
                            "molecule": molecule,
                            "x": (ia + fx) * structure.lattice_a_angstrom,
                            "y": (ib + fy) * structure.lattice_b_angstrom,
                            "z": margin + (ic + fz) * structure.lattice_c_angstrom,
                        }
                        atoms.append(atom)
                        if atom_type == 1:
                            carbons.setdefault(molecule, []).append(atom)
                        else:
                            hydrogens.setdefault((molecule, ic, op), []).append(atom)

    bottom_ids: list[int] = []
    top_ids: list[int] = []
    for molecule, strand_carbons in sorted(carbons.items()):
        ordered = sorted(strand_carbons, key=lambda atom: float(atom["z"]))
        if len(ordered) != 2 * repeats:
            raise RuntimeError(f"incomplete backbone for molecule {molecule}")
        for end, terminal, neighbor in (
            ("bottom", ordered[0], ordered[1]),
            ("top", ordered[-1], ordered[-2]),
        ):
            cell = 0 if end == "bottom" else repeats - 1
            op = (0 if molecule % 2 else 3) if end == "bottom" else (1 if molecule % 2 else 2)
            attached_h = hydrogens.get((molecule, cell, op), [])
            if len(attached_h) != 2:
                raise RuntimeError(f"terminal carbon {terminal['id']} needs two original hydrogens")

            vectors = [
                _bond_direction(atom, terminal, box_x, box_y)
                for atom in (neighbor, *attached_h)
            ]
            missing = _unit(tuple(-sum(vector[axis] for vector in vectors) for axis in range(3)))
            cap = {
                "id": len(atoms) + 1,
                "type": 2,
                "molecule": molecule,
                "x": (float(terminal["x"]) + 1.09 * missing[0]) % box_x,
                "y": (float(terminal["y"]) + 1.09 * missing[1]) % box_y,
                "z": float(terminal["z"]) + 1.09 * missing[2],
            }
            if not 0 < float(cap["z"]) < box_z:
                raise RuntimeError("hydrogen cap is outside the open-z box")
            atoms.append(cap)
            ids = bottom_ids if end == "bottom" else top_ids
            ids.extend([int(terminal["id"]), *(int(atom["id"]) for atom in attached_h), int(cap["id"])])

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Capped PE oligomer chain-end reference; not a UHMWPE fiber result", "",
        f"{len(atoms)} atoms", "2 atom types", "",
        f"0.0 {box_x:.12f} xlo xhi", f"0.0 {box_y:.12f} ylo yhi",
        f"0.0 {box_z:.12f} zlo zhi", "", "Masses", "",
        f"1 {CARBON_MASS_AMU}", f"2 {HYDROGEN_MASS_AMU}", "",
        "Atoms # molecular", "",
    ]
    lines.extend(
        f"{atom['id']} {atom['molecule']} {atom['type']} "
        f"{float(atom['x']):.12f} {float(atom['y']):.12f} {float(atom['z']):.12f}"
        for atom in atoms
    )
    path.write_text("\n".join(lines) + "\n")
    molecule_count = 2 * replicate_a * replicate_b
    if len(atoms) != molecule_count * (6 * repeats + 2):
        raise RuntimeError("capped chain atom count is inconsistent")
    return {
        "structure_hash": stable_hash({
            "base": structure.model_dump(mode="json"),
            "cap": "tetrahedral_completion_from_existing_C_C_and_two_C_H_vectors",
            "cap_bond_angstrom": 1.09, "open_z_margin_angstrom": margin,
        }),
        "atom_count": len(atoms), "molecule_count": molecule_count,
        "carbons_per_chain": 2 * repeats, "hydrogens_per_chain": 4 * repeats + 2,
        "molecular_weight_g_mol": 2 * repeats * CARBON_MASS_AMU + (4 * repeats + 2) * HYDROGEN_MASS_AMU,
        "box_lengths_angstrom": [box_x, box_y, box_z],
        "bottom_atom_ids": bottom_ids, "top_atom_ids": top_ids,
        "data_sha256": file_sha256(path),
        "scientific_scope": "capped short-chain PE defect reference, not UHMWPE or fiber strength",
    }


def write_finite_chain_protocol(path: Path, seed: int, smoke: bool = False) -> None:
    payload = {
        "version": "capped-pe-chain-end-reference-v2", "seed": seed,
        "repeats": 16, "replicate_a": 4, "replicate_b": 6,
        "timestep_fs": 0.2, "boundary": "p p f", "potential": "CH.airebo-m",
        "stages": {
            "minimize": 2_000 if smoke else 20_000,
            "ramp": 5_000 if smoke else 125_000,
            "stability": 10_000 if smoke else 250_000,
            "tensile": 5_000 if smoke else 75_000,
        },
        "pull_velocity_angstrom_per_ps": 0.08,
        "gauge_method": "end-group center-of-mass separation",
        "stress_method": "top-end reaction force divided by xy area",
        "scientific_scope": "short-chain PE defect reference only",
        "admissible_as_candidate_measurement": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
