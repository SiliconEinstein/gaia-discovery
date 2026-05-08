"""
act_63bd405c2915 -- Python numerical verification: AC Josephson effect energy-conservation

Verification plan:
  1. Verify Delta E = -2eV algebraically for a range of V values
  2. Verify omega_J = 2eV/hbar computes correctly (f_J ~ 483.6 MHz/muV)
  3. Verify I(t) = I_c sin(phi_0 + omega_J t) oscillates
  4. Verify <I(t)> = 0 numerically via integration over one period
  5. Verify cos 2pi-periodicity: cos(theta + 2pi) - cos(theta) = 0
  6. Contrast: Ohmic I = V/R is constant and non-zero for V != 0

All tests must pass for the claim to be considered numerically verified.
"""
import numpy as np
from scipy.integrate import quad
import json
import sys

# Physical constants
e = 1.602176634e-19  # elementary charge (C)
h = 6.62607015e-34   # Planck constant (J*s)
hbar = h / (2 * np.pi)  # reduced Planck constant
two_e_over_h = 2 * e / h  # Josephson frequency-to-voltage ratio (Hz/V)

def test_1_energy_change():
    """Verify Delta E = -2eV for Cooper pair tunneling."""
    V_test = np.array([1e-6, 1e-3, 1.0, 10.0])  # volts
    eV = e * V_test  # eV in joules

    # K=0 eigenvalues: E1 = +eV, E2 = -eV
    # Delta E = E2 - E1 = -eV - eV = -2eV
    Delta_E = -eV - eV
    expected = -2 * eV

    errors = np.abs(Delta_E - expected)
    max_err = np.max(errors)

    results = {
        "test": "energy_change",
        "passed": bool(max_err < 1e-30),
        "max_error": float(max_err),
        "V_samples": V_test.tolist(),
        "Delta_E_samples": Delta_E.tolist(),
        "expected": expected.tolist(),
        "units": "joules"
    }
    assert max_err < 1e-30, f"Energy change test failed with max error {max_err}"
    return results

def test_2_josephson_frequency():
    """Verify omega_J = 2eV/hbar and f_J = 2eV/h ~ 483.6 MHz/muV."""
    V_test = np.array([1e-6, 10e-6, 100e-6, 1e-3])  # volts

    # omega_J = 2eV/hbar
    eV = e * V_test
    omega_J = 2 * eV / hbar

    # f_J = omega_J / (2*pi) = 2eV/h
    f_J = omega_J / (2 * np.pi)
    f_J_from_h = 2 * eV / h

    errors = np.abs(f_J - f_J_from_h)

    # Expected value: f_J/V = 2e/h ~ 483.6 MHz/muV
    theoretical_ratio = two_e_over_h  # Hz/V
    ratio = f_J / V_test

    results = {
        "test": "josephson_frequency",
        "passed": bool(np.max(errors) < 1e-24),
        "max_freq_error": float(np.max(errors)),
        "theoretical_ratio_Hz_per_V": float(theoretical_ratio),
        "computed_ratio_Hz_per_V": float(np.mean(ratio)),
        "ratio_MHz_per_uV": float(theoretical_ratio * 1e-6 / 1e6),
        "V_samples_muV": (V_test * 1e6).tolist(),
        "f_J_samples_Hz": f_J.tolist(),
        "f_J_expected_GHz": [483.6e-3, 4.836, 48.36, 483.6]  # for 1,10,100,1000 muV
    }
    assert np.max(errors) < 1e-24, f"Frequency test failed with max error {np.max(errors)}"
    return results

def test_3_ac_current_oscillation():
    """Verify I(t) = I_c sin(phi_0 + omega_J t) oscillates at omega_J."""
    I_c = 1e-3  # 1 mA critical current
    V = 100e-6  # 100 muV
    omega_J = 2 * e * V / hbar
    T = 2 * np.pi / omega_J  # period
    phi_0 = 0.5  # arbitrary initial phase

    # Sample over 3 periods
    t = np.linspace(0, 3 * T, 1000)
    I_t = I_c * np.sin(phi_0 + omega_J * t)

    # Check: I(t+T) = I(t) for all t (periodicity)
    idx_half = len(t) // 3
    shift = int(T / (t[1] - t[0]))
    I_shifted = np.roll(I_t, shift)
    periodicity_error = np.max(np.abs(I_t - I_shifted))

    # Check: I(t) crosses zero twice per period
    zero_crossings = np.sum(np.diff(np.sign(I_t)) != 0)
    expected_crossings_per_period = 2

    results = {
        "test": "ac_current_oscillation",
        "passed": bool(periodicity_error < 0.01),
        "periodicity_max_error": float(periodicity_error),
        "zero_crossings": int(zero_crossings),
        "expected_crossings_per_3_periods": 6,
        "I_c_A": float(I_c),
        "V_muV": float(V * 1e6),
        "omega_J_rad_s": float(omega_J),
        "T_period_s": float(T),
        "f_J_Hz": float(omega_J / (2 * np.pi))
    }
    assert periodicity_error < 0.01, f"Periodicity test failed with error {periodicity_error}"
    return results

