from __future__ import annotations

import pytest

from polymer_lab.radonpy_resume import build_lammps_resume_input

EQ_INPUT = """\
log eq2.log append
kspace_style pppm 1e-6
dielectric 1.0
special_bonds amber
pair_modify mix arithmetic
neighbor 2.0 bin
read_data eq2.data
restart 10000 radon_md_1.rst radon_md_2.rst

timestep 1.0
fix shake1 all shake 1e-4 1000 0 m 1.0
fix md1 all nvt temp 600 600 100
run 50000
unfix md1
unfix shake1

timestep 1.0
fix shake2 all shake 1e-4 1000 0 m 1.0
fix md2 all npt temp 300 300 100 iso 50000 50000 1000
run 100000
unfix md2
unfix shake2
write_dump all custom eq2_last.dump id x y z
write_data eq3.data
quit
"""


def test_build_lammps_resume_input_preserves_current_fix_and_future_protocol() -> None:
    resumed, total = build_lammps_resume_input(
        EQ_INPUT,
        restart_file="radon_md_2.rst",
        restart_step=70000,
    )

    assert total == 150000
    assert "read_restart radon_md_2.rst" in resumed
    assert "read_data eq2.data" not in resumed
    assert "kspace_style pppm 1e-6" in resumed
    assert "special_bonds amber" in resumed
    assert "neigh_modify delay 0 every 1 check yes" not in resumed
    assert "fix md1" not in resumed
    assert "fix md2 all npt" in resumed
    assert "run 80000" in resumed
    assert "write_dump all custom eq2_last.dump" in resumed
    assert "write_data eq3.data" in resumed


@pytest.mark.parametrize("restart_step", [0, 150000, 150001])
def test_build_lammps_resume_input_rejects_nonresumable_steps(restart_step: int) -> None:
    with pytest.raises(ValueError):
        build_lammps_resume_input(
            EQ_INPUT,
            restart_file="radon_md_1.rst",
            restart_step=restart_step,
        )


EQ3_INPUT = """\
log eq3.log append
kspace_style pppm 1e-6
dielectric 1.0
special_bonds amber
pair_modify mix arithmetic
neighbor 2.0 bin
neigh_modify delay 0 every 1 check yes
read_data eq3.data

thermo_style custom step temp
thermo 1000
dump dump0 all custom 1000 eq3.dump id type x y z
dump xtc0 all xtc 1000 eq3.xtc
dump_modify xtc0 unwrap yes
restart 10000 radon_md_1.rst radon_md_2.rst

timestep 1.0
compute cmol1 all chunk/atom molecule
fix rg1 all ave/time 1 1000 1000 c_gyr1 file rg3.profile mode vector
fix msd1 all ave/time 1 1000 1000 c_msd1[4] mode scalar
variable msd equal f_msd1
fix md1 all npt temp 300 300 100 iso 1 1 1000
thermo_style custom step temp v_msd
thermo 1000
run 5000000
unfix md1
write_dump all custom eq3_last.dump id x y z
write_data eq3_last.data
quit
"""


def test_build_eq3_resume_restores_outputs_and_continues_remaining_sampling() -> None:
    resumed, total = build_lammps_resume_input(
        EQ3_INPUT,
        restart_file="radon_md_1.rst",
        restart_step=650000,
        log_file="eq3.log",
    )

    assert total == 5000000
    assert "log eq3.log append" in resumed
    assert "read_restart radon_md_1.rst" in resumed
    assert "read_data eq3.data" not in resumed
    assert resumed.count("restart 10000 radon_md_1.rst radon_md_2.rst") == 1
    assert "dump dump0 all custom 1000 eq3.dump" in resumed
    assert "dump xtc0 all xtc 1000 eq3.xtc" in resumed
    assert "compute cmol1 all chunk/atom molecule" in resumed
    assert "fix rg1 all ave/time" in resumed
    assert "fix md1 all npt" in resumed
    assert "run 1000" in resumed
    assert "run 4349000" in resumed
    assert resumed.count("thermo_style") == 3
    assert "write_dump all custom eq3_last.dump" in resumed
    assert "write_data eq3_last.data" in resumed


def test_eq3_resume_can_be_capped_for_stateful_smoke_test() -> None:
    resumed, total = build_lammps_resume_input(
        EQ3_INPUT,
        restart_file="radon_md_1.rst",
        restart_step=650000,
        log_file="eq3-smoke.log",
        max_resume_steps=2000,
    )

    assert total == 5000000
    assert resumed.count("run 1000") == 2
    assert "run 4349000" not in resumed
