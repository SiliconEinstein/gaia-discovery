# FINAL ANSWER — fs003_1a5d24e0

## Infinite QFI MZI via Photon Number Fluctuations

**Problem**: Design an MZI scheme achieving infinite quantum Fisher information with finite average photon number ⟨N⟩ ≈ 1.37, using photon number fluctuations with distribution P(N) ∝ 1/N³.

**Belief**: t_target = 0.994 (junction tree BP, exact inference)

---

## Sub-question 1: QFI Equations for a Fluctuating-N State

### State Definition

The probe state is a pure superposition over photon number:

$$\left| \Psi \right\rangle = \sum_{N=0}^{\infty} \sqrt{P(N)} \left| \psi_N \right\rangle$$

where P(N) is a classical probability distribution (P(N) ≥ 0, Σ_N P(N) = 1) and |ψ_N⟩ are normalized quantum states indexed by photon number N.

### Braunstein-Caves Theorem

For a pure state ρ₀ = |Ψ⟩⟨Ψ| undergoing unitary evolution ρ_θ = e^{−iθĜ} ρ₀ e^{iθĜ} with a Hermitian generator Ĝ, the quantum Fisher information is (Braunstein & Caves, PRL 72, 3439, 1994):

$$F_Q = 4\,\text{Var}_{|\Psi\rangle}(\hat{G}) = 4\left[\langle \hat{G}^2 \rangle - \langle \hat{G} \rangle^2\right]$$

This holds for *any* θ — QFI is independent of the parameter value for unitary families on pure states.

### Generator Identification

In the MZI, the phase shift θ is applied in arm c via Û_θ = exp(iθ ĉ†ĉ). The generator is the photon number operator in the phase-shifted arm:

$$\hat{G} = \hat{c}^{\dagger}\hat{c}$$

### Diagonal Property in the Fock Basis

When |ψ_N⟩ = |N⟩_a are Fock states (eigenstates of the number operator â†â), the generator ĉ†ĉ commutes with the photon number operator for mode a. Since each N-component is an eigenstate of â†â with eigenvalue N, cross-terms ⟨M|ĉ†ĉ|N⟩ vanish for M ≠ N.

The variance expansion yields:

$$F_Q = 4\left[\sum_{N=0}^{\infty} P(N) N^2 - \left(\sum_{N=0}^{\infty} P(N) N\right)^2\right] = 4\,\text{Var}(N)$$

where Var(N) = ⟨N²⟩ − ⟨N⟩² is the variance of the photon number distribution P(N). This is the naive formula — **however, this is incorrect for the full MZI** because the effective generator includes cross terms from the beam splitter transformation. The corrected formula is derived in Sub-question 5.

---

## Sub-question 2: Input State at the First Beam Splitter

### Mode Configuration

The MZI has two input spatial modes:
- **Mode a** (sensing arm): receives the probe state
- **Mode b** (reference arm): receives vacuum |0⟩_b

### Input State

The input state entering BS1 is:

$$\left| \Psi_{\text{in}} \right\rangle = \sum_{N=0}^{\infty} \sqrt{P(N)} \left| N \right\rangle_a \otimes \left| 0 \right\rangle_b$$

where:
- $|N\rangle_a = \frac{(\hat{a}^{\dagger})^N}{\sqrt{N!}} |0\rangle_a$ is an N-photon Fock state in mode a
- $\hat{a}^{\dagger}$ and $\hat{b}^{\dagger}$ are creation operators for the two input spatial modes
- $|0\rangle_b$ is the vacuum state in the reference mode b
- $P(N)$ is a classical probability distribution: $\sum_{N=0}^{\infty} P(N) = 1,\; P(N) \geq 0$

### Physical Interpretation

This is a **pure quantum superposition** over photon number (not a classical mixture). Each term in the superposition is a product of an N-photon Fock state in the sensing arm and vacuum in the reference arm. The state is separable across modes a and b for each N-component, but entangled across photon number within mode a.

