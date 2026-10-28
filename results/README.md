# results/

Aggregated result files (`*.json`, schema in `docs/METHODOLOGY.md`) live here.

* `baseline-*.json` are produced by `trialgauntlet audit --out-dir results` from the built-in
  non-LLM baseline agents. They are real, deterministic and reproducible.
* `qwen3-{4b,8b,14b}-{stock,ablated}-n4.json` and `qwen3-4b-stock-native-n4.json` are real runs of Qwen3
  models served by llama.cpp (n=4 trials per task, k=2, temperature 0.7, all 138 tasks). They are not
  regenerable without the model servers; the README table is generated from them by
  `python -m trialgauntlet.docgen`. Read the README section "LLM results" and
  `docs/THREATS_TO_VALIDITY.md` before quoting any number.
* Files labelled `MOCK` only test plumbing.
