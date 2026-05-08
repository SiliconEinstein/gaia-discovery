# act_89ad7f7eae2b -- Constant-Δ Approximation for Josephson Junctions

Action: `support` | Claim: `c_const_delta` | Router: `heuristic`

---

## Task Restatement

Justify why the components Δ_j = √(n_{s,j}/2) e^{iφ_j} of the two-component superconducting
wavefunction can be treated as spatially constant inside the bulk superconducting regions on
either side of the Josephson tunnel barrier. Each of the seven numbered points from the task
specification is addressed below.

---

## (1) Coherence Length ξ as the Characteristic Length Scale for |Δ| Variation

The **BCS coherence length** ξ is the fundamental length scale governing spatial variations
of the superconducting order parameter Δ(r).

### Microscopic (BCS) definition

In the clean limit (mean free path ℓ ≫ ξ₀), the BCS coherence length at T = 0 is

```
ξ₀ = ℏv_F / πΔ(0)
```

where v_F is the Fermi velocity and Δ(0) is the zero-temperature gap. For typical elemental
superconductors: ξ₀(Nb) ≈ 38 nm, ξ₀(Pb) ≈ 83 nm, ξ₀(Al) ≈ 1600 nm.

In the dirty limit (ℓ ≪ ξ₀), the effective coherence length is

```
ξ = √(ξ₀ ℓ)
```

### Physical origin

The BCS gap equation is nonlocal in space:

```
Δ(r) = V ∫ K(r, r') F(r') d³r'
```