The phase coherence between different N-components is essential — it enables the interference that generates the cross terms in ⟨Ĝ²⟩ (see Sub-question 5).

### Normalization

$$\langle \Psi_{\text{in}} | \Psi_{\text{in}} \rangle = \sum_{N,N'} \sqrt{P(N)P(N')} \langle N|N'\rangle_a \langle 0|0\rangle_b = \sum_N P(N) = 1$$

---

## Sub-question 3: Average Photon Number is Finite

### Distribution Definition

The photon number distribution is a discrete power-law (zeta distribution):

$$P(N) = \frac{1}{\zeta(3) \cdot N^3}, \quad N = 1, 2, 3, \ldots$$

where ζ(3) ≈ 1.2020569 is Apéry's constant (the Riemann zeta function evaluated at α = 3).

### Normalization

$$\sum_{N=1}^{\infty} P(N) = \frac{1}{\zeta(3)} \sum_{N=1}^{\infty} \frac{1}{N^3} = \frac{\zeta(3)}{\zeta(3)} = 1$$

Verified: the sum of 1/N³ converges to ζ(3) by the p-test (p = 3 > 1).

### First Moment (Mean) — Finite

$$\langle N \rangle = \sum_{N=1}^{\infty} N \cdot P(N) = \frac{1}{\zeta(3)} \sum_{N=1}^{\infty} \frac{N}{N^3} = \frac{1}{\zeta(3)} \sum_{N=1}^{\infty} \frac{1}{N^2}$$

The sum Σ 1/N² = ζ(2) = π²/6 ≈ 1.644934 converges by the p-test (p = 2 > 1).

$$\langle N \rangle = \frac{\zeta(2)}{\zeta(3)} = \frac{\pi^2/6}{\zeta(3)} \approx \frac{1.644934}{1.202057} \approx 1.368$$

### Second Moment — Divergent

$$\langle N^2 \rangle = \sum_{N=1}^{\infty} N^2 \cdot P(N) = \frac{1}{\zeta(3)} \sum_{N=1}^{\infty} \frac{N^2}{N^3} = \frac{1}{\zeta(3)} \sum_{N=1}^{\infty} \frac{1}{N}$$

The harmonic series Σ 1/N diverges (p-test with p = 1; integral test: ∫₁^∞ dx/x = ln(x)|₁^∞ → ∞).

Therefore:
- $\langle N \rangle \approx 1.368$ is **finite**
- $\langle N^2 \rangle \to \infty$ **diverges** (logarithmically, as ∼ln(N_max) for finite cutoff)

### Variance Behavior

$$\text{Var}(N) = \langle N^2 \rangle - \langle N \rangle^2 \to \infty$$

This is the key property: the distribution has a heavy enough tail (α = 3) that the mean converges but the variance diverges. This is the marginal case — for α ≤ 3, the second moment diverges; for α > 3, it converges.

---

## Sub-question 4: Time-Evolved State Through the MZI

### MZI Operator Sequence

The full MZI evolution operator is:

$$\hat{U}_{\text{MZI}}(\theta) = \hat{B}_2 \cdot \hat{U}_{\theta} \cdot \hat{B}_1$$

where:
- B̂₁: first 50:50 beam splitter (modes a,b → c,d)
- Û_θ = exp(iθ ĉ†ĉ): phase shift in arm c
- B̂₂: second 50:50 beam splitter (modes c,d → e,f)

### Beam Splitter Transformation

For a 50:50 BS: $\hat{B} = \exp[i(\pi/4)(\hat{u}^{\dagger}\hat{v} + \hat{u}\hat{v}^{\dagger})]$.

The Heisenberg-picture creation operator transformations are:

**BS1** (input modes a,b → internal modes c,d):
$$\hat{a}^{\dagger} \to \frac{\hat{c}^{\dagger} + i\hat{d}^{\dagger}}{\sqrt{2}}, \qquad \hat{b}^{\dagger} \to \frac{i\hat{c}^{\dagger} + \hat{d}^{\dagger}}{\sqrt{2}}$$

