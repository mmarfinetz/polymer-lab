"""Catch broken chain identity and missing caps before spending Betty time."""

from __future__ import annotations

import math
from collections import defaultdict

from polymer_lab.finite_chain import generate_finite_chain_data


def test_finite_segment_has_continuous_capped_backbones(tmp_path):
    path = tmp_path / "capped.data"
    report = generate_finite_chain_data(path)
    assert report["molecule_count"] == 48
    assert report["atom_count"] == 4704
    assert math.isclose(report["molecular_weight_g_mol"], 450.88)
    lines = path.read_text().split("Atoms # molecular\n\n", 1)[1].splitlines()
    atoms = [tuple(float(field) for field in line.split()) for line in lines]
    molecules = defaultdict(list)
    for atom in atoms:
        molecules[int(atom[1])].append(atom)
    assert len(molecules) == 48
    box_x, box_y, _ = report["box_lengths_angstrom"]
    for chain in molecules.values():
        carbons = sorted((atom for atom in chain if int(atom[2]) == 1), key=lambda atom: atom[5])
        assert len(carbons) == 32
        assert len(chain) == 98
        for left, right in zip(carbons, carbons[1:], strict=False):
            dx = right[3] - left[3]
            dy = right[4] - left[4]
            dx -= round(dx / box_x) * box_x
            dy -= round(dy / box_y) * box_y
            distance = math.sqrt(dx * dx + dy * dy + (right[5] - left[5]) ** 2)
            assert 1.4 < distance < 1.7
