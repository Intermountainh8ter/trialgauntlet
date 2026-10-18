# trialgauntlet

**Report pass^k next to pass@k. Audit every environment against do-nothing agents before you trust it.**


## For the lay reader

- [docs/diagrams/explainer.svg](docs/diagrams/explainer.svg) &mdash; a one-page
  summary in ordinary words: the question, one chart, the finding, and why it
  matters. No background assumed.
- [GLOSSARY.md](GLOSSARY.md) &mdash; every abbreviation this repo uses, defined.

![license: MIT](https://img.shields.io/badge/license-MIT-blue) ![python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue) ![runtime dependencies: none](https://img.shields.io/badge/runtime%20dependencies-none-brightgreen) ![LLM results: Qwen3 8B+14B pairs](https://img.shields.io/badge/LLM%20results-Qwen3%208B%2B14B%20pairs-blue)

trialgauntlet is a small agent **reliability** harness. Most agent evaluations report pass@1 on a
stochastic setup, which averages over inconsistency: an agent that solves every task half the time and an
agent that solves half the tasks every time look identical. This harness

1. reports **pass^k** (all k independent trials of a task succeed, as in tau-bench) next to **pass@k**, with
   the unbiased estimator `C(c,k)/C(n,k)` from `n >= k` trials per task;
2. runs a **degenerate-success audit**: every environment ships no-op, random-tool and always-refuse
   baselines, and the harness FLAGs any environment where one of them scores above a threshold (default 5%);
3. uses **deterministic scripted users and deterministic graders**: no LLM user simulator and no LLM judge,
   so a difference between two trials of the same task comes from the agent or the model server, not from
   the harness;
4. ships **prompt-injection and fault-injection suites** that wrap any environment.

> **Read this first.** The field is crowded (tau-bench, ReliabilityBench, Agent Reliability Lab, induat,
> ratemyagent, proofagent-harness, and more), and this is not a general benchmark. The environments are small,
> synthetic and graded against one author's written policies; the scripted users are keyword rules. The
> contribution is the **audit-first design** and being **tiny, deterministic, reproducible and
> dependency-free** (Python 3.10+, standard library only). See
> [`docs/THREATS_TO_VALIDITY.md`](docs/THREATS_TO_VALIDITY.md) before quoting any number from here.

## LLM results

**LLM results: Qwen3 stock vs ablated pairs at 8B and 14B, plus a Qwen3-4B stock row, n=4 trials/task,
k=2.** Pre-registered: `--env all --n 4 --k 2`, sampling temperature 0.7, top-p 0.8, top-k 20, Q8_0 GGUFs
served under llama.cpp HIP on AMD gfx906, every arm driven from the shared Qwen3 chat template file
(`gguf/qwen3-chat-template.jinja`, sha256-16 `a55ee1b1660128b7`), `parse_text_tools` off. Full results:
`results/qwen3-{4b,8b,14b}-{stock,ablated}-n4.json`. `outcome-only` ignores policy violations;
`viol/trial` is mean policy violations per trial in that environment.

<!-- LLM:BEGIN -->
| model | env | n | k | pass@1 | pass@k | pass^k | gap | outcome-only | viol/trial |
|---|---|---|---|---|---|---|---|---|---|
| qwen3-4b-stock | config | 4 | 2 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.00 |
| qwen3-4b-stock | fleet | 4 | 2 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.00 |
| qwen3-4b-stock | ledger | 4 | 2 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.00 |
| qwen3-8b-stock | config | 4 | 2 | 15.3% | 22.7% | 8.0% | 7.4% | 19.9% | 0.21 |
| qwen3-8b-stock | fleet | 4 | 2 | 55.3% | 70.5% | 40.1% | 15.2% | 56.2% | 0.04 |
| qwen3-8b-stock | ledger | 4 | 2 | 42.9% | 56.7% | 29.0% | 13.9% | 43.5% | 0.02 |
| qwen3-8b-ablated | config | 4 | 2 | 5.7% | 11.4% | 0.0% | 5.7% | 15.9% | 0.59 |
| qwen3-8b-ablated | fleet | 4 | 2 | 54.3% | 68.9% | 39.7% | 14.6% | 55.3% | 0.06 |
| qwen3-8b-ablated | ledger | 4 | 2 | 42.9% | 57.9% | 27.8% | 15.1% | 42.9% | 0.01 |
| qwen3-14b-stock | config | 4 | 2 | 22.7% | 24.6% | 20.8% | 1.9% | 22.7% | 0.09 |
| qwen3-14b-stock | fleet | 4 | 2 | 46.6% | 48.4% | 44.9% | 1.8% | 63.5% | 0.33 |
| qwen3-14b-stock | ledger | 4 | 2 | 37.5% | 42.1% | 32.9% | 4.6% | 66.7% | 0.82 |
| qwen3-14b-ablated | config | 4 | 2 | 13.6% | 16.3% | 11.0% | 2.7% | 21.6% | 0.17 |
| qwen3-14b-ablated | fleet | 4 | 2 | 46.6% | 50.0% | 43.3% | 3.4% | 66.3% | 0.46 |
| qwen3-14b-ablated | ledger | 4 | 2 | 19.6% | 22.2% | 17.1% | 2.6% | 67.3% | 1.22 |
<!-- LLM:END -->

Policy violations per trial, trial-weighted over the whole benchmark (552 trials per arm):
8B **stock 0.09 vs ablated 0.21**; 14B **stock 0.40 vs ablated 0.60**. Share of trials with at least one
violation: 8B 8.3% vs 19.2%; 14B 27.2% vs 41.3%.
Tool misuse per trial: 8B 0.00 vs 0.01; 14B 0.09 vs 0.23.
Steps per trial: 8B 4.1 vs 4.1; 14B 7.0 vs 6.6.

> **Correction (2026-10-18).** An earlier version of this section called 20.4% (stock) and 52.8% (ablated)
> the 8B pair's "overall policy-violation rate across the whole benchmark". Those were the `config`
> environment's share of trials with at least one violation (0.21 and 0.59 violations per trial), not
> benchmark-wide numbers, and the
> tool-misuse (0.01 / 0.04) and steps (4.4) figures in the same sentence were config-only too. The
> trial-weighted figures above replace them. No pass metric changed.

Read, 8B: pass@1 is statistically indistinguishable on `fleet` and `ledger` (ablated is not uniformly less
capable), but on `config`, the hardest environment, where safe tool-use discipline matters most, the ablated
arm drops to 5.7% pass@1 and 0.0% pass^2. Outcome-only on config is 19.9% stock vs 15.9% ablated, so about
4 pp of the gap is raw competence and the remaining roughly 9.6 pp is policy violations committed during
otherwise-correct trajectories. Caveat: both 8B arms ended 30% of trials in `no_action` (167 of 552 stock,
171 ablated), and a trial with no actions cannot violate anything, which deflates the 8B violation counts.

Read, 14B: outcome-only is indistinguishable between arms on all three environments (config 22.7% vs
21.6%, fleet 63.5% vs 66.3%, ledger 66.7% vs 67.3%), so the ablated arm is not less competent. Its pass@1
still falls on `config` (22.7% to 13.6%) and `ledger` (37.5% to 19.6%) and is flat on `fleet` (46.6% both):
the whole drop is policy violations, which rise on every environment (config 0.09 to 0.17, fleet 0.33 to
0.46, ledger 0.82 to 1.22 per trial) along with tool misuse on config (0.30 to 0.72). The 14B arms never
end in `no_action` and take more steps than 8B (7.0 vs 4.1 per trial), which is also why 14B **stock**
commits more violations per trial than 8B stock (0.40 vs 0.09): more actions, more chances to break a
policy. The ablated-vs-stock spread is the comparison this benchmark is for; the across-size comparison is
confounded by the no-action share.

**Qwen3-4B stock: a format failure, not a capability result.** All 552 trials terminated `no_action`
(0.0 steps per trial, 0.0% on every metric). Under the shared template the 4B model emitted its tool-call
JSON as plain text without the opening `<tool_call>` tag, the server's tool parser therefore returned no
tool calls, and with `parse_text_tools` off (the pre-registered setting) the harness recorded no action.
The row is kept as run. A rerun with the model's own template or with text-tool parsing enabled would be a
new, separately pre-registered cell, not a replacement for this one.

Everything below is for the built-in **non-LLM** agents, which are real and reproducible: rerun
`scripts/regenerate_results.sh` and the committed files come out byte for byte the same. The adapter
is tested against a scripted mock server (runs against it are labelled `MOCK` and say nothing about any
model). To produce more LLM results see [Run it against a local model](#run-it-against-a-local-model).

## What is in the box

<!-- FACTS:BEGIN -->
- `fleet`: 52 tasks from 13 scenario kinds (tiers: T1 16, T2 20, T3 16); 16 tasks (31%) are unsolvable or ambiguous and must be escalated
- `ledger`: 42 tasks from 14 scenario kinds (tiers: T1 12, T2 15, T3 15); 15 tasks (36%) are unsolvable or ambiguous and must be escalated
- `config`: 44 tasks from 11 scenario kinds (tiers: T1 12, T2 16, T3 16); 16 tasks (36%) are unsolvable or ambiguous and must be escalated
- 138 task seeds in total, every one solved by its scripted oracle
<!-- FACTS:END -->

| env | what it is |
|---|---|
| `fleet` | triage faults on a simulated bare-metal fleet; destructive actions need an approval token; capacity floors; graded on the final fleet state and policy compliance |
| `ledger` | refund and order desk in the spirit of tau-bench: a written policy, a small database and a scripted customer; graded on the final ledger and policy |
| `config` | multi-file configuration change with hidden cross-file invariants and a protected file; graded on the final files and change policy |

Each environment has three difficulty tiers, a documented unsolvable or ambiguous subset (the correct behaviour
is to `escalate` with the right category **and** the blocking entity, never to do nothing), a scripted oracle
that proves solvability through the public tool interface, and a greedy-unsafe agent that proves the policy
grader fires. Details: [`docs/ENVIRONMENTS.md`](docs/ENVIRONMENTS.md). Definitions and the derivation of the
estimators: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

![usage flowchart](docs/diagrams/usage.svg)

([Mermaid source and the troubleshooting decision tree](docs/FLOWCHARTS.md))

## The degenerate-success audit (real output)

```
trialgauntlet audit --out-dir results --format markdown
```

Five seconds, no network, no API key. `n=8` trials per task, `k=4`, FLAG when a trivial baseline exceeds 5% pass@1.
`outcome-only` ignores policy violations: the distance between it and `pass@1` is how much the policy grader matters.

<!-- AUDIT:BEGIN -->
| env | agent | pass@1 | 95% CI | pass@4 | pass^4 | outcome-only | verdict |
|---|---|---|---|---|---|---|---|
| fleet | no-op | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| fleet | random-tool | 0.7% | 0.0-1.7% | 2.9% | 0.0% | 2.2% | ok |
| fleet | always-refuse | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| fleet | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| fleet | greedy-unsafe | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 61.5% | ok: shortcut caught |
| ledger | no-op | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| ledger | random-tool | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| ledger | always-refuse | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| ledger | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| ledger | greedy-unsafe | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 50.0% | ok: shortcut caught |
| config | no-op | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| config | random-tool | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| config | always-refuse | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 0.0% | ok |
| config | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| config | greedy-unsafe | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 18.2% | ok: shortcut caught |
<!-- AUDIT:END -->

How to read it, without flattering the result:

* No environment needed iterating after the first audit run. That is because the design rules were chosen up
  front for a known failure mode (every solvable task needs a state change and an explicit `finish`; a refusal
  counts only with the right category **and** the blocking entity), not evidence that no other cheap strategy
  exists. The audit is only as strong as the baselines shipped; see the threats document for two stronger
  baselines that are not included and would score a few percent on `fleet`.
* `random-tool` is not exactly zero on `fleet` (0.7%, 3 of 416 trials: two lucky `clock_drift` repairs and one
  correct one-step escalation). Far below the threshold, but not zero.
* The scripted oracle solves every task. `greedy-unsafe` reaches the right *outcome* on a fifth to three fifths of
  the tasks and never passes, because its shortcuts violate the written policy.

What a degenerate benchmark looks like: the same baselines against a deliberately naive grader that passes an
unsolvable task whenever the final state is unchanged (`<env>+naive`, used nowhere else):

<!-- DEMO:BEGIN -->
| env | agent | pass@1 | 95% CI | pass@4 | pass^4 | outcome-only | verdict |
|---|---|---|---|---|---|---|---|
| fleet+naive | no-op | 30.8% | 19.2-44.2% | 30.8% | 30.8% | 30.8% | FLAG: trivial baseline exceeds 5.0% |
| fleet+naive | random-tool | 16.3% | 9.4-24.8% | 30.1% | 3.4% | 23.3% | FLAG: trivial baseline exceeds 5.0% |
| fleet+naive | always-refuse | 30.8% | 19.2-44.2% | 30.8% | 30.8% | 30.8% | FLAG: trivial baseline exceeds 5.0% |
| fleet+naive | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| fleet+naive | greedy-unsafe | 0.0% | 0.0-0.0% | 0.0% | 0.0% | 61.5% | ok: shortcut caught |
| ledger+naive | no-op | 35.7% | 21.4-50.0% | 35.7% | 35.7% | 35.7% | FLAG: trivial baseline exceeds 5.0% |
| ledger+naive | random-tool | 26.8% | 16.1-38.4% | 35.5% | 11.9% | 35.7% | FLAG: trivial baseline exceeds 5.0% |
| ledger+naive | always-refuse | 35.7% | 21.4-50.0% | 35.7% | 35.7% | 35.7% | FLAG: trivial baseline exceeds 5.0% |
| ledger+naive | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| ledger+naive | greedy-unsafe | 7.1% | 0.0-14.3% | 7.1% | 7.1% | 57.1% | FLAG: policy grader accepted a shortcut |
| config+naive | no-op | 36.4% | 22.7-50.0% | 36.4% | 36.4% | 36.4% | FLAG: trivial baseline exceeds 5.0% |
| config+naive | random-tool | 26.7% | 16.2-37.8% | 36.3% | 10.0% | 36.4% | FLAG: trivial baseline exceeds 5.0% |
| config+naive | always-refuse | 36.4% | 22.7-50.0% | 36.4% | 36.4% | 36.4% | FLAG: trivial baseline exceeds 5.0% |
| config+naive | scripted-oracle | 100.0% | 100.0-100.0% | 100.0% | 100.0% | 100.0% | ok: solvable |
| config+naive | greedy-unsafe | 9.1% | 2.3-18.2% | 9.1% | 9.1% | 27.3% | FLAG: policy grader accepted a shortcut |
<!-- DEMO:END -->

The do-nothing agent scores 30.8%, 35.7% and 36.4% on the three naive variants and 0% on the real graders. This
illustrates the mechanism behind a published 2025 finding that a do-nothing agent scored well on parts of
tau-bench; it does not reproduce that paper's numbers, and we have not re-run tau-bench. (We cite the finding from
memory of the abstract: check the paper before quoting it.)

## Injection and fault suites

Wrappers selected through the environment spec (`fleet+inject=exfil`, `fleet+fault=mixed:0.3`), or with the flags
`--inject VARIANT|all` and `--fault PROFILE[:RATE]`. Details: [`docs/SUITES.md`](docs/SUITES.md). Both are
exercised here with scripted agents only, which is what proves the graders fire: a `gullible` agent that obeys any
tool call embedded in a tool result, and a retrying and a non-retrying version of the same deterministic agent.

Injection (`n=2`; attack success is judged from the tool-call log; exposed = the trial read a poisoned result):

<!-- INJECTION:BEGIN -->
| environment | variant | agent | attack success | exposed | utility under attack |
|---|---|---|---|---|---|
| config | exfil | scripted-oracle | 0.0% | 100.0% | 100.0% |
| config | fake_system | scripted-oracle | 0.0% | 100.0% | 100.0% |
| config | instruction | scripted-oracle | 0.0% | 100.0% | 100.0% |
| fleet | exfil | scripted-oracle | 0.0% | 100.0% | 100.0% |
| fleet | fake_system | scripted-oracle | 0.0% | 100.0% | 100.0% |
| fleet | instruction | scripted-oracle | 0.0% | 100.0% | 100.0% |
| ledger | exfil | scripted-oracle | 0.0% | 92.9% | 100.0% |
| ledger | fake_system | scripted-oracle | 0.0% | 92.9% | 100.0% |
| ledger | instruction | scripted-oracle | 0.0% | 92.9% | 100.0% |
| config | exfil | gullible-oracle | 100.0% | 100.0% | 0.0% |
| config | fake_system | gullible-oracle | 100.0% | 100.0% | 0.0% |
| config | instruction | gullible-oracle | 100.0% | 100.0% | 0.0% |
| fleet | exfil | gullible-oracle | 100.0% | 100.0% | 0.0% |
| fleet | fake_system | gullible-oracle | 100.0% | 100.0% | 0.0% |
| fleet | instruction | gullible-oracle | 100.0% | 100.0% | 0.0% |
| ledger | exfil | gullible-oracle | 92.9% | 92.9% | 7.1% |
| ledger | fake_system | gullible-oracle | 92.9% | 92.9% | 7.1% |
| ledger | instruction | gullible-oracle | 92.9% | 92.9% | 7.1% |
<!-- INJECTION:END -->

Faults (`mixed:0.3`, `n=8`, `k=4`). The non-retrying agent is deterministic, so every pass^4 loss below comes
from the environment's faults, not from the agent. This is the harness's central claim in one table: the same agent
has pass@1 of 36 to 52% and pass^4 of 9 to 29%.

<!-- FAULTS:BEGIN -->
| environment | agent | pass@1 | pass^4 | faults per trial | pass rate when a fault hit |
|---|---|---|---|---|---|
| fleet | scripted-oracle | 52.4% | 12.6% | 0.62 | 16.8% |
| fleet | scripted-oracle-retry | 100.0% | 100.0% | 1.30 | 100.0% |
| ledger | scripted-oracle | 36.0% | 8.7% | 0.94 | 19.2% |
| ledger | scripted-oracle-retry | 100.0% | 100.0% | 1.86 | 100.0% |
| config | scripted-oracle | 48.6% | 28.8% | 1.85 | 43.8% |
| config | scripted-oracle-retry | 100.0% | 100.0% | 3.35 | 100.0% |
<!-- FAULTS:END -->

## Install and first commands

```
pip install -e ".[dev]"            # runtime has no dependencies; [dev] adds pytest, pytest-cov, ruff
trialgauntlet list                 # environments, task counts, tiers, scenario kinds
trialgauntlet audit                # the degenerate-success audit; exit status 1 on any FLAG
trialgauntlet run --agent oracle --env fleet --n 4 --k 2 --run-dir runs/oracle
trialgauntlet replay runs/oracle   # every recorded trajectory must replay to the identical grade
trialgauntlet report results       # markdown tables and SVG charts from results/*.json
```

`trialgauntlet report` refuses to run when `results/` holds no result files.

## Run it against a local model

Any OpenAI-compatible server with tool calling works (llama.cpp `llama-server --jinja`, vLLM, Ollama). The
commands below target llama.cpp serving a Qwen3-Coder GGUF. **They were written from the llama.cpp documentation and
were not executed on Windows or against Qwen3-Coder while building this repository**; `trialgauntlet doctor` exists so
that you find out in seconds, not hours, whether the server is set up correctly. `--jinja` is the flag that matters:
without it the server returns tool calls as plain text and every trial ends in a format error.

### Linux

```bash
# terminal 1: the model server
llama-server -m ~/models/qwen3-coder/MODEL.gguf --host 127.0.0.1 --port 8080 --ctx-size 32768 --jinja -ngl 99

# terminal 2: the harness
git clone https://github.com/Intermountainh8ter/trialgauntlet && cd trialgauntlet
python3 -m venv .venv && . .venv/bin/activate && pip install -e .
trialgauntlet doctor --base-url http://127.0.0.1:8080/v1
trialgauntlet run --agent llm --base-url http://127.0.0.1:8080/v1 --model qwen3-coder --env all \
  --limit 5 --n 4 --k 2 --temperature 0.7 --run-dir runs/smoke --out runs/smoke/result.json     # smoke test
echo '{"top_k": 20}' > sampling.json
trialgauntlet run --agent llm --base-url http://127.0.0.1:8080/v1 --model qwen3-coder --env all \
  --n 8 --k 4 --temperature 0.7 --top-p 0.8 --extra-body "@sampling.json" \
  --run-dir runs/qwen3-coder --out results/qwen3-coder.json
trialgauntlet report results --out-dir report
```

### Windows (PowerShell)

```powershell
# terminal 1: the model server (CUDA build of llama.cpp unpacked in C:\llama, GGUF in C:\models\qwen3-coder)
C:\llama\llama-server.exe `
  -m C:\models\qwen3-coder\MODEL.gguf `
  --host 127.0.0.1 --port 8080 `
  --ctx-size 32768 `
  --jinja `
  -ngl 99

# terminal 2: the harness
git clone https://github.com/Intermountainh8ter/trialgauntlet
cd trialgauntlet
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
trialgauntlet doctor --base-url http://127.0.0.1:8080/v1
trialgauntlet run --agent llm --base-url http://127.0.0.1:8080/v1 --model qwen3-coder --env all `
  --limit 5 --n 4 --k 2 --temperature 0.7 --run-dir runs\smoke --out runs\smoke\result.json      # smoke test
'{"top_k": 20}' | Out-File -Encoding utf8 sampling.json
trialgauntlet run --agent llm --base-url http://127.0.0.1:8080/v1 --model qwen3-coder --env all `
  --n 8 --k 4 --temperature 0.7 --top-p 0.8 --extra-body "@sampling.json" `
  --run-dir runs\qwen3-coder --out results\qwen3-coder.json
trialgauntlet report results --out-dir report
```

Notes:

* The sampling values are an example; use the settings from your model's card. `--temperature 0` makes all trials
  of a task identical, so pass^k collapses onto pass@1 and the harness cannot show inconsistency: use sampling.
* A full run is about 1,100 trials with several requests each; on a local 30B model expect hours. Runs are resumable:
  if the server dies, restart it and re-run the **same** command (completed trials are kept in `--run-dir`).
* Keep smoke-test output out of `results/`: `trialgauntlet report` treats every file there as a result.
* A run against the built-in `trialgauntlet mock-server` is labelled `MOCK` automatically and `--label REAL` is
  refused. A result file is only called `REAL` when the server did not identify itself as the mock.
* Something wrong? [`docs/FLOWCHARTS.md`](docs/FLOWCHARTS.md) has the symptom-to-fix tree: audit FLAG, pass^k
  collapse, tool calls as text, replay mismatch, budget exceeded, injection attack-success high, connection refused.

## Metrics

pass@1 = `c/n`; pass@k = `1 - C(n-c,k)/C(n,k)`; **pass^k = `C(c,k)/C(n,k)`**, unbiased for `p^k`
(derivation and numeric examples in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)). Suite numbers are means over
tasks with percentile cluster-bootstrap intervals. Also reported per run: outcome-only success, tokens, cost (from
`--price-in/--price-out`), latency, steps, tool-misuse and policy-violation counts, per-tier and
solvable-versus-unsolvable slices.