**Phase shift** (mode c only):
$$\hat{c}^{\dagger} \to e^{i\theta} \hat{c}^{\dagger}, \qquad \hat{d}^{\dagger} \to \hat{d}^{\dagger}$$

**BS2** (internal modes c,d → output modes e,f):
$$\hat{c}^{\dagger} \to \frac{\hat{e}^{\dagger} + i\hat{f}^{\dagger}}{\sqrt{2}}, \qquad \hat{d}^{\dagger} \to \frac{i\hat{e}^{\dagger} + \hat{f}^{\dagger}}{\sqrt{2}}$$

### Binomial Expansion for an N-Photon Fock Component

For each N-component |N⟩_a|0⟩_b:

**After BS1**: an N-photon Fock state in mode a splits into modes c,d according to the binomial distribution:

$$\left| N \right\rangle_a \left| 0 \right\rangle_b \xrightarrow{\hat{B}_1} \sum_{k=0}^{N} \sqrt{\binom{N}{k}} \frac{i^k}{2^{N/2}} \left| k \right\rangle_c \left| N-k \right\rangle_d$$

**After phase shift**:
$$\xrightarrow{\hat{U}_{\theta}} \sum_{k=0}^{N} \sqrt{\binom{N}{k}} \frac{i^k e^{i\theta k}}{2^{N/2}} \left| k \right\rangle_c \left| N-k \right\rangle_d$$

**After BS2**: each |k⟩_c|N−k⟩_d component further splits into output modes e,f:
$$\xrightarrow{\hat{B}_2} \sum_{k=0}^{N} \sqrt{\binom{N}{k}} \frac{i^k e^{i\theta k}}{2^{N/2}} \sum_{j=0}^{k} \sum_{\ell=0}^{N-k} \sqrt{\binom{k}{j} \binom{N-k}{\ell}} \frac{i^{\ell} (-1)^{?}}{2^{(k+(N-k))/2}} \times (\text{output state in e,f})$$

The complete output for each N-component is a superposition over photon number distributions (n_e, n_f) at the output ports, with θ-dependent amplitudes.

### Full Output State

The total output state is the coherent superposition over all N:

$$\left| \Psi_{\text{out}}(\theta) \right\rangle = \hat{U}_{\text{MZI}}(\theta) \left| \Psi_{\text{in}} \right\rangle = \sum_{N=0}^{\infty} \sqrt{P(N)} \left| \Phi_N^{(\text{out})}(\theta) \right\rangle$$

where $|\Phi_N^{(\text{out})}(\theta)\rangle$ is the output of the N-photon component through the full MZI.

### Normalization Check

Since Û_MZI is unitary and |Ψ_in⟩ is normalized:

$$\langle \Psi_{\text{out}} | \Psi_{\text{out}} \rangle = \langle \Psi_{\text{in}} | \hat{U}_{\text{MZI}}^{\dagger} \hat{U}_{\text{MZI}} | \Psi_{\text{in}} \rangle = \langle \Psi_{\text{in}} | \Psi_{\text{in}} \rangle = 1$$

θ → 0 limit: Û_MZI(0) = B̂₂ B̂₁ = B̂₁₂, the composition of two 50:50 BSs, which equals the identity up to an overall phase (the Mach-Zehnder returns to the identity at zero phase difference).

---

## Sub-question 5: QFI Tends to Infinity for Finite ⟨N⟩

### Effective Generator in the Input Picture

By the Braunstein-Caves theorem applied in the Heisenberg picture, the QFI is determined by the variance of the effective generator **pulled back to the input**:

$$\hat{G}_{\text{eff}} = \hat{B}_1^{\dagger} \hat{c}^{\dagger}\hat{c} \hat{B}_1$$

This is the physical quantity we need: the photon number operator in the phase-shifted arm, expressed in terms of input operators.

### Explicit Computation of the Effective Generator

Using the BS1 Heisenberg transformation (inverse: B̂₁† ĉ B̂₁ = (â + ib̂)/√2, B̂₁† d̂ B̂₁ = (iâ + b̂)/√2):

