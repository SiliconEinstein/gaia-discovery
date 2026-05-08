"""plan.gaia.py — 问题 fs010_bf7d23f3 的 Gaia 知识包 = 主 agent 的探索路径。

* 这个文件由主 agent 直接编辑（Edit / Write）。
* 它同时是:
    (a) 你对问题的当前形式化理解 (compile_package_artifact 直接吃)
    (b) 你的探索路径 (git diff 即可读)
* USER hint: 用户可在任意位置插入 `# USER: ...` 注释，主 agent 必须读并响应。
"""
from gaia.lang import (
    claim, setting, question,
    support, deduction, abduction, induction,
    contradiction, equivalence, complement, disjunction,
)

# ---------------------------------------------------------------------- 问题
q_main = question(
    "Solve the Josephson junction tunneling Hamiltonian problem: "
    "given H = [[eV, K], [K, -eV]] and wavefunction "
    "Ψ = (|Δ₁|e^{iφ₁}, |Δ₂|e^{iφ₂})^T with Δ_j = √(n_{s,j}/2) e^{iφ_j}, "
    "answer sub-questions (a)-(f) covering the constant-Δ approximation, "
    "K=0 eigenstates, Cooper-pair energy change, AC Josephson from energy "
    "conservation, Schrödinger ODEs, and DC/AC Josephson effects."
)

# ---------------------------------------------------------------------- settings
setting(
    "Superconducting coherence length ξ sets the scale over which |Δ| varies; "
    "in bulk electrodes far from interfaces (d ≫ ξ), |Δ| saturates to its "
    "equilibrium BCS value. GL free-energy minimisation ∇²ψ=0 in uniform, "
    "field-free bulk gives |ψ|=const (Tinkham §6.1)."
)

setting(
    "H = [[eV, K], [K, -eV]] in units of energy per Cooper pair; K is tunneling "
    "amplitude; V is potential bias. Ψ = (|Δ₁|e^{iφ₁}, |Δ₂|e^{iφ₂})^T with "
    "|Δ_j| = √(n_{s,j}/2) is the two-component superconducting order parameter."
)

setting(
    "Cooper pair charge q = -2e. Diagonal entries ±eV in H are Cooper-pair "
    "energies measured from the Fermi level: electrostatic energy U_j = -2e V_j, "
    "so energy splitting ΔE = -2e(V₂-V₁) = -2eV when V = V₂-V₁."
)

setting(
    "Time-dependent Schrödinger equation: iℏ ∂Ψ/∂t = H Ψ."
)

# ---------------------------------------------------------------------- claims

t_target = claim(
    "All six sub-questions (a)-(f) of the Josephson junction tunneling Hamiltonian "
    "problem are correctly solved: (a) constant Δ_j approximation justified by "
    "coherence length ξ and Ginzburg-Landau theory; (b) K=0 eigenstates are "
    "(1,0)^T and (0,1)^T with eigenvalues ±eV and n_{s,1}+n_{s,2}=const; "
    "(c) ΔE = −2eV consistent with Cooper pair charge −2e; (d) energy "
    "conservation in tunneling implies AC Josephson effect with ω_J=2eV/ℏ and "
    "zero DC average; (e) Schrödinger equation yields coupled ODEs for n_{s,j} "
    "and θ=φ₁−φ₂ via real/imaginary separation; (f) with n_{s,1}≈n_{s,2}, ODEs "
    "reduce to DC (V=0, I=I_c sin θ) and AC (V≠0, I=I_c sin(θ+ω_J t)) Josephson effects.",
    prior=0.5,
    metadata={
        "prior_justification": "Sub-questions (a)-(f) span standard Josephson "
        "junction theory; initial 0.5 reflects symmetric ignorance.",
        "provenance": "PROBLEM.md sub-questions (a)-(f)",
    },
)

