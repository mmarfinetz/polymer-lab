# Fabrication plan: `fiber-bbd827e465e62664`

Status: **hypothesis ready for a controlled laboratory test**, not a validated or
production-qualified fiber. This document describes how to make and test the
candidate; it does not report that any candidate-specific specimen has been made.
The frozen candidate is in
[`runs/fiber-v1/discovery-v3/zone-draw-test-candidate.json`](../../runs/fiber-v1/discovery-v3/zone-draw-test-candidate.json)
and the predeclared comparison is in
[`configs/fiber-v1-zone-draw-test-v1.json`](../../configs/fiber-v1-zone-draw-test-v1.json).
Its design hash is
`bbd827e465e62664790a5f27bc7a86f81043e646106fdf1f81ae266f2aacaa19`.

## What is being made

The chemistry is **linear ultra-high-molecular-weight polyethylene (UHMWPE)**,
repeat unit `–CH₂–CH₂–` (`[*]CC[*]` in the project representation). This plan
starts with purchased UHMWPE resin; it does **not** specify or require
polymerizing ethylene. The procurement targets are number-average molecular
weight **Mn 1.5 million g/mol** and weight-average molecular weight
**Mw 3.0 million g/mol**. Verify the actual lot and distribution: these targets
are not measurements of a resin already in hand.

The output is a gel-spun, drawn **20 µm target-diameter monofilament**. A later
assembly step combines **3,200 filaments** with **25 turns/m** twist into a
**1.25 mm target-diameter bundle**, without a sheath or interphase. All three
dimensions are design targets, not observed values. This needs a heated,
solvent-compatible gel-spinning and drawing line; the project's aqueous
protein/coaxial spinneret is not suitable.

## Sequence for a laboratory pilot

1. **Qualify materials and the line.** Obtain a traceable linear-UHMWPE lot
   and record its supplier, grade, additives, and molecular-weight evidence.
   Record the paraffin-oil grade and the extraction solvent. Perform a line
   shakedown before the predeclared study; shakedown material must not be
   counted as an independent study batch.
2. **Prepare the spinning dope.** Make a mixture that is **5.0 wt% UHMWPE by
   total mixture mass** in paraffin oil. Heat and mix until the chosen lot is
   uniformly dissolved and its rheology is usable; record the actual
   dissolution temperature, duration, mixing history, atmosphere, and measured
   viscosity. The current design does *not* specify those values. Historical
   gel-spinning work supports 5 wt% UHMWPE/paraffin oil, but its operating
   window cannot be assumed to transfer unchanged to this resin and line.
3. **Gel-spin.** Extrude the homogeneous dope through a documented die with
   the **spinning zone at 170 °C**, logging die geometry, pressure, mass
   throughput, residence time, and take-up. Cool the emerging filament to
   **room temperature** to form the gel; record quench geometry and residence
   time. Reject broken, visibly irregular, or unstable filament as a process
   failure rather than silently replacing it with a successful specimen.
4. **Remove the oil and dry.** Extract paraffin oil from the cooled gel
   filament using **n-hexane in a separate, approved solvent-handling system**.
   Record extraction conditions, then dry using a predeclared length/tension
   condition and assay residual oil and hexane. Do not assume that drying at
   fixed length is benign: a published UHMWPE study reported excessive
   crazing under that condition. Inspect for crazing and other defects before
   drawing. The extraction duration, solvent exchange rate, and drying
   condition have not yet been selected for this candidate.
5. **Zone-draw the lead group.** Draw the dry filament at a **128 °C zone
   temperature**, **20 MPa nominal drawing stress**, and **1 mm/min heat-band
   speed** toward an **actual 24.5× length draw ratio**. Log how stress is
   defined and measured, the actual tension, zone dimensions, speeds, and
   draw ratio. Stop and record breakage or necking instability; a nominal
   machine setting is not evidence that the specified draw ratio was reached.
   Measure the final diameter distribution instead of assuming it is 20 µm.
6. **Make the controls separately.** Repeat with **25.5×** and **26.4×** zone
   draw ratios, holding the other declared setpoints fixed. These are separate
   candidate IDs (`fiber-2e54e2533e066d8a` and
   `fiber-3af5cbc6679fe713`), not replicates of the 24.5× design.
