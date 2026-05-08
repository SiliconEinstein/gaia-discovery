#!/usr/bin/env python3
"""
Numerical model: Protein depletion kinetics after inducible shRNA knockdown.

Models the combined effect of doxycycline-induced shRNA transcription,
target mRNA degradation, and first-order protein decay to predict
western blot band intensity changes over a 24h/48h/72h time course.
"""
import numpy as np
import json
import sys


def residual_protein(t_hours, t_lag=6, t_half_mrna=4, t_half_protein=6,
                     knockdown_efficiency=0.90):
    """
    Compute fraction of target protein remaining after dox induction.

    Parameters
    ----------
    t_hours : float
        Time post-doxycycline induction (hours).
    t_lag : float
        Lag time before shRNA reaches effective concentration (hours).
    t_half_mrna : float
        Target mRNA half-life after shRNA-mediated degradation begins (hours).
    t_half_protein : float
        Protein half-life (hours). For CHEK1, estimated 4-8 hours.
    knockdown_efficiency : float
        Fraction of mRNA degraded at steady state (0-1). Typical 0.85-0.95.

    Returns
    -------
    float : Fraction of initial protein level remaining.
    """
    if t_hours <= t_lag:
        return 1.0

    t_eff = t_hours - t_lag
    k_mrna = np.log(2) / t_half_mrna
    k_deg = np.log(2) / t_half_protein

    # mRNA level at time t_eff after induction
    mrna_frac = 1.0 - knockdown_efficiency * (1.0 - np.exp(-k_mrna * t_eff))

    # Solve dP/dt = k_syn*mrna - k_deg*P numerically
    # At steady state before induction: P0 = 1, mrna0 = 1
    # dP/dt = k_deg*(mrna_frac - P)
    dt = 0.05  # hours
    n_steps = int(t_eff / dt)
    P = 1.0
    for i in range(n_steps):
        tau = i * dt
        mrna_t = 1.0 - knockdown_efficiency * (1.0 - np.exp(-k_mrna * tau))
        dP = k_deg * (mrna_t - P) * dt
        P += dP
    return max(P, 1.0 - knockdown_efficiency)


def main():
    # Define parameter ranges
    scenarios = [
        {"name": "Conservative", "t_lag": 8, "t_half_mrna": 6, "t_half_protein": 8},
        {"name": "Typical",     "t_lag": 6, "t_half_mrna": 4, "t_half_protein": 6},
        {"name": "Fast",        "t_lag": 4, "t_half_mrna": 2, "t_half_protein": 4},
        {"name": "Slow protein","t_lag": 6, "t_half_mrna": 4, "t_half_protein": 24},
    ]

    results = {}
    print("=" * 70)
    print("INDUCIBLE shRNA KNOCKDOWN: PROTEIN DEPLETION MODEL")
    print("=" * 70)
    for sc in scenarios:
        print(f"\n--- {sc['name']} scenario ---")
        print(f"    lag={sc['t_lag']}h, mRNA t1/2={sc['t_half_mrna']}h, protein t1/2={sc['t_half_protein']}h")
        times = [0, 12, 24, 36, 48, 60, 72, 96]
        sc_results = {}
        for t in times:
            level = residual_protein(t, sc["t_lag"], sc["t_half_mrna"], sc["t_half_protein"])
            depletion = (1 - level) * 100
            sc_results[t] = round(level, 3)
            print(f"    t={t:3d}h: {level:.3f} ({depletion:.1f}% depletion)")
        results[sc["name"]] = sc_results

    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    print("""
Under all plausible parameter regimes for a Tet-On inducible shRNA system:
  - At 24h post-dox: partial knockdown (25-85% depletion depending on kinetics)
  - At 48h post-dox: substantial reduction (58-88% depletion)
  - At 72h post-dox: near-maximal knockdown (74-90% depletion)

The housekeeping protein (e.g., GAPDH, beta-actin) is not targeted by the
shRNA and its expression is unaffected. Its band intensity on western blot
remains constant across all time points, serving as a loading control.

Expected western blot appearance:
  Time:       0h    24h    48h    72h
  CHEK1 band: ====  ===    =      .
  HK band:    ====  ====   ====   ====
    """)

    return results


if __name__ == "__main__":
    main()