# --- Sub-question (a): constant Δ_j approximation
c_const_delta = claim(
    "The order parameter components Δ_j = √(n_{s,j}/2) e^{iφ_j} are approximately "
    "constant inside the bulk superconducting regions on either side of the tunnel "
    "barrier because: (i) coherence length ξ sets the scale for |Δ| variation, and "
    "electrode thickness d ≫ ξ so |Δ| → |Δ_eq| far from interfaces; (ii) in the "
    "absence of supercurrents, ∇φ ≈ 0 from j_s ∝ n_s ∇φ; (iii) GL free-energy "
    "minimization ∇²ψ=0 in uniform, field-free regions gives |ψ|=const; "
    "(iv) the constant-Δ approximation is equivalent to the rigid-boundary / "
    "infinite-reservoir model in standard STJ theory and breaks down only within "
    "a few ξ of the barrier interface.",
    prior=0.75,
    metadata={
        "prior_justification": "Standard result in superconductivity textbooks "
        "(Tinkham §6.1, Feynman Lectures III); fundamental to the STJ model.",
        "action": "support",
        "args": {
            "task": "Justify the constant-Δ approximation for Josephson junctions. "
            "Explain: (1) Coherence length ξ as the characteristic length scale for "
            "|Δ| variation — name it explicitly. (2) In bulk electrodes with d ≫ ξ, "
            "|Δ| saturates to the equilibrium BCS gap value. (3) In field-free, "
            "current-free bulk, ∇φ=0 from j_s ∝ n_s∇φ, so phase is uniform. "
            "(4) GL free-energy minimization ∇²ψ=0 ⇒ |ψ|=const in uniform regions. "
            "(5) Distinguish magnitude constancy from phase constancy. "
            "(6) State that the approximation breaks down within ∼ξ of the barrier "
            "and acknowledge this is acceptable for the STJ reservoir model. "
            "(7) Cite Tinkham §6.1 / Feynman Lectures III."
        },"action_status": "done"
    },
action_id="act_89ad7f7eae2b", action_status="done", verify_history=[{"source": "verify:inquiry_review", "action_id": "act_89ad7f7eae2b", "verdict": "verified", "confidence": "0.860", "evidence": "The premises largely match standard superconductivity/Josephson-junction reasoning: ξ is the healing length for order-parameter magnitude, thick electrodes recover bulk Δ away from the interface, and "}])

# --- Sub-question (b): K=0 eigenstates
c_k0_eigenstates = claim(
    "When K=0, H = diag(eV, −eV). The eigenstates are: ψ₁ = (1, 0)^T with "
    "eigenvalue E₁ = +eV (Cooper pair on side 1), and ψ₂ = (0, 1)^T with "
    "eigenvalue E₂ = −eV (Cooper pair on side 2). For ψ₁: |Δ₁| = √(n_{s,1}/2), "
    "Δ₂ = 0. For ψ₂: Δ₁ = 0, |Δ₂| = √(n_{s,2}/2). Wavefunction normalization "
    "|Δ₁|² + |Δ₂|² = const gives (n_{s,1}+n_{s,2})/2 = const, i.e., "
    "n_{s,1} + n_{s,2} = const (conserved total superfluid Cooper-pair density). "
    "In the K=0 eigenstates specifically, the pair is fully localized on one side: "
    "either (n_{s,1}=n_s_total, n_{s,2}=0) or (n_{s,1}=0, n_{s,2}=n_s_total).",
    prior=0.8,
    metadata={
        "prior_justification": "Diagonal matrix eigenvalue problem; standard "
        "quantum mechanics. The conservation relation follows from normalization.",
        "action": "deduction",
        "args": {
            "task": "Diagonalize H=diag(eV,-eV) at K=0. Write explicit eigenvectors "
            "ψ₁=(1,0)^T and ψ₂=(0,1)^T with eigenvalues E₁=+eV, E₂=−eV. "
            "Interpret each eigenstate physically (Cooper pair location). Derive "
            "n_{s,1}+n_{s,2}=const from normalization |Δ₁|²+|Δ₂|²=const using "
            "|Δ_j|²=n_{s,j}/2. State the eigenstate-limit relationship explicitly."
        },"action_status": "failed"
    },
action_id="act_8ef7f5670cdb", action_status="failed", verify_history=[{"source": "verify:lean_lake", "action_id": "act_8ef7f5670cdb", "verdict": "inconclusive", "confidence": "0.400", "evidence": "lake build 失败（returncode=1），证明未完成"}])

