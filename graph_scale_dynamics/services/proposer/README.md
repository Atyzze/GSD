# Proposer

The proposer is a target-blind candidate source. It never launches jobs, writes
scientific decisions, or imports measurement estimators.

The proposer combines curated enumeration, lineage mutation, random novelty, and an
optional local LLM suggestion source. All candidates pass the same restricted
DSL validation, complexity budget, normalization, and exact fingerprint dedupe.

The proposal landscape includes operator subsets, coefficients, signs,
coefficient scaling primitives, anchor parameters, beta, and lineage. Constant,
mixed, and fully N-coupled laws are explicit allocation strata.

Graded family and coefficient-region memory changes sampling probability but
never creates a zero-probability scientific exclusion. Configure an existing
campaign with:

```text
python main.py proposal status
python main.py proposal mode active
```
