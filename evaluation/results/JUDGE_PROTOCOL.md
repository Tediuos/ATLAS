# LLM judge protocol evaluation

**10/10 synthetic protocol checks passed.**

Checks score ranges/types, deterministic aggregation, evidence-free score capping and rejection gates. These are tests of the judge harness, not scores assigned by a real LLM.

Run `python -m atlas.evaluation.judge_run --live` after configuring Groq to generate and judge actual articles.