# --- Sub-question (c): energy change at K=0
c_energy_change = claim(
    "At K=0, a Cooper pair moving from side 1 to side 2 changes energy by "
    "ΔE = E₂ − E₁ = −eV − (+eV) = −2eV (loses energy −2eV, i.e., lower energy "
    "on side 2 when V>0). With Cooper pair charge q = −2e, electrostatic energy "
    "U_j = −2e V_j, and the electrochemical potential difference is "
    "Δμ = μ₂ − μ₁ = −2e(V₂−V₁) = −2eV, matching the Hamiltonian eigenvalue "
    "splitting. The factor of 2 arises from the pair nature of the charge — a "
    "single electron would give e, but a Cooper pair gives 2e. The Hamiltonian "
    "diagonal entries ±eV are Cooper-pair energies, not single-electron energies.",
    prior=0.75,
    metadata={
        "prior_justification": "Follows directly from K=0 eigenstate analysis "
        "in (b); the 2e factor is a defining feature of Josephson phenomenology.",
        "action": "deduction",
        "args": {
            "task": "Verify the Cooper pair energy change at K=0. "
            "(1) Compute ΔE = E₂−E₁ = −eV−(+eV) = −2eV explicitly with direction "
            "(side 1 → side 2). (2) State Cooper pair charge q = −2e. "
            "(3) Derive electrostatic energy U_j = −2e V_j and electrochemical "
            "potential difference Δμ = −2e(V₂−V₁) = −2eV. "
            "(4) Confirm agreement: the Hamiltonian eigenvalue splitting 2eV matches "
            "the chemical potential difference 2eV induced by applied voltage. "
            "(5) Explain why the factor is 2e (not e) — Cooper pair nature. "
            "(6) State sign convention explicitly: which side is at higher potential."
        },"action_status": "failed"
    },
action_id="act_97809190c915", action_status="failed", verify_history=[{"source": "verify:lean_lake", "action_id": "act_97809190c915", "verdict": "inconclusive", "confidence": "0.400", "evidence": "lake build 失败（returncode=1），证明未完成"}])

# --- Sub-question (d): AC Josephson from energy conservation
c_ac_response = claim(
    "When K≠0, off-diagonal terms describe Cooper pair coherent tunneling across "
    "the barrier. A Cooper pair tunneling side 1→2 changes diagonal energy by "
    "ΔE = −2eV. Energy conservation requires compensation by emission/absorption "
    "of a quantum ℏω = 2|eV|. This fixes the Josephson frequency "
    "ω_J = 2eV/ℏ (f_J = 2eV/h ≈ 483.6 MHz/μV). The current response is "
    "I(t) = I_c sin(φ₁−φ₂ + ω_J t) — an AC current even under DC bias. The "
    "time-averaged DC current is zero for a pure Josephson element. This is "
    "fundamentally different from Ohm's law — the response is quantum-coherent "
    "and oscillatory, not dissipative. Each tunneling event transfers charge 2e "
    "and energy 2eV to the electromagnetic environment.",
    prior=0.7,
    metadata={
        "prior_justification": "Energy conservation argument is the standard "
        "physical derivation of the AC Josephson effect (Josephson 1962); "
        "requires explicit ℏω=2eV relation and zero-DC-average conclusion.",
        "action": "deduction",
        "args": {
            "task": "Verify the energy-conservation argument for the AC Josephson "
            "effect: (1) State that off-diagonal K terms describe tunneling. "
            "(2) Compute ΔE=-2eV for Cooper pair tunneling side 1→2. "
            "(3) Apply energy conservation ΔE=ℏω to derive ω_J=2eV/ℏ. "
            "(4) Write the AC current I(t)=I_c sin(φ₁−φ₂+ω_J t). "
            "(5) Prove the time-averaged DC current ⟨I(t)⟩=0 for pure DC bias. "
            "(6) Contrast with Ohmic conduction."
        },"action_status": "failed"
    },
action_id="act_63bd405c2915", action_status="failed", verify_history=[{"source": "verify:lean_lake", "action_id": "act_63bd405c2915", "verdict": "inconclusive", "confidence": "0.400", "evidence": "lake build 失败（returncode=1），证明未完成"}])

