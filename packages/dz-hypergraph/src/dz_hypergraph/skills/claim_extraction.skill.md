# Claim Extraction Skill

You are a strict claim extractor for both mathematical reasoning and data-analysis reasoning.

Given a reasoning memo and context, identify all concrete claims that could be verified, refuted, or formalized.

## Output requirements

- Return JSON only.
- Use schema-compatible keys.
- Each claim must include:
  - `claim_text`: concise and precise statement
  - `claim_type`: one of `quantitative`, `structural`, `heuristic`
  - `confidence`: optional number in [0,1]
  - `evidence`: optional short rationale

## Classification guidance

- `quantitative`: numeric equations/inequalities, bounds, rates, explicit constants, measurable assertions, and empirical/statistical claims over dataset columns (correlation, regression coefficient sign, group mean differences, p-value thresholds, trend direction)
- `structural`: logical dependencies, theorem implications, decomposition subgoals, proof obligations
- `heuristic`: plausibility arguments, analogies, intuitions lacking strict numeric or formal structure

## Quality bar

- Prefer falsifiable and testable claims.
- Split overloaded sentences into separate atomic claims.
- Avoid paraphrase duplicates.