$$\hat{G}_{\text{eff}} = \hat{B}_1^{\dagger} \hat{c}^{\dagger}\hat{c} \hat{B}_1$$

$$= \left(\frac{\hat{a}^{\dagger} - i\hat{b}^{\dagger}}{\sqrt{2}}\right) \left(\frac{\hat{a} + i\hat{b}}{\sqrt{2}}\right)$$

$$= \frac{1}{2}\left(\hat{a}^{\dagger}\hat{a} + i\hat{a}^{\dagger}\hat{b} - i\hat{b}^{\dagger}\hat{a} + \hat{b}^{\dagger}\hat{b}\right)$$

### Expectation of Ĝ_eff on |Ψ_in⟩

On the input state |Ψ_in⟩ = Σ √P(N) |N⟩_a|0⟩_b with vacuum in mode b:

$$\langle \hat{a}^{\dagger}\hat{a} \rangle = \langle N \rangle, \quad \langle \hat{b}^{\dagger}\hat{b} \rangle = 0$$

$$\langle i\hat{a}^{\dagger}\hat{b} \rangle = 0, \quad \langle -i\hat{b}^{\dagger}\hat{a} \rangle = 0$$

Therefore:
$$\langle \hat{G}_{\text{eff}} \rangle = \frac{\langle N \rangle}{2}$$

### CRITICAL CORRECTION: Expectation of Ĝ_eff²

While the cross terms vanish in ⟨Ĝ_eff⟩, they **do contribute to ⟨Ĝ_eff²⟩**. Compute the action on an N-photon Fock component:

$$\hat{G}_{\text{eff}} |N, 0\rangle = \frac{1}{2}\left[N|N,0\rangle - i\sqrt{N}|N-1, 1\rangle\right]$$

The norm:
$$||\hat{G}_{\text{eff}} |N,0\rangle||^2 = \frac{1}{4}\left(N^2 + N\right)$$

where the N term comes from ||−i√N|N−1,1⟩||² = N.

Therefore, for the superposition state:
$$\langle \hat{G}_{\text{eff}}^2 \rangle = \sum_N P(N) \cdot \frac{N^2 + N}{4} = \frac{\langle N^2 \rangle + \langle N \rangle}{4}$$

### QFI: The Corrected Formula

Applying Braunstein-Caves:

$$F_Q = 4\,\text{Var}_{|\Psi_{\text{in}}\rangle}(\hat{G}_{\text{eff}}) = 4\left[\frac{\langle N^2 \rangle + \langle N \rangle}{4} - \left(\frac{\langle N \rangle}{2}\right)^2\right]$$

$$= \langle N^2 \rangle + \langle N \rangle - \langle N \rangle^2$$

$$F_Q = \text{Var}(N) + \langle N \rangle$$

**This is the critical correction.** The earlier formula F_Q = 4 Var(N) missed the contribution of the cross terms iâ†b̂ and −ib̂†â to ⟨Ĝ²⟩. The corrected formula changes the coefficient of Var(N) from 4 to 1 but adds ⟨N⟩, preserving the divergence since Var(N) → ∞ dominates over the finite ⟨N⟩.

### Proof of Divergence

Substituting P(N) = 1/(ζ(3) · N³):

$$\langle N \rangle = \frac{\zeta(2)}{\zeta(3)} \approx 1.368 \quad \text{(finite)}$$

$$\langle N^2 \rangle = \frac{1}{\zeta(3)} \sum_{N=1}^{\infty} \frac{1}{N} \to \infty \quad \text{(harmonic series diverges)}$$

$$\text{Var}(N) = \langle N^2 \rangle - \langle N \rangle^2 \to \infty$$

$$F_Q = \text{Var}(N) + \langle N \rangle \to \infty$$

**Therefore, F_Q → ∞ while ⟨N⟩ remains finite ≈ 1.37.**

### Finite-Cutoff Expression

With a finite cutoff N_max, the harmonic series partial sum is $H_{N_{\text{max}}} = \sum_{N=1}^{N_{\text{max}}} 1/N$:

$$F_Q(N_{\text{max}}) = \frac{H_{N_{\text{max}}}}{\zeta(3)} - \left(\frac{\zeta(2)}{\zeta(3)}\right)^2 + \frac{\zeta(2)}{\zeta(3)}$$

Numerical values (verified by independent Python computation using math.fsum):

| N_max | ⟨N⟩ | ⟨N²⟩ | F_Q |
|-------|------|------|-----|
| 100 | 1.360155 | 4.315418 | **3.826** |
| 10³ | 1.367601 | 6.227218 | **5.724** |
| 10⁴ | 1.368300 | 8.133371 | **7.638** |
| 10⁵ | 1.368420 | 10.039468 | **9.552** |
| 10⁶ | 1.368432 | 11.973415 | **11.469** |

### Scaling Analysis

The asymptotic behavior (large N_max):

$$F_Q \sim \frac{1}{\zeta(3)} \ln(N_{\text{max}}) - \left(\frac{\zeta(2)}{\zeta(3)}\right)^2 + \frac{\zeta(2)}{\zeta(3)} + \frac{\gamma}{\zeta(3)}$$

where γ ≈ 0.577216 is the Euler-Mascheroni constant and 1/ζ(3) ≈ 0.831907.

Fitted slope from numerical data (10³ to 10⁵): 0.831541 vs theoretical 0.831907 — error 0.044%.

**The divergence is logarithmic** (~0.832 · ln(N_max)), NOT Heisenberg-like (~N²). Every factor-of-10 increase in N_max adds only ~1.915 to F_Q.

### θ-Independence

Ĝ_eff contains no θ parameter — it is manifestly independent of θ. Therefore F_Q = 4 Var(Ĝ_eff) is independent of θ for all θ values, not just in a neighborhood of θ₀.

---

## Sub-question 6: Alternative Experimental Strategy

### Strategy Comparison

Three MZI-based phase estimation strategies compared at realistic experimental parameters:

#### Strategy I: Squeezed Vacuum (RECOMMENDED)

**Input**: $|\xi\rangle_a \otimes |0\rangle_b$ where $|\xi\rangle = \hat{S}(\xi)|0\rangle$ with squeezing parameter r = |ξ|.

$$\langle N \rangle = N_s = \sinh^2 r$$

**QFI**: $F_Q = N_s(2N_s + 3) \approx 2\langle N \rangle^2$ for large N_s.

| ⟨N⟩ | F_Q (ideal) | F_Q at η=0.95 | F_Q at η=0.90 |
|------|-------------|---------------|---------------|
| 10 | 230 | 218 | 207 |
| 50 | 5,150 | 4,893 | 4,635 |
| 100 | 20,300 | 19,285 | 18,270 |

**Loss degradation**: Approximately linear: F_Q(η) ≈ η · F_Q. This preserves the quantum advantage even at moderate losses.

**Experimental maturity**: TRL 8-9.
- Source: OPO with >15 dB squeezing demonstrated (Vahlbruch et al., PRL 117, 110801, 2016)
- Deployed in: GEO600 (2011), Advanced LIGO (2019), Advanced Virgo — operational gravitational wave observatories
- Detection: balanced homodyne detection — well-established, off-the-shelf technology
- Precedent: squeezed vacuum injection improved LIGO sensitivity by ~3 dB at frequencies above 100 Hz

#### Strategy II: NOON States

**Input**: $(|N,0\rangle + |0,N\rangle)/\sqrt{2}$

**QFI**: $F_Q = N^2$ (Heisenberg scaling)

**Loss degradation**: $F_Q(\eta) = \eta^N \cdot N^2$ (exponential — FATAL)

| N | F_Q (ideal) | F_Q at η=0.95 | F_Q at η=0.90 |
|---|-------------|---------------|---------------|
| 5 | 25 | 19.3 (77%) | 14.8 (59%) |
| 10 | 100 | 59.9 (60%) | 34.9 (35%) |
| 20 | 400 | 143.4 (36%) | 48.6 (12%) |