7. **Test monofilaments before bundling.** For each ratio, make **three
   independent spinning batches** and test **at least five tensile specimens
   per batch** at a fixed, reported gauge length and strain rate. Preserve raw
   force–extension curves, measured load-bearing area/diameter, break
   locations, density, solvent residue, and defect microscopy. Calculate
   strength, break strain, and toughness by integrating the measured
   stress–strain curve to break. A 24.5× group that cannot combine the needed
   strength with **at least 15% break strain** should not advance on the basis
   of a literature value from another specimen.
8. **Assemble and qualify only promising material.** Combine **3,200 matching
   filaments** at **25 turns/m**, without an interphase, and measure actual
   count, packing, twist, and bundle diameter. Test independent bundles from
   matching batches for straight tensile strength, break strain, toughness,
   knot and anchor retention, creep, fatigue, and behavior from **−20 to
   80 °C in humid air**. Record failures and specimen-level curves, not just
   group means. Only the exact tested formulation/process can be promoted.

For the nominal geometry, 3,200 circular 20 µm filaments occupy about **81.9%**
of a 1.25 mm circular bundle cross-section. Reaching **2 GPa gross bundle
stress** would require roughly **2.45 GPa filament stress even with ideal load
sharing**. This is a necessary geometric bound, not a strength prediction;
twist, defects, and unequal loading can make the requirement harder.

## Settings that must be frozen before a reproducible run

The candidate fixes composition and principal setpoints but **not** a complete
manufacturing traveler. Before the three-batch study, the lab must record and
predeclare at least: resin lot/Mn/Mw method and acceptable range; oil grade;
dissolution time/temperature and rheology acceptance; die bore/length;
extrusion pressure and throughput; quench distance/time; extraction duration
and residual-solvent limit; drying length/tension and endpoint; drawing-stress
definition and heat-band geometry; actual-ratio calculation; tensile gauge
length/strain rate/gripping; and bundle assembly tension. Equipment-specific
values should be set by a shakedown and documented, **not invented from the
candidate ID**. A change to a frozen design setpoint needs a new candidate
design hash; other study changes need a protocol amendment and separate
analysis.

## Go/no-go and safety

The [Fiber v1 target](../../runs/fiber-v1/target.json) requires a measured
bundle strength of at least **2 GPa** (4 GPa stretch goal), **15–40%** strain
at break, **>100 MJ/m³** toughness, **<1.3 g/cm³** density, **>10,000** load
cycles, and **>60%** knot efficiency, plus the declared diameter and
environmental tests. No current simulation or cited paper satisfies these
gates for `fiber-bbd827e465e62664`. The 1996 zone-drawn specimen reported
**2.63 GPa and 12.75% strain at 26.4×**; it missed this project's 15% strain
minimum and used a different complete spinning recipe. The 24.5× point is a
test of a strength–strain tradeoff, not an extrapolated result.

This is professional laboratory work. The 170 °C spinning zone, moving
filaments, and n-hexane extraction require local EHS review, appropriate
ventilation/closed solvent handling, ignition control, and solvent-waste
management. **Never route n-hexane through the hot spinning zone.** NIOSH
classifies n-hexane as a highly flammable liquid and lists peripheral
neuropathy among its health effects. A home-scale or aqueous-spinneret trial
is not an acceptable substitute for the equipment and controls above.

## Evidence behind the plan

- [Pennings et al., 1983](https://doi.org/10.1351/pac198355050777):
  gel-spinning/hot-drawing route with paraffin oil, quenching, extraction,
  and drawing. The route is precedent, not validation of this combined design.
- [Pennings et al., 1986](https://research.rug.nl/en/publications/high-speed-gel-spinning-of-ultra-high-molecular-weight-polyethyle/):
  5 wt% UHMWPE/paraffin-oil gel spinning and the reported fixed-length
  n-hexane drying/crazing issue.
- [Han et al., 1996](https://pubs.kist.re.kr/handle/201004/144249):
  5 wt% gel-spun UHMWPE zone-draw study; its 26.4×, 128 °C, 20 MPa,
  1 mm/min point yielded the published 2.63 GPa/12.75% specimen.
- [NIOSH n-hexane pocket guide](https://www.cdc.gov/niosh/npg/npgd0322.html):
  solvent flammability and exposure hazards.
- Testing should use an approved laboratory method appropriate to the
  specimen, such as the current
  [ASTM single-fiber](https://store.astm.org/d3822_d3822m-14r20.html) and
  [yarn/strand](https://store.astm.org/d2256_d2256m-21.html) standards;
  freeze the actual gauge, rate, gripping, conditioning, and analysis rules
  before measuring the comparison groups.
