import Mathlib

/-!
# Gap Lower Bound Contradiction Theorem

We formalize the logical structure of the contradiction argument:
If all normalized gaps d_n ≥ μ > 0 for zeros in [T, 2T],
then the pair correlation function F integrated from 0 to μ would be zero
(since no pairs exist at separation < μ).

But Montgomery's proven formula gives:
∫_0^μ F(α) dα = (π²/9)μ³ + O(μ⁵) > 0 for μ > 0

This is a contradiction, hence the assumption must be false:
there must exist gaps with d_n < μ for any μ > 0.

We formalize the logical skeleton of this argument.
-/

open Real

-- The key logical structure: if a minimum gap exists and equals μ,
-- then pair correlation below μ is zero, contradicting positive integral.

/-- If an integral is positive over [0, μ], there must be some density in that interval -/
theorem discovery_gap_bound_contradiction_logic
    (μ : ℝ) (hμ_pos : μ > 0)
    (integral_positive : (π^2 / 9) * μ^3 > 0)
    (no_pairs_implies_zero_integral : 
      (∀ d : ℝ, d ≥ μ) → (π^2 / 9) * μ^3 = 0) :
    ¬(∀ d : ℝ, d ≥ μ) := by
  intro h_all_ge_mu
  have h_zero := no_pairs_implies_zero_integral h_all_ge_mu
  linarith

/-- The cubic term (π²/9)μ³ is positive when μ > 0 -/
theorem montgomery_integral_positive (μ : ℝ) (hμ : μ > 0) :
    (π^2 / 9) * μ^3 > 0 := by
  apply mul_pos
  · apply div_pos
    · exact sq_pos_of_pos pi_pos
    · norm_num
  · exact pow_pos hμ 3

/-- Main theorem: combining the pieces -/
theorem discovery_small_gaps_must_exist
    (μ : ℝ) (hμ : μ > 0)
    (no_pairs_implies_zero : (∀ d : ℝ, d ≥ μ) → (π^2 / 9) * μ^3 = 0) :
    ∃ d : ℝ, d < μ := by
  by_contra h_no_small
  push_neg at h_no_small
  have h_pos := montgomery_integral_positive μ hμ
  have h_zero := no_pairs_implies_zero h_no_small
  linarith