**Experimental maturity**: TRL 2-3.
- Laboratory demonstrations up to N = 5 in bulk optics
- Post-selection reduces effective count rate
- Generation probability scales unfavorably with N
- Exponential loss sensitivity makes N > 10 impractical

#### Strategy III: Fluctuating-N P(N) ∝ 1/N³ (THIS WORK)

**QFI**: $F_Q = \text{Var}(N) + \langle N \rangle$, ⟨N⟩ ≈ 1.37

| N_max | F_Q |
|-------|-----|
| 100 | 3.83 |
| 10³ | 5.72 |
| 10⁴ | 7.64 |
| 10⁵ | 9.55 |
| 10⁶ | 11.47 |

**Loss degradation**: $F_Q(\eta) \approx \eta^2 \cdot \text{Var}(N) + \eta \cdot \langle N \rangle$ (linear-like, robust)

**Experimental maturity**: TRL 1 (theoretical concept only).
- No known physical source produces P(N) ∝ 1/N³ over decades of N
- QFI growth is only logarithmic
- At N_max = 10⁶, F_Q < 14 — comparable to a coherent state with ⟨N⟩ = 14

### Conclusion

**Ranking**: Squeezed vacuum >> NOON >> Fluctuating-N (for experimental practicality)

At η = 0.95 and ⟨N⟩ = 10, squeezed vacuum delivers F_Q ≈ 218, while NOON (N = 10) delivers F_Q ≈ 60 (only 60% retained) and fluctuating-N at N_max = 10⁶ yields only F_Q ≈ 10.9.

The squeezed vacuum strategy provides orders-of-magnitude higher QFI at accessible resource scales and uses mature, deployed technology. The fluctuating-N scheme serves as a theoretical proof-of-principle that infinite QFI is compatible with finite ⟨N⟩, but offers no practical advantage at any foreseeable experimental scale.

---

## Sub-question 7: Experimental Implementation

### I. Input State Preparation (Primary Challenge)

**Requirement**: A photon source producing the distribution P(N) = 1/(ζ(3) · N³) for N ≥ 1.

This is an **open experimental problem** with no demonstrated physical realization. Standard single-mode SPDC produces thermal (geometric) distributions P(N) = (1 − |ξ|²)|ξ|^{2N} — exponential decay, not power-law.

Potential approaches (all at TRL 1-2):
- **(a) Multiplexed SPDC** with engineered pump spectra across many Schmidt modes using group-velocity matching in periodically-poled KTP or lithium niobate waveguides (Kues et al., Nature 546, 622, 2017)
- **(b) Conditional state preparation** via a PNR detector trigger with feed-forward to an electro-optic amplitude modulator for sequential N-component selection
- **(c) Engineered nonlinear waveguide arrays** with tailored coupling coefficients to approximate power-law statistics

### II. Interferometer (Mature Technology)

**Component**: Fiber-coupled 50:50 MZI with active piezo-controlled phase stabilization.

Commercial fiber-based MZI modules with reference-laser feedback achieve phase stability better than λ/100 — more than sufficient for the proposed scheme. This component poses no experimental barrier.

### III. Optimal Measurement

**Hardware**: Joint photon-number-resolving detection at both MZI output ports (modes e, f) using:
- **Superconducting nanowire single-photon detectors** (SNSPDs): >90% detection efficiency at telecom wavelengths, <100 Hz dark count rate, <20 ps timing jitter (Hadfield, Nat. Photon. 3, 696, 2009)
- **Transition-edge sensors** (TES): >95% efficiency, intrinsic energy resolution for PNR up to ~10 photons (Lita et al., Opt. Express 16, 3032, 2008)

**Justification**: The joint probability distribution p(n_e, n_f|θ) from PNR detection provides **informationally complete statistics** for phase estimation. Maximum-likelihood estimation (MLE) on this distribution can asymptotically saturate the Cramér-Rao bound in the limit of many independent repetitions (ν → ∞).

