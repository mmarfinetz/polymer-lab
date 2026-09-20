# Fiber v1: candidate for a controlled laboratory test

Candidate `fiber-bbd827e465e62664` is a single-chemistry, gel-spun UHMWPE
bundle. Its repeat unit is `[*]CC[*]`. Target resin specifications are
Mn = 1.5 million and Mw = 3.0 million g/mol. These are purchase and verification
specifications, not measured properties of a batch.

The proposed first point is 5 wt% UHMWPE in paraffin oil, spun at 170 °C,
quenched at room temperature, extracted with n-hexane, dried, and zone drawn
at 128 °C, 20 MPa and a 1 mm/min heat-band speed to a 24.5 draw ratio. Target
filament diameter is 20 µm. Assemble 3,200 filaments into a 1.25 mm bundle at
25 turns/m, without an interphase. Record the actual resin, die, throughput,
extraction time, residual solvent, and dimensions for every batch. This route
requires a heated solvent-compatible gel-spinning and drawing line; the aqueous
protein coaxial spinneret is not the appropriate apparatus.

Why this point: a published 5 wt% gel-spun UHMWPE zone-drawing study measured
2.63 GPa tensile strength and 12.75% breaking strain at draw ratio 26.4,
128 °C, 20 MPa and 1 mm/min. The lower 24.5 ratio is a *test hypothesis* for
gaining strain while keeping strength. The published sample still missed our
15% strain target, and it used a different full spinning recipe. Its values
must not be assigned to this candidate.

Geometry gives 0.819 filament area fraction in the 1.25 mm bundle. Even with
ideal load sharing and negligible twist loss, a filament must reach about
2.45 GPa for the bundle to reach 2 GPa. This is a necessary bound, not a
prediction. The old 75/25 high-/low-draw bundle at 25 turns/m provides at most
0.52% outer-filament path-length slack. Under favorable published constituent
strength and failure-strain values, its rectangular-envelope work to 15%
strain is at most 77.7 MJ/m³, below the 100 MJ/m³ target. That conditional
screen is why this single-chemistry zone-draw experiment takes priority.

Test three separately identified draw ratios: 24.5 (lead), 25.5 and 26.4
(controls). Use three independent spinning batches per ratio and at least five
tensile specimens per batch. Test single filaments first, then matching
3,200-filament bundles. Integrate each measured stress–strain curve to failure
for toughness. If a group cannot reach the necessary filament strength and
15% strain together, stop before expensive bundle and environmental tests.
For promising groups, measure bundle strength, toughness, density, knot and
anchor efficiency, fatigue beyond 10,000 cycles, creep, and performance at
−20 °C and 80 °C in humid air. Add an interphase only if measured interface
slip or load-transfer loss justifies it. The full frozen protocol is
`configs/fiber-v1-zone-draw-test-v1.json`.

Readiness: **controlled laboratory test**. Production qualification remains
open until matching specimens pass every target. No strength, strain,
toughness, fatigue or knot result has been measured for this candidate.

Primary sources: [zone-drawn UHMWPE study](https://pubs.kist.re.kr/handle/201004/144249),
[gel-spinning study](https://citeseerx.ist.psu.edu/document?doi=b78f189de926fd0c87e2d80e19853415bd2342be&repid=rep1&type=pdf),
[draw-ratio strength/strain study](https://doi.org/10.1021/acsomega.3c09230),
and [NIST temperature/strain-rate tests](https://www.nist.gov/publications/investigation-temperature-and-strain-rate-effects-strain-failure-uhmwpe-fibers).
