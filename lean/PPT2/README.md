# PPT² — Lean 4 formalization scaffold

This is the Lean 4 lake project corresponding to the gaia-discovery
case `projects/ppt2_main` (PPT² conjecture: composing two PPT quantum
channels yields an entanglement-breaking channel).

## Status (committed snapshot)

- `lake build PPT2`: green (1997 jobs).
- Toolchain: `leanprover/lean4:v4.30.0-rc2`.
- Mathlib: `mathlib4 @ master` (see `lake-manifest.json` for pin).

## Top-level theorems & axiom closures

Axiom closures shown below exclude the Lean core triple
`{propext, Classical.choice, Quot.sound}`.

| Top-level result                          | Project axioms used                                      |
|-------------------------------------------|----------------------------------------------------------|
| `PPT2.measure_prepare_is_EB`              | none (real proof, P1)                                    |
| `PPT2.dephasing_is_measure_prepare`       | none (P4-pre)                                            |
| `PPT2.ppt_dephasing_is_EB` (P4 TARGET)    | none                                                     |
| `PPT2.EB_comp_left`                       | `choi_comp_left_formula` (HSR 2003 Prop. 1)              |
| `PPT2.EB_comp_right`                      | `choi_comp_right_formula` (HSR 2003 Prop. 1)             |
| `PPT2.ppt2_dim2`                          | `ppt_implies_eb_dim2` (Peres–Horodecki 1996)             |
|                                           | + `choi_comp_right_formula`                              |
| `PPT2.depolarizing_EB_threshold`          | `depolarizing_choi_separable` (King 2003 / HHHH 2009)    |
| `PPT2.ppt2_conjecture_dim2`               | `ppt_implies_eb_dim2` + `choi_comp_right_formula`        |
| `PPT2.ppt2_dim3` (P7 statement)           | `sorry` (Christandl–Müller-Hermes–Wolf 2019, deferred)   |

Each remaining project axiom is documented at its declaration site with
its literature source.

## Repro

```bash
cd lean/PPT2
elan toolchain install leanprover/lean4:v4.30.0-rc2
lake exe cache get  # mathlib pre-built oleans
lake build PPT2
lake env lean -e 'import PPT2 #print axioms PPT2.ppt_dephasing_is_EB'
```