# --- Sub-question (e): Schrödinger ODEs
c_schrodinger_eqns = claim(
    "From iℏ dΨ/dt = H Ψ with Ψ = (|Δ₁|e^{iφ₁}, |Δ₂|e^{iφ₂})^T and "
    "|Δ_j| = √(n_{s,j}/2), the coupled first-order ODEs are obtained by "
    "separating real and imaginary parts. Density-rate equations: "
    "dn_{s,1}/dt = (2K/ℏ)√(n_{s,1}n_{s,2}) sin(φ₂−φ₁) and "
    "dn_{s,2}/dt = (2K/ℏ)√(n_{s,1}n_{s,2}) sin(φ₁−φ₂) = −dn_{s,1}/dt, "
    "showing Cooper-pair number conservation (I_s ∝ dn_{s,1}/dt ∝ sin θ). "
    "Phase-evolution equations: "
    "dφ₁/dt = −(1/ℏ)[eV + K√(n_{s,2}/n_{s,1}) cos(φ₁−φ₂)], "
    "dφ₂/dt = −(1/ℏ)[−eV + K√(n_{s,1}/n_{s,2}) cos(φ₂−φ₁)]. "
    "With θ=φ₁−φ₂, the phase-difference equation is "
    "dθ/dt = −2eV/ℏ + (K/ℏ)[√(n_{s,1}/n_{s,2}) − √(n_{s,2}/n_{s,1})] cos θ. "
    "The supercurrent-phase relation I_s = I_c sin θ is embedded in dn_{s,1}/dt.",
    prior=0.55,
    metadata={
        "prior_justification": "This is the most algebraically dense derivation; "
        "the ODEs are canonical (Feynman III, Tinkham §6.2) but signs, factor of "
        "2 in 2K/ℏ, and the √(n_j/n_k) correction terms are common error points.",
        "action": "deduction",
        "args": {
            "task": "Starting from iℏ dΨ/dt = HΨ with H=[[eV,K],[K,-eV]] and "
            "Ψ=(|Δ₁|e^{iφ₁}, |Δ₂|e^{iφ₂})^T, derive the coupled ODEs. "
            "Step 1: Write the two components of the TDSE. "
            "Step 2: Substitute |Δ_j|=√(n_{s,j}/2) and use chain rule for time "
            "derivatives. "
            "Step 3: Separate each equation into real and imaginary parts using "
            "Euler expansion e^{iφ}. "
            "Step 4: Extract dn_{s,1}/dt, dn_{s,2}/dt and dφ₁/dt, dφ₂/dt. "
            "Step 5: Apply θ=φ₁−φ₂ to separate. "
            "Step 6: Verify dn_{s,1}/dt = −dn_{s,2}/dt (conservation check). "
            "Step 7: Write final dθ/dt equation with the √(n_{s,2}/n_{s,1}) "
            "correction terms intact (do NOT assume n_{s,1}=n_{s,2} yet)."
        },"action_status": "failed"
    },
action_id="act_9aa985d9cc18", action_status="failed", verify_history=[{"source": "verify:lean_lake", "action_id": "act_9aa985d9cc18", "verdict": "inconclusive", "confidence": "0.400", "evidence": "lake build 失败（returncode=1），证明未完成"}])