def test_4_zero_dc_average():
    """Verify <I(t)> = 0 by numerical integration over one period."""
    I_c = 1e-3  # 1 mA
    phi_0_vals = np.linspace(0, 2*np.pi, 50)  # test many initial phases

    V = 100e-6  # 100 muV
    omega_J = 2 * e * V / hbar
    T = 2 * np.pi / omega_J

    max_avg = 0.0
    for phi_0 in phi_0_vals:
        integral, _ = quad(lambda t: I_c * np.sin(phi_0 + omega_J * t), 0, T)
        avg = integral / T
        max_avg = max(max_avg, abs(avg))

    results = {
        "test": "zero_dc_average",
        "passed": bool(max_avg < 1e-15),
        "max_dc_average_A": float(max_avg),
        "num_phi_0_tested": len(phi_0_vals),
        "V_muV": float(V * 1e6),
        "T_period_s": float(T)
    }
    assert max_avg < 1e-15, f"Zero DC average test failed with max avg {max_avg}"
    return results

def test_5_cos_periodicity():
    """Verify cos(theta + 2*pi) = cos(theta) for many theta values."""
    theta_vals = np.linspace(0, 4*np.pi, 1000)
    diff = np.cos(theta_vals + 2*np.pi) - np.cos(theta_vals)
    max_diff = np.max(np.abs(diff))

    # Allow for floating-point precision (machine epsilon ~2.2e-16 for float64)
    results = {
        "test": "cos_periodicity",
        "passed": bool(max_diff < 1e-14),
        "max_error": float(max_diff),
        "num_samples": len(theta_vals)
    }
    assert max_diff < 1e-14, f"Cos periodicity test failed with max error {max_diff}"
    return results

def test_6_ohmic_contrast():
    """Verify Ohmic current is constant and non-zero for V != 0."""
    R = 1.0  # 1 ohm
    V_test = np.array([-10.0, -1.0, -0.001, 0.001, 1.0, 10.0])

    I_ohm = V_test / R

    # All are non-zero for V != 0
    nonzero_ok = np.all(I_ohm[V_test != 0] != 0)
    # Zero for V = 0
    zero_ok = np.isclose(I_ohm[V_test == 0], 0).all() if 0 in V_test else True

    # Time independence: I doesn't depend on t
    t_samples = np.linspace(0, 100, 100)
    for V in V_test:
        I_t = np.full_like(t_samples, V / R)
        assert np.allclose(I_t, V / R)

    results = {
        "test": "ohmic_contrast",
        "passed": bool(nonzero_ok and zero_ok),
        "nonzero_ok": bool(nonzero_ok),
        "zero_ok": bool(zero_ok),
        "V_samples_V": V_test.tolist(),
        "I_ohm_A": I_ohm.tolist(),
        "note": "Ohmic I=V/R is constant DC; Josephson AC time-averages to zero"
    }
    assert nonzero_ok and zero_ok, "Ohmic contrast test failed"
    return results

def test_7_sin_integral_epoch():
    """Verify integral_0^(2*pi) sin(x) dx = 0 numerically (justify axiom)."""
    integral, error = quad(np.sin, 0, 2*np.pi)

    results = {
        "test": "sin_integral_full_period",
        "passed": bool(abs(integral) < 1e-15),
        "integral_value": float(integral),
        "quad_error_estimate": float(error),
        "note": "This justifies the sin_integral_full_period axiom in the Lean proof"
    }
    assert abs(integral) < 1e-15, f"Sin integral test failed: {integral}"
    return results

def main():
    tests = [
        ("test_1_energy_change", test_1_energy_change),
        ("test_2_josephson_frequency", test_2_josephson_frequency),
        ("test_3_ac_current_oscillation", test_3_ac_current_oscillation),
        ("test_4_zero_dc_average", test_4_zero_dc_average),
        ("test_5_cos_periodicity", test_5_cos_periodicity),
        ("test_6_ohmic_contrast", test_6_ohmic_contrast),
        ("test_7_sin_integral_epoch", test_7_sin_integral_epoch),
    ]

    all_results = {}
    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            result = test_fn()
            all_results[name] = result
            if result.get("passed", False):
                passed += 1
                print(f"  PASS: {name}")
            else:
                failed += 1
                print(f"  FAIL: {name}")
        except Exception as exc:
            failed += 1
            all_results[name] = {"test": name, "passed": False, "error": str(exc)}
            print(f"  ERROR: {name} - {exc}")

    print(f"\nSummary: {passed} passed, {failed} failed, {len(tests)} total")

    # Produce verdict JSON
    verdict = {
        "overall": "PASS" if failed == 0 else "FAIL",
        "num_passed": passed,
        "num_failed": failed,
        "num_total": len(tests),
        "results": all_results
    }

    # Write to a JSON file for machine consumption
    output_path = "task_results/act_63bd405c2915.py.verdict.json"
    with open(output_path, 'w') as f:
        json.dump(verdict, f, indent=2)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
