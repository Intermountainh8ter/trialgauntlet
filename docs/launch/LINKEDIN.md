# LinkedIn post

Plain text, ready to paste (under 3,000 characters). The repository link is the last line. Every number comes from
`results/*.json` and matches the README tables; if the result files change, re-check this copy against
`trialgauntlet report results` before posting.

---

Most agent evals report pass@1 on a stochastic setup. That number averages over inconsistency: an agent that
solves every task half the time and an agent that solves half the tasks every time get the same score.

I built a small harness around "would you trust this agent to do the task right every time?" and have now run real
models through it. What it does:
- Reports pass^k (all k independent trials succeed, with the unbiased estimator C(c,k)/C(n,k)) next to pass@k.
- Audits every environment against do-nothing agents before trusting it. No-op, random-tool and always-refuse
  baselines pass at most 0.7% on my three environments (138 tasks). A deliberately naive grader lets the do-nothing
  agent pass 30.8%, 35.7% and 36.4%.
- Uses scripted users and code graders, no LLM judge, so a difference between two trials comes from the agent or
  the model server, not from the benchmark. Injection and fault wrappers exist, but so far only scripted agents
  have been run through them.

The runs: Qwen3 4B, 8B and 14B (Q8_0 GGUFs, llama.cpp, one AMD gfx906 machine), temperature 0.7, n=4 trials per task,
k=2, stock and ablated (abliterated) pairs at 8B and 14B.
- pass^2 sits below pass@1 in every cell that passes anything. 8B stock on fleet: pass@1 55.3%, pass^2 40.1%; on
  ledger 42.9% and 29.0%. The 14B gaps are smaller, 1.8 to 4.6 points.
- 8B stock vs ablated: fleet and ledger look the same (55.3% vs 54.3%, 42.9% vs 42.9% pass@1). On config, the hardest
  environment, pass@1 was 15.3% vs 5.7% and pass^2 8.0% vs 0.0%.
- 14B pair: outcome-only success is about the same, but pass@1 is lower for ablated on ledger (37.5% vs 19.6%) and
  config (22.7% vs 13.6%) and flat on fleet (46.6% both). Policy violations per trial: 8B 0.09 vs 0.21, 14B 0.40 vs 0.60.
- Qwen3-4B stock: 0.0% everywhere. Under the shared chat template its tool calls came out as plain text (13 parsed
  calls in 552 trials), a format artefact I kept as run. Under its own template: 28.8% fleet, 3.6% ledger, 1.1% config,
  and 373 of 552 trials still ended without a tool call.

What this does not show: the environments are small and synthetic, the users are keyword rules, and the graders and
the oracle were written by the same person (me). One machine, one run configuration, one model family. n=4 is small:
the 95% intervals overlap in every stock-vs-ablated pair, so read the differences as leads for a larger run, not as
settled effects. About 30% of 8B trials ended without a tool call, which confounds any 8B vs 14B comparison. I also
corrected one of my own README violation-rate statements (it used one environment's numbers); the correction is
dated there.

MIT, Python 3.10+, standard library only. Critique welcome, especially from anyone who has seen a degenerate baseline
slip past a check like this one.

#AIAgents #LLM #Evals #Reliability #OpenSource

Code, tables and caveats: https://github.com/Intermountainh8ter/trialgauntlet
