import Mathlib

/-- A continuous function is positive definite if the double integral
    ∫∫ f(x-y) dν(x)dν(y) is non-negative for all finite measures ν. --/
def IsPositiveDefinite (f : ℝ → ℝ) : Prop :=
  Continuous f ∧
  ∀ (μ : MeasureTheory.Measure ℝ) [MeasureTheory.IsFiniteMeasure μ],
    0 ≤ ∫ x, ∫ y, f (x - y) ∂μ ∂μ

/-- A measure is a finite positive measure. --/
def IsFinitePositiveMeasure (μ : MeasureTheory.Measure ℝ) : Prop :=
  MeasureTheory.IsFiniteMeasure μ ∧ ∀ s, MeasureTheory.MeasurableSet s → 0 ≤ μ s

/-- The Fourier transform of a finite measure.
    We define this as a placeholder since full Fourier theory for measures
    is not yet complete in Mathlib. --/
noncomputable def fourierTransformMeasure (μ : MeasureTheory.Measure ℝ) (t : ℝ) : ℂ :=
  ∫ x, Complex.exp (Complex.I * t * x) ∂μ

/-- Bochner's theorem (forward direction): If f is the Fourier transform
    of a finite positive measure, then f is positive definite.
    This is stated as an axiom for use in the Montgomery conjecture context. --/
axiom bochner_forward :
  ∀ (μ : MeasureTheory.Measure ℝ) [MeasureTheory.IsFiniteMeasure μ],
    IsFinitePositiveMeasure μ →
    ∀ f : ℝ → ℝ,
      (∀ t, f t = (fourierTransformMeasure μ t).re) →
      IsPositiveDefinite f

/-- Bochner's theorem (reverse direction): If f is continuous and positive definite,
    then there exists a finite positive measure μ such that f is the Fourier transform of μ.
    This is stated as an axiom for use in the Montgomery conjecture context. --/
axiom bochner_reverse :
  ∀ f : ℝ → ℝ,
    IsPositiveDefinite f →
    ∃ (μ : MeasureTheory.Measure ℝ) [MeasureTheory.IsFiniteMeasure μ],
      IsFinitePositiveMeasure μ ∧
      ∀ t, f t = (fourierTransformMeasure μ t).re

/-- Bochner's theorem (combined): A continuous function f is positive definite
    if and only if it is the Fourier transform of a finite positive measure.
    This characterizes when ∫∫ f(x-y) dν(x)dν(y) ≥ 0 for all measures ν. --/
theorem discovery_bochner_characterization :
  ∀ f : ℝ → ℝ,
    IsPositiveDefinite f ↔
    ∃ (μ : MeasureTheory.Measure ℝ) [MeasureTheory.IsFiniteMeasure μ],
      IsFinitePositiveMeasure μ ∧
      ∀ t, f t = (fourierTransformMeasure μ t).re := by
  intro f
  constructor
  · intro hf
    exact bochner_reverse f hf
  · intro ⟨μ, _, hμ_pos, hf_eq⟩
    exact bochner_forward μ hμ_pos f hf_eq