# X thread

Seven posts, each under 280 characters. Link goes in the last one. No claim about real LLM results.

---

1/ Most agent evals report pass@1 on a stochastic setup. It hides inconsistency: solving every task half the time
and half the tasks every time score the same. I built a tiny harness that reports pass^k next to pass@k.

2/ pass^k = all k independent trials succeed. Unbiased estimator from n >= k trials: C(c,k)/C(n,k). The repo checks it
against enumerated subsets and exact binomial expectations, and shows why the naive (c/n)^k is biased upward.

3/ Second idea: audit before you trust. Every environment ships no-op, random and always-refuse baselines, and the
harness FLAGs any where one scores above 5%. Result on my three: 0.7% or less. A naive state-diff grader: 31 to 36%
for doing nothing.

4/ Third: no LLM user simulator, no LLM judge. Scripted users and code graders, so a difference between two trials is
the agent or the server, not the benchmark. Recorded trajectories replay to the identical grade.

5/ Fourth: injection and fault wrappers for any environment. A scripted agent obeying text found in tool results gets
100% attack success when exposed. The same deterministic agent under 30% tool faults: pass@1 36 to 52%, pass^4 9 to 29%.

6/ What it is not: a general benchmark. Three small synthetic environments, keyword-rule users, graders encoding my own
policies, a baseline set that is incomplete. tau-bench and others already exist. No real LLM has been run yet. It says
so in the README.

7/ Tiny, deterministic, dependency-free (Python 3.10+, stdlib only), MIT. Point it at a local llama-server with --jinja
and run `trialgauntlet doctor` first. Feedback welcome. <repo link>
