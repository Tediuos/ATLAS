# Live article judge evaluation status

**Not measured in this snapshot. No live article scores are claimed.**

The Groq evaluator is implemented and tested with injected responses. Running actual article generation and judging requires `GROQ_API_KEY` in the local `.env` file.

Run `python -m atlas.evaluation.judge_run --live --samples 3 --repetitions 2` to save real articles, rubric scores, rationales, token usage and failure counts. The command replaces this status report with the observed results.

The separate 10/10 judge-protocol result uses synthetic scores and does not establish model quality.