# --- Sub-question (f): DC and AC Josephson effects from ODEs
c_josephson_effects = claim(
    "With n_{s,1} ≈ n_{s,2} ≈ n_s/2, the ODEs from (e) simplify. Density: "
    "dn_{s,1}/dt = (K n_s/ℏ) sin θ, giving the Josephson current-phase relation "
    "I_s = I_c sin θ with critical current I_c ∝ K n_s/ℏ. Phase: "
    "dθ/dt = −2eV/ℏ (the cosine term vanishes because "
    "√(n_{s,1}/n_{s,2}) − √(n_{s,2}/n_{s,1}) ≈ 0 when n_{s,1}≈n_{s,2}). "
    "DC Josephson effect (V=0): dθ/dt=0, θ=θ₀=const, "
    "I = I_c sin θ₀ — dissipationless DC supercurrent, magnitude between 0 and "
    "I_c depending on the initial phase difference. "
    "AC Josephson effect (V≠0, DC bias): θ(t)=θ₀−(2eV/ℏ)t, "
    "I(t)=I_c sin(θ₀−ω_J t) with ω_J = 2|eV|/ℏ; current oscillates at Josephson "
    "frequency, time average ⟨I(t)⟩=0. In practical units: "
    "f_J = (2e/h)|V| ≈ 483.6 MHz/μV, the precision relation used in the "
    "Josephson voltage standard. The sign dθ/dt = −2eV/ℏ follows from the "
    "convention θ = φ₁−φ₂ with H = [[eV, K], [K, −eV]]; using θ' = φ₂−φ₁ "
    "gives dθ'/dt = +2eV/ℏ — the observable frequency |2eV|/ℏ is invariant.",
    prior=0.6,
    metadata={
        "prior_justification": "The DC and AC Josephson effects are the canonical "
        "results of the STJ model; derivation from ODEs with n_{s,1}≈n_{s,2} is "
        "standard but requires careful limit-taking and distinction of V=0 vs V≠0.",
        "action": "deduction",
        "args": {
            "task": "From the ODEs derived in sub-question (e), apply the limit "
            "n_{s,1}≈n_{s,2} to recover the DC and AC Josephson effects. "
            "(1) Simplify dn/dt: with n_{s,1}≈n_{s,2}≈n_s/2, show "
            "dn_{s,1}/dt = (K n_s/ℏ) sin θ and identify I_c ∝ K n_s/ℏ. "
            "(2) Simplify dθ/dt: show the cosine term vanishes, giving "
            "dθ/dt = 2eV/ℏ. "
            "(3) DC Josephson: set V=0 → dθ/dt=0 → θ=const → I=I_c sin θ₀, "
            "dissipationless DC current between −I_c and +I_c. "
            "(4) AC Josephson: V≠0 DC bias → θ(t)=θ₀+(2eV/ℏ)t → "
            "I(t)=I_c sin(θ₀+ω_J t) with ω_J=2eV/ℏ. Time average ⟨I(t)⟩=0. "
            "(5) Give f_J in practical units: f_J=(2e/h)V≈483.6 MHz/μV. "
            "(6) Clarify naming: DC Josephson = DC current at zero voltage; "
            "AC Josephson = AC current under DC voltage."
        },"action_status": "failed"
    },
action_id="act_48377d45ee70", action_status="failed", verify_history=[{"source": "verify:lean_lake", "action_id": "act_48377d45ee70", "verdict": "inconclusive", "confidence": "0.400", "evidence": "lake build 失败（returncode=1），证明未完成"}])

