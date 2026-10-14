# LinkedIn post

Plain text, ready to paste. Put the repository link in the first comment. This copy makes no claim about
real LLM results because there are none yet; do not add one until `results/` contains a non-mock file for
a model, and then use the numbers from `trialgauntlet report`.

---

Most agent evals report pass@1 on a stochastic setup. That number averages over inconsistency: an agent that
solves every task half the time and an agent that solves half the tasks every time get the same score.

I built a small harness around the question "would you trust this agent to do the task right every time?"

What it does differently:
- It reports pass^k (all k independent trials succeed, the tau-bench idea, with the unbiased estimator
  C(c,k)/C(n,k)) next to pass@k.
- It audits every environment before trusting it. Each one ships no-op, random-tool and always-refuse baselines, and
  the harness flags any environment where one scores above 5%.
- Users and graders are deterministic scripts, not an LLM, so a difference between two runs of the same task comes
  from the agent or the model server, not from the benchmark.
- Prompt-injection and fault-injection wrappers work on any environment.

Numbers from the scripted agents (real, reproducible, no model involved):
- do-nothing, random and always-refuse baselines: 0.7% or less on all three environments (138 tasks)
- the same do-nothing agent against a deliberately naive final-state grader: 31 to 36%
- one deterministic scripted agent under 30% tool faults: pass@1 36 to 52%, pass^4 9 to 29%. The gap is the
  point: nothing about the agent changed, only the environment's faults.

The honest part: no real LLM has been run through it yet, and the README says so at the top. The environments are
small, the scripted users are keyword rules, the graders encode my reading of my own policies, and the audit is only
as strong as the baselines I wrote. The field is crowded (tau-bench, ReliabilityBench and others); this is not a
general benchmark. The contribution is the audit-first design and being tiny, deterministic and dependency-free.

MIT, Python 3.10+, standard library only. Critique welcome, especially from anyone who has seen a degenerate
baseline slip past a check like this one.

#AIAgents #LLM #Evals #Reliability #OpenSource