where the kernel K(r, r') = Σ_k (e^{ik·(r−r')} / 2E_k) has range ∼ξ₀. Consequently, Δ(r)
at point r depends on the pair amplitude F(r') within a volume of radius ∼ξ₀ around r.
Any attempt to change Δ on a length scale shorter than ξ requires exponentially large
gradient energy (∝ |∇Δ|²), which is energetically forbidden in the ground state.

### Ginzburg-Landau coherence length

In GL theory, the free energy functional contains a gradient term:

```
F = ∫ [α|ψ|² + (β/2)|ψ|⁴ + (ℏ²/2m*)|∇ψ|²] d³r
```

The coefficient of the gradient term defines the GL coherence length:

```
ξ²(T) = ℏ² / (2m*|α|) = ξ₀² / (1 − T/T_c)
```

ξ(T) is the healing length: if ψ is perturbed at a point, it recovers to the bulk value
over a distance ∼ξ(T). This is the direct analog of the healing length in a
Bose-Einstein condensate (Pitaevskii & Stringari §5.2, §11.1).

**Conclusion**: ξ is the minimum distance over which |Δ| can change appreciably. Any
spatial variation of |Δ| is necessarily smooth on the scale of ξ.

---

## (2) Bulk Electrodes with d ≫ ξ: |Δ| Saturates to the Equilibrium BCS Gap Value

Consider an SIS Josephson junction with electrode thickness d on each side. The order
parameter amplitude |Δ(r)| satisfies the GL equation (or the BCS self-consistency equation)
subject to boundary conditions at the SN interface (superconductor-normal metal at the
barrier).

### Boundary behavior

At a superconductor-normal metal interface, the de Gennes boundary condition is:

```
(∇ψ/ψ) · n̂ = 1/b
```

where b is the extrapolation length (b → ∞ for insulating boundary, b finite for
metallic contact). For a tunnel barrier with low transparency (b large), the boundary
condition is approximately ∇ψ · n̂ ≈ 0 (zero-slope, fully-reflecting boundary).

### Exponential recovery to bulk value

Solving the linearized GL equation (valid near T_c) or the Usadel equation (valid at
all T) near the interface gives:

```
ψ(x) = ψ_∞ [1 − A e^{−x/ξ}]
```

where x is the distance from the interface, ψ_∞ = √(−α/β) is the bulk equilibrium
value, and A is a constant of order 1 determined by the boundary condition. The
recovery is exponential with characteristic length ξ.

### The d ≫ ξ condition

When the electrode thickness d ≫ ξ (e.g., d = 200 nm Nb, ξ ≈ 38 nm → d ≈ 5.3 ξ),
the perturbed boundary layer occupies only a small fraction ∼ξ/d ≈ 0.19 of the
electrode volume. The vast majority of the electrode has |Δ(r)| ≈ |Δ_eq| with
corrections of order exp(−d/ξ), which are exponentially suppressed.

For d = 5ξ, the midpoint of the electrode has |Δ| ≈ |Δ_eq| (1 − e^{−2.5}) ≈ 0.92|Δ_eq|,
and the spatial average ⟨|Δ|⟩ ≈ |Δ_eq| (1 − ξ/2d) ≈ 0.90|Δ_eq| — already dominated
by the bulk value. For thicker electrodes (d ≥ 10ξ), the approximation is even better.

---

## (3) ∇φ = 0 in Field-Free, Current-Free Bulk: Phase Uniformity from j_s ∝ n_s ∇φ

The supercurrent density in GL theory (no vector potential, A = 0) is:

```
j_s = (e*ℏ/m*) n_s ∇φ = (2eℏ/m*) n_s ∇φ
```

where e* = 2e is the Cooper pair charge and n_s = 2|ψ|² is the superfluid density.

### Phase gradient as driving force

This is the London-type constitutive relation: a phase gradient ∇φ drives a supercurrent.
Conversely, if no net supercurrent flows through a bulk region, then j_s = 0 everywhere
in that region, which forces:

```
∇φ(r) = 0   for all r in the region
```

Integrating: φ(r) = φ₀ = const (spatially uniform phase).

### Physical picture in the STJ geometry

In the STJ geometry, the tunnel barrier is a high-impedance element (tunnel resistance
R_N ∼ 10 Ω for a 10 μm² junction). The Josephson current I_s = I_c sin(φ₁ − φ₂) across
the barrier is supported by Cooper pair tunneling, not by a hydrodynamic supercurrent
flow within the electrodes. Within each electrode, far from the barrier, the supercurrent
density vanishes:

- Side 1: j_s,1 = 0 → ∇φ₁ = 0 → φ₁ = const
- Side 2: j_s,2 = 0 → ∇φ₂ = 0 → φ₂ = const

The Josephson tunneling current at the barrier is a boundary phenomenon that does not
require a gradient within the bulk reservoirs — the tunneling Hamiltonian couples the
two uniform phases directly.

### Distinction from finite-current scenario

When a net supercurrent does flow through an electrode (e.g., in a superconducting wire
connecting two junctions), ∇φ ≠ 0 and φ varies linearly with position. The current-phase
gradient relation then gives exactly the London equation. This is NOT the situation in
the STJ model, where the electrodes are isolated reservoirs.

---

## (4) GL Free-Energy Minimization: ∇²ψ = 0 ⇒ |ψ| = const in Uniform Regions

A complementary argument comes from variational minimization of the GL free energy.

### GL equation without fields

In the absence of magnetic fields (A = 0) and in a region where the GL coefficients α, β
are spatially uniform (homogeneous material, uniform temperature), the GL equation
δF/δψ* = 0 gives:

```
αψ + β|ψ|²ψ − (ℏ²/2m*)∇²ψ = 0
```

### Uniform-region simplification

Deep in the electrode bulk, |ψ| ≈ |ψ_∞| = √(−α/β), and the nonlinear term approximately
cancels the linear term: αψ + β|ψ_∞|²ψ ≈ 0. The residual equation is:

```
∇²ψ = 0
```

The Laplace equation ∇²ψ = 0 in a uniform medium has the general solution:

```
ψ(r) = a + b·r + higher multipoles
```

where a is a constant and b is a constant vector. In a finite, isolated region with
zero net current, regularity at the boundaries forces b = 0 (no linear drift) and
all higher multipoles to vanish. The unique regular solution is:

```
ψ(r) = const
```

Since ψ ∝ √(n_s/2) e^{iφ}, this implies both |ψ| = const and φ = const (up to a
global phase).

### Physical interpretation

The gradient term (ℏ²/2m*)|∇ψ|² in the free energy penalizes spatial variation of ψ.
In the absence of driving forces (currents, fields, temperature gradients), the system
minimizes this gradient energy by making ψ as uniform as possible. The constant solution
is the unique energy-minimizing configuration for an isolated superconducting region
under equilibrium conditions.

---

## (5) Distinguishing Magnitude Constancy from Phase Constancy

It is essential to recognize that |Δ| = const and φ = const are **independent** conditions
that must each be justified separately.

### Magnitude constancy: |Δ(r)| = |Δ_eq|

- **Mechanism**: governed by the coherence length ξ (premises 1–2) and GL healing-length argument (premise 4).
- **Physical origin**: the gap equation is nonlocal; |Δ| cannot vary on scales < ξ; far from interfaces (d ≫ ξ), it relaxes to the equilibrium value.
- **Violation scenario**: proximity effect near a normal-metal interface, non-equilibrium quasiparticle injection, or heating.

### Phase constancy: φ(r) = φ₀

- **Mechanism**: governed by the current-phase relation j_s ∝ n_s∇φ (premise 3) and Laplace equation (premise 4).
- **Physical origin**: without current flow, there is no driving force for a phase gradient; the minimum-gradient-energy configuration is φ = const.
- **Violation scenario**: flowing DC supercurrent through the electrode, or magnetic field (A ≠ 0, giving finite canonical momentum).

### Why both matter for the STJ model

The STJ ansatz Ψ = (|Δ₁|e^{iφ₁}, |Δ₂|e^{iφ₂})^T with constant parameters assumes:

1. |Δ₁|, |Δ₂| are constant (same n_{s,1}, n_{s,2} everywhere in each reservoir)
2. φ₁, φ₂ are constant within each reservoir (giving well-defined φ₁ − φ₂ across the junction)

If either condition fails, the simple two-level Hamiltonian description is inadequate.
For example, if φ₁ varies across electrode 1 (∇φ₁ ≠ 0), there is no single φ₁ to insert
into exp(iφ₁), and the tunneling matrix element K exp(iφ₁ − iφ₂) becomes ill-defined
without a spatial integral.

---

## (6) Breakdown Within ∼ξ of the Barrier -- and Why This Is Acceptable

### The boundary-perturbation region

Within a distance of order ξ from the tunnel barrier interface:

1. **Gap suppression**: |Δ(x)| is reduced from its bulk value due to the boundary
   condition at the SN interface. For a low-transparency barrier (specular reflection
   boundary condition), the suppression is weak (∼10⁻²); for higher transparency
   (finite b), the suppression scales as ∼b/ξ.

2. **Phase variation**: the Josephson tunneling current I_c sin(φ₁ − φ₂) is a
   conversion of supercurrent at the interface, requiring a local ∇φ near the
   barrier. However, the phase gradient extends only ∼ξ into each electrode.

3. **Andreev bound states**: Sub-gap states localized within ξ of the barrier modify
   the local density of states and contribute to the Josephson current (Beenakker
   & van Houten 1991). These states are confined to the boundary layer.

### Why the boundary layer can be neglected

The standard STJ model (Feynman Lectures on Physics, Vol. III, Chapter 21; Tinkham
§6.1) treats the electrodes as **infinite reservoirs**:

- The tunneling amplitude K is small (K ≪ Δ, typically K/Δ ∼ 10⁻³ to 10⁻⁴ for
  oxide tunnel barriers).
- The tunneling probability per unit time is Γ = π|K|²ρ_J, which is small compared
  to the inverse relaxation time of the condensate τ⁻¹ ∼ Δ/ℏ.
- Therefore, the depletion of the condensate by tunneling is a second-order effect
  (O(|K|²)), and the boundary perturbation to |Δ| is correspondingly small.

The key physics is that the bulk reservoirs act as particle baths: Cooper pairs lost
to (or gained from) tunneling are rapidly replenished by the condensate over
timescales ∼ℏ/Δ (∼10⁻¹² s) and over distances ∼ξ (∼10⁻⁸ m). The reservoirs
remain in quasi-equilibrium at all times, maintaining constant |Δ_j|.

### Self-consistency check

If the tunneling rate were large enough to significantly deplete the reservoirs
(K → Δ), the approximation would break down, and a self-consistent treatment
(self-consistent Born approximation, or full Bogoliubov-de Gennes equations)
would be required. This corresponds to the crossover from SIS (tunnel junction)
to SNS or S-c-S (point contact / microbridge) junctions.

---

## (7) Literature Citations

### Primary

- **Tinkham, M.** "Introduction to Superconductivity" (2nd ed., McGraw-Hill, 1996):
  - §2.2: BCS coherence length ξ₀, nonlocal electrodynamics
  - §4.2–4.3: Ginzburg-Landau theory, gradient term, healing length, boundary conditions
  - §6.1: The Josephson effects, tunnel Hamiltonian model, constant-Δ assumption explicitly discussed in the STJ context
  - §6.2: Microscopic derivation of the Josephson relations, confirming the consistency of constant-Δ approximation

- **Feynman, R.P.** "The Feynman Lectures on Physics," Vol. III, Chapter 21
  (Addison-Wesley, 1965):
  - Treats the two-state system for the Josephson junction
  - Explicitly assumes |Δ₁| = |Δ₂| = const (uniform superconducting state in
    each electrode), treating the junction as a weakly coupled two-level quantum system
  - Pedagogical derivation showing that the constant-Δ approximation is the
    starting point for the simplest and most transparent derivation of the
    Josephson equations

### Secondary

- **Barone, A. & Paterno, G.** "Physics and Applications of the Josephson Effect"
  (Wiley, 1982): §1.3 discusses the Feynman two-state model and the constant-Δ
  (rigid-boundary) approximation; §3 covers its validity limits.

- **Clarke, J. & Braginski, A.I.** (eds.) "The SQUID Handbook," Vol. I (Wiley-VCH,
  2004): §1.2 reviews the RCSJ model; the constant-Δ reservoir assumption is
  embedded in all standard SQUID models.

- **Likharev, K.K.** "Dynamics of Josephson Junctions and Circuits" (Gordon &
  Breach, 1986): §1.1–1.2 formalize the two-level Hamiltonian starting from the
  constant-Δ assumption; §1.3–1.4 discuss finite-gap corrections and the limits
  of the approximation.

- **Josephson, B.D.** "Possible new effects in superconductive tunnelling,"
  Phys. Lett. 1, 251 (1962): The original paper that first used the
  constant-Δ ansatz; derives the DC and AC Josephson effects from it.

### Independent verification

- **Tonomura, A. et al.** "Observation of individual vortices trapped along
  columnar defects in high-temperature superconductors," Nature 412, 620 (2001):
  Direct Lorentz-microscopy imaging of |Δ| variations on the ξ scale, confirming
  ξ as the relevant healing length.

---

## Summary of the Logical Chain

```
ξ sets minimum scale for |Δ| variation [premise 1]
    +
d ≫ ξ → boundary perturbation is localized [premise 2]
    +
j_s = 0 → ∇φ = 0 in bulk [premise 3]
    +
∇²ψ = 0 → ψ = const in uniform regions [premise 4]
    ↓
|Δ_j| = const AND φ_j = const independently in each electrode [premise 5]
    ↓
The STJ ansatz Ψ = (|Δ₁|e^{iφ₁}, |Δ₂|e^{iφ₂})^T is valid [conclusion]
    ↓
Corrections O(ξ/d) and O(|K|²/Δ²) are negligible for tunnel junctions with
d ≫ ξ and low-transparency barriers [premise 6]
```

---

## Confidence Assessment

The constant-Δ approximation is one of the most well-validated approximations in
superconductivity. Its justification rests on:

1. **ξ as a healing length** (BCS gap equation nonlocality + GL gradient term) --
   firmly established theoretically (95% confidence).
2. **d ≫ ξ in practical junctions** (geometric fact for μm-scale electrodes with
   nm-scale ξ) -- trivially verifiable for any specific junction (95% confidence).
3. **j_s = 0 → ∇φ = 0** (London current-phase relation) -- mathematically exact
   within GL theory (97% confidence).
4. **∇²ψ = 0 → ψ = const** (unique regular solution of Laplace equation in a
   bounded region) -- mathematically exact; the only assumption is that GL theory
   applies, which is valid for T ≲ 0.9 T_c (93% confidence).
5. **Distinction of |Δ| and φ constancy** (conceptual clarity, not a derivation) --
   self-evident from the definitions (92% confidence).
6. **Boundary effects negligible** (controlled by ξ/d and |K|/Δ) -- standard
   approximation, confirmed by experiment; corrections are known and small (90% confidence).
7. **Citations** (Tinkham, Feynman, Barone & Paterno) -- correct and verifiable (97% confidence).

The converged confidence considering the independence of the four convergence arguments
(coherence length, current-phase relation, GL minimization, and self-consistency of the
reservoir model) is approximately 0.90 for the overall claim.
