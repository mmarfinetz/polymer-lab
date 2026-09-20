from __future__ import annotations

import json
import math

import pytest

from polymer_lab.pe_reference import (
    PECrystalStructure,
    PEReferenceProtocol,
    analyze_pe_reference_replicate,
    generate_pe_crystal_data,
    parse_lammps_thermo,
    render_pe_reference_inputs,
)


def test_pe_structure_density_and_crystallographic_geometry(tmp_path) -> None:
    structure = PECrystalStructure()
    data = tmp_path / "pe.data"
    report = generate_pe_crystal_data(data, structure)

    assert structure.atom_count == 3456
    assert report["carbon_count"] == 1152
    assert report["hydrogen_count"] == 2304
    assert structure.unit_cell_density_g_cm3 == pytest.approx(0.998, abs=0.01)
    assert min(report["box_lengths_angstrom"]) > 20.4

    atom_lines = data.read_text().split("Atoms # atomic\n\n", 1)[1].splitlines()
    coordinates = []
    for line in atom_lines[:12]:
        _, atom_type, x, y, z = line.split()
        coordinates.append((int(atom_type), float(x), float(y), float(z)))
    carbon = [item for item in coordinates if item[0] == 1]
    hydrogen = [item for item in coordinates if item[0] == 2]
    assert len(carbon) == 4
    assert len(hydrogen) == 8

    lengths = (
        structure.lattice_a_angstrom,
        structure.lattice_b_angstrom,
        structure.lattice_c_angstrom,
    )

    def periodic_distance(left, right):
        components = []
        for index, length in enumerate(lengths, start=1):
            delta = left[index] - right[index]
            delta -= round(delta / length) * length
            components.append(delta)
        return math.sqrt(sum(value * value for value in components))

    nearest_cc = min(periodic_distance(carbon[0], item) for item in carbon[1:])
    nearest_ch = min(periodic_distance(carbon[0], item) for item in hydrogen)
    assert nearest_cc == pytest.approx(1.53, abs=0.03)
    assert nearest_ch == pytest.approx(1.09, abs=0.03)


def test_reference_protocol_and_restartable_inputs(tmp_path) -> None:
    protocol = PEReferenceProtocol()
    structure = PECrystalStructure()
    data = tmp_path / "pe.data"
    potential = tmp_path / "CH.airebo-m"
    potential.write_text("test potential")
    generate_pe_crystal_data(data, structure)
    inputs = render_pe_reference_inputs(
        output=tmp_path,
        data_path=data,
        potential_path=potential,
        seed=104729,
        protocol=protocol,
    )

    assert protocol.maximum_engineering_strain == pytest.approx(0.03)
    assert set(inputs) == {"00_minimize.in", "01_ramp.in", "02_stability.in", "03_tensile.in"}
    assert "pair_style airebo/morse 3.0" in inputs["00_minimize.in"].read_text()
    assert "read_restart" in inputs["01_ramp.in"].read_text()
    tensile = inputs["03_tensile.in"].read_text()
    assert "z erate 0.002" in tensile
    assert "-pzz*0.0001" in tensile
    assert "couple xy" in tensile


def test_reference_analysis_pass_and_fail(tmp_path) -> None:
    structure = PECrystalStructure()
    for stage in ("00_minimize", "01_ramp", "02_stability", "03_tensile"):
        (tmp_path / f"{stage}.complete").write_text("{}\n")
        (tmp_path / f"{stage}.in").write_text("input\n")
        (tmp_path / f"{stage}.stdout").write_text("stdout\n")
    (tmp_path / "structure.json").write_text(json.dumps(structure.model_dump(mode="json")))
    stability_header = "Step Temp Press Density Lx Ly Lz PotEng KinEng TotEng Pxx Pyy Pzz"
    stability_rows = []
    for index in range(501):
        density = structure.unit_cell_density_g_cm3 + (index % 2) * 1.0e-5
        stability_rows.append(
            f"{index * 500} {300 + (index % 2) * 0.1} 0 {density} "
            f"{structure.lattice_a_angstrom * structure.replicate_a} "
            f"{structure.lattice_b_angstrom * structure.replicate_b} "
            f"{structure.lattice_c_angstrom * structure.replicate_c} -1 1 0 0 0 0"
        )
    (tmp_path / "02_stability.log").write_text(
        stability_header + "\n" + "\n".join(stability_rows) + "\nLoop time of 1\n"
    )
    tensile_header = (
        "Step v_engineering_strain v_true_strain v_axial_gpa Temp Density "
        "v_transverse_bar Lx Ly Lz Pxx Pyy Pzz PotEng TotEng"
    )
    tensile_rows = []
    for index in range(1501):
        strain = index * 0.00002
        stress = 235 * strain + 0.01
        tensile_rows.append(
            f"{index * 50} {strain} {math.log1p(strain)} {stress} 300 "
            f"{structure.unit_cell_density_g_cm3} 0 1 1 1 0 0 {-stress * 10000} -1 0"
        )
    (tmp_path / "03_tensile.log").write_text(
        tensile_header + "\n" + "\n".join(tensile_rows) + "\nLoop time of 1\n"
    )

    parsed = parse_lammps_thermo(tmp_path / "02_stability.log", tuple(stability_header.split()))
    result = analyze_pe_reference_replicate(output=tmp_path, seed=104729)
    assert len(parsed) == 501
    assert result.passed
    assert result.axial_modulus_gpa == pytest.approx(235)
    assert result.modulus_fit_r2 == pytest.approx(1)
    assert not result.admissible_as_candidate_measurement

    bad_rows = [row.replace(" 300 ", " 400 ") for row in tensile_rows]
    # Tensile temperature is diagnostic; make the stability temperature fail instead.
    (tmp_path / "02_stability.log").write_text(
        stability_header + "\n" + "\n".join(row.replace(" 300", " 400", 1) for row in stability_rows) + "\n"
    )
    failed = analyze_pe_reference_replicate(output=tmp_path, seed=104729)
    assert not failed.passed
    assert "temperature" in failed.failed_checks
    assert bad_rows  # Keep explicit proof that tensile rows are independent of the stability gate.
