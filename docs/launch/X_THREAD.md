# X thread

Seven posts, each under 280 characters. Link goes in the last one. Every number comes from `results/*.json`
and matches the README tables. The runs are real Qwen3 runs; the limits are stated in the thread itself.

---

1/ Most agent evals report pass@1 on a stochastic setup, which hides inconsistency. I built a tiny harness that reports pass^k (all k trials succeed) next to pass@k, with scripted users and code graders, no LLM judge. Then I ran real Qwen3 models through it.

2/ First, audit the benchmark. No-op, random-tool and always-refuse baselines pass at most 0.7% on my three environments (138 tasks). A deliberately naive grader lets the do-nothing agent pass 30.8%, 35.7% and 36.4%.

3/ Qwen3 4B/8B/14B, Q8_0 on llama.cpp, one AMD gfx906 box, temp 0.7, n=4 trials per task, k=2. pass^2 sits below pass@1 in every cell that passes anything. 8B stock: fleet 55.3% -> 40.1%, ledger 42.9% -> 29.0%. 14B gaps are 1.8 to 4.6 points.

4/ Stock vs ablated (abliterated) pass@1. 8B: fleet 55.3% vs 54.3%, ledger 42.9% vs 42.9%, config 15.3% vs 5.7% (pass^2 8.0% vs 0.0%). 14B: ledger 37.5% vs 19.6%, config 22.7% vs 13.6%, fleet 46.6% both. Intervals overlap in every pair: leads, not results.

5/ Policy violations per trial, stock vs ablated: 8B 0.09 vs 0.21, 14B 0.40 vs 0.60. At 14B ablated is higher in all three environments; at 8B the difference sits on config. About 30% of 8B trials ended in no_action, which may deflate the 8B counts.

6/ Qwen3-4B stock: 0.0% everywhere. Under the shared chat template its tool calls came out as plain text (13 parsed calls in 552 trials): a format artefact, kept as run. Own template, pass@1: fleet 28.8%, ledger 3.6%, config 1.1%; 373 of 552 trials still no_action.

7/ Not shown: small synthetic environments, scripted users, graders and oracle by one author, one machine, one configuration, Qwen3 only, n=4 so cells are noisy. Code, tables, caveats: https://github.com/Intermountainh8ter/trialgauntlet