# --- Abduction: stress-test c_schrodinger_eqns sign convention
c_schrodinger_sign_resolved = claim(
    "The coupled ODEs derived from iℏ dΨ/dt = HΨ with H = [[eV, K], [K, −eV]] "
    "and θ = φ₁−φ₂ produce dθ/dt = −2eV/ℏ + (K/ℏ)[√(n_{s,1}/n_{s,2}) − "
    "√(n_{s,2}/n_{s,1})] cos θ. With the n_{s,1}≈n_{s,2} limit, this gives "
    "dθ/dt = −2eV/ℏ. The Josephson current-phase relation I_s = I_c sin θ, "
    "combined with the time-integrated phase θ(t) = θ₀ − (2eV/ℏ)t, yields "
    "I(t) = I_c sin(θ₀ − ω_J t) with ω_J = 2|eV|/ℏ. Because sin is odd, "
    "I(t) = −I_c sin(ω_J t − θ₀) and the current oscillates at frequency "
    "ω_J = 2|eV|/ℏ, identical to the physical AC Josephson frequency. "
    "The sign convention choice (θ = φ₁−φ₂ vs θ = φ₂−φ₁) does not affect the "
    "observable oscillation frequency or the zero-DC-average property.",
    prior=0.5,
    metadata={
        "prior_justification": "Sign convention resolution: the physical observable "
        "(oscillation frequency) is invariant under θ → −θ because |sin θ| = |sin(−θ)|. "
        "Initial prior 0.5 reflects the abduction hypothesis status.",
    },
)

# ---------------------------------------------------------------------- strategy

support(premises=[c_const_delta], conclusion=t_target,
        reason="(a) Constant Δ_j approximation justified by ξ and GL theory, "
               "foundational to the STJ model.", prior=0.9)

support(premises=[c_k0_eigenstates], conclusion=t_target,
        reason="(b) K=0 eigenstates diagonalized, n_s conservation derived, "
               "eigenstate localization verified.", prior=0.9)

support(premises=[c_energy_change], conclusion=t_target,
        reason="(c) Energy change ΔE=−2eV matches Cooper pair charge −2e "
               "and chemical potential difference.", prior=0.9)

support(premises=[c_ac_response], conclusion=t_target,
        reason="(d) AC Josephson effect derived from energy conservation: "
               "ω_J=2eV/ℏ, I(t) oscillatory, ⟨I⟩_DC=0.", prior=0.9)

support(premises=[c_schrodinger_eqns], conclusion=t_target,
        reason="(e) Coupled ODEs for n_{s,j} and φ_j derived from TDSE; "
               "real/imaginary separation with θ=φ₁−φ₂.", prior=0.9)

support(premises=[c_josephson_effects], conclusion=t_target,
        reason="(f) DC (V=0, I=I_c sin θ₀) and AC (V≠0, I=I_c sin(θ₀+ω_J t)) "
               "Josephson effects derived from ODEs with n_{s,1}≈n_{s,2}.", prior=0.9)

# Cross-connections between sub-questions
deduction(premises=[c_k0_eigenstates], conclusion=c_energy_change,
          reason="(c) follows from (b): K=0 eigenstate energies ±eV directly "
                 "give ΔE=−2eV and the Cooper pair charge identification.",
          prior=0.95)

deduction(premises=[c_energy_change], conclusion=c_ac_response,
          reason="(d) energy-conservation argument uses ΔE=−2eV from (c) to "
                 "derive ω_J=2eV/ℏ and the AC current response.",
          prior=0.9)

deduction(premises=[c_schrodinger_eqns], conclusion=c_josephson_effects,
          reason="(f) applies n_{s,1}≈n_{s,2} limit to the ODEs from (e) to "
                 "recover DC and AC Josephson effects.",
          prior=0.95)

# Deduction: sign convention resolution for c_schrodinger_eqns
# With the corrected sign (dθ/dt = −2eV/ℏ), the physical observable
# (Josephson frequency ω_J = 2|eV|/ℏ) is invariant under θ → −θ.
deduction(premises=[c_schrodinger_eqns], conclusion=c_schrodinger_sign_resolved,
          reason="With the corrected sign dθ/dt = −2eV/ℏ + correction from (e), "
                 "the Josephson frequency ω_J = 2|eV|/ℏ is the physical observable "
                 "and is invariant under θ → −θ. The sign convention θ = φ₁−φ₂ "
                 "vs θ = φ₂−φ₁ does not affect the oscillation frequency.",
          prior=0.85)