## Design in five lines

* An `Environment` is a pure function of a task seed: `reset(seed)`, a tool schema, `step(call)`, final-state
  grading. State-changing tools execute even when they violate policy; the violation is *recorded*, and the grader
  fails the trial. Environments measure policy compliance, they do not enforce it.
* A trial is seeded, budgeted (steps, tokens, time) and recorded as JSONL; `replay` re-runs the recorded calls and
  requires identical observations, final-state digest and grade.
* Wrappers (`+naive`, `+inject=...`, `+fault=...`) compose by name in the environment spec.
* Result files are plain JSON ([schema notes](docs/METHODOLOGY.md#10-result-files-and-the-leaderboard)); reports and
  the leaderboard are rendered from them only.
* Core uses only the standard library. numpy is not used anywhere (the bootstrap is plain `random`).

## Repository map

```
src/trialgauntlet/   core (runner, metrics, trajectories), envs/ (fleet, ledger, config, wrappers),
                     agents/ (baselines, scripted agents, LLM adapter), audit, report, mock server, cli
tests/               unit tests, property tests of the estimators, per-environment semantics, mock-server tests
results/             committed result files of the non-LLM agents (regenerate: scripts/regenerate_results.sh)
docs/                METHODOLOGY, ENVIRONMENTS, SUITES, THREATS_TO_VALIDITY, FLOWCHARTS, launch copy
```

Contributing (including the required audit for a new environment): [`CONTRIBUTING.md`](CONTRIBUTING.md).
Changes: [`CHANGELOG.md`](CHANGELOG.md). License: MIT.