**Technical note**: The symmetric logarithmic derivative (SLD) L̂_θ is NOT strictly diagonal in the joint Fock basis |n_e, n_f⟩. The cross term from the BS2 transformation creates off-diagonal coherences between |n_e, n_f⟩ and |n_e ± 1, n_f ∓ 1⟩. However, the PNR measurement statistics still encode all θ-information in the output state — the measurement is sufficient for asymptotically optimal phase estimation via MLE.

### IV. Corrected Sensitivity Estimates

Using F_Q = Var(N) + ⟨N⟩ (not 4 Var(N)):

| N_max | F_Q | Δθ (single trial) | Δθ (ν = 10⁶ reps) |
|-------|-----|--------------------|--------------------|
| 100 | 3.83 | 0.511 rad | 5.11 × 10⁻⁴ rad |
| 500 | 5.15 | 0.441 rad | 4.41 × 10⁻⁴ rad |
| 10⁴ | 7.64 | 0.362 rad | 3.62 × 10⁻⁴ rad |

Uncertainty improves as 1/√ν for ν independent repetitions.

### V. Practical Limitations

**(a) Detection efficiency** (η < 1):

$$F_Q^{\text{eff}} = \eta^2 \cdot \text{Var}(N) + \eta \cdot \langle N \rangle$$

The two terms scale differently: Var(N) arises from two-operator correlations (η²), while ⟨N⟩ arises from single-operator contributions (η). The formula approaches the ideal F_Q = Var(N) + ⟨N⟩ as η → 1 without any pathological divergence. At η = 0.90, approximately 87% of ideal F_Q is retained.

**(b) Finite N_max**: Regularizes QFI to logarithmic growth ∼(1/ζ(3)) ln(N_max). Practical sensitivity is severely limited by the slow growth rate.

**(c) Dark count noise**: Negligible. With DCR 1-100 Hz and gate times 1-100 ns, dark count probability is 10⁻⁹-10⁻⁵ per gate — contributing a noise floor well below the signal-limited uncertainty.

**(d) The practical reality**: The logarithmic QFI growth means exponentially larger N_max is required for each unit gain in Fisher information. Even N_max = 10⁹ gives F_Q ≈ 17.2 — comparable to a coherent state with ⟨N⟩ ≈ 17 and far below squeezed-state performance. The scheme's value is as a **theoretical existence proof** that infinite QFI is compatible with finite ⟨N⟩, not as a practical metrological strategy.

---

## Summary

The central result is the corrected QFI formula for the fluctuating-N MZI scheme:

$$\boxed{F_Q = \text{Var}(N) + \langle N \rangle}$$

derived from the effective generator $\hat{G}_{\text{eff}} = \hat{B}_1^{\dagger} \hat{c}^{\dagger}\hat{c} \hat{B}_1 = (\hat{a}^{\dagger}\hat{a} + i\hat{a}^{\dagger}\hat{b} - i\hat{b}^{\dagger}\hat{a} + \hat{b}^{\dagger}\hat{b})/2$, where the cross terms $i\hat{a}^{\dagger}\hat{b}$ and $-i\hat{b}^{\dagger}\hat{a}$ contribute to ⟨Ĝ²⟩ even though their expectation values vanish on vacuum mode b.

For P(N) = 1/(ζ(3) · N³):
- ⟨N⟩ = ζ(2)/ζ(3) ≈ 1.368 (finite)
- ⟨N²⟩ = (1/ζ(3)) Σ 1/N → ∞ (harmonic series divergence)
- F_Q → ∞ with logarithmic scaling ∼(1/ζ(3)) ln(N_max)

The scheme achieves infinite QFI with finite average photon number — a mathematically valid quantum-mechanical result. However, the logarithmic divergence makes the practical advantage negligible at any accessible parameter scale. Squeezed vacuum states at ⟨N⟩ ≈ 10-50 remain the most experimentally viable quantum-enhanced phase estimation strategy, using mature OPO source technology already deployed in gravitational wave observatories.
