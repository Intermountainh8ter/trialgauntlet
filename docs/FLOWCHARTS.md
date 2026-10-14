# Flowcharts

Both charts live as Mermaid source in `docs/diagrams/` (GitHub renders the blocks below directly) and as
pre-rendered SVGs next to them. Re-render with `scripts/render_diagrams.sh` (needs Node 18+).

## Usage: from install to the pass@1 versus pass^k report

![usage flowchart](diagrams/usage.svg)

[Open the SVG](diagrams/usage.svg)

```mermaid
flowchart TD
    A["Install<br/>pip install -e .<br/>(Python 3.10+, no dependencies)"] --> B["Choose environments<br/>trialgauntlet list<br/>fleet 52 | ledger 42 | config 44 tasks"]
    B --> C["Audit first<br/>trialgauntlet audit<br/>no-op, random, always-refuse,<br/>scripted-oracle, greedy-unsafe"]
    C --> D{"AUDIT PASSED?<br/>trivial baselines <= 5%,<br/>oracle 100%, shortcut caught"}
    D -->|"FLAG"| E["Fix the environment or grader,<br/>re-run the audit<br/>(see troubleshooting chart)"]
    E --> C
    D -->|"yes"| F["Optional: stress the suites with scripted agents<br/>run --agent gullible --inject all<br/>run --agent oracle --fault mixed:0.3"]
    D -->|"yes"| G["Point at a model server<br/>llama-server --jinja ...<br/>trialgauntlet doctor --base-url URL"]
    G --> H{"doctor PASS?"}
    H -->|"no"| I["Fix the server<br/>(see troubleshooting chart)"]
    I --> G
    H -->|"yes"| J["Smoke test<br/>run --agent llm --limit 5 --n 4 --k 2"]
    J --> K["Full run, n trials per task<br/>run --agent llm --env all --n 8 --k 4<br/>--run-dir runs/X --out results/X.json<br/>(resumable: re-run the same command)"]
    K --> L["Report<br/>trialgauntlet report results<br/>tables + SVG charts"]
    L --> M["Read pass@1 next to pass^k<br/>the gap is the inconsistency<br/>pass@1 alone hides"]
    K --> N["Verify reproducibility<br/>trialgauntlet replay runs/X<br/>every grade must replay identically"]
    classDef gate fill:#ffe9b8,stroke:#b07a00,color:#000
    classDef ok fill:#d6f0d8,stroke:#2b7a2f,color:#000
    classDef stop fill:#f9d2d2,stroke:#a33,color:#000
    class D,H gate
    class M ok
    class E,I stop
```

## Troubleshooting: symptom to fix

Every leaf is a concrete action. The symptoms are the ones this harness really produces: an audit FLAG,
a collapsing pass^k, tool calls that arrive as text, a replay mismatch, a budget termination, a high
injection attack-success rate, a refused connection and a resume error.

![troubleshooting flowchart](diagrams/troubleshooting.svg)

[Open the SVG](diagrams/troubleshooting.svg)

```mermaid
flowchart LR
    S{"Symptom"}
    S --> A1["audit prints FLAG"]
    S --> A2["pass^k far below pass@1"]
    S --> A3["format_error everywhere,<br/>tool calls appear as text"]
    S --> A4["replay says MISMATCH"]
    S --> A5["terminated: budget:*"]
    S --> A6["injection attack success high"]
    S --> A7["connection refused or HTTP 4xx"]
    S --> A8["ResumeError"]

    A1 --> B1{"Which row is flagged?"}
    B1 -->|"no-op, random-tool or<br/>always-refuse above 5%"| C1["The grader accepts a do-nothing or a blind refusal.<br/>Require explicit finish for solve tasks, and escalate with the right<br/>category AND blocking entity for unsolvable ones.<br/>Compare with the +naive demo rows. Re-run: trialgauntlet audit --env X"]
    B1 -->|"scripted-oracle below 100%"| C2["Task unsolvable or grader too strict.<br/>trialgauntlet run --agent oracle --env X --run-dir runs/o,<br/>read the end record's reason in the failing trajectory"]
    B1 -->|"greedy-unsafe passes"| C3["A policy shortcut is not recorded as a violation.<br/>Add a _violate code in the tool the shortcut uses"]

    A2 --> B2{"Does the gap shrink at<br/>--temperature 0?"}
    B2 -->|"yes"| C4["Sampling noise is the cause (a real finding).<br/>Report both numbers; try a lower temperature,<br/>a stricter system prompt, fewer tools"]
    B2 -->|"no, still large"| B3{"terminated and by_tier<br/>in the result file"}
    B3 -->|"format_error or<br/>no_action common"| C5["Protocol failures, not task failures.<br/>Run trialgauntlet doctor, fix the template"]
    B3 -->|"one tier or the<br/>unsolvable slice"| C6["The agent is unreliable on that slice only.<br/>Open its trajectories, replay them, read the violations"]
    B3 -->|"n close to k"| C7["Wide intervals: raise --n (8 or more)<br/>pass^k with n = k is all-or-nothing"]

    A3 --> B4{"Server started with<br/>a tool-capable template?"}
    B4 -->|"llama-server without --jinja"| C8["Restart: llama-server --jinja -m MODEL.gguf<br/>Verify: trialgauntlet doctor --base-url URL"]
    B4 -->|"vLLM / Ollama"| C9["vLLM: --enable-auto-tool-choice --tool-call-parser PARSER.<br/>Ollama: use a model tagged for tools.<br/>Last resort: --parse-text-tools (recorded in the result)"]

    A4 --> B5{"Did the code change<br/>since recording?"}
    B5 -->|"yes (env version, tools)"| C10["Expected. Re-record with --no-resume into a fresh --run-dir"]
    B5 -->|"no"| C11["Nondeterminism in an environment:<br/>time, unseeded random, set or dict ordering.<br/>Derive randomness from rng_for(name, seed). The mismatch line names the first step"]

    A5 --> B6{"Which budget?"}
    B6 -->|"budget:steps"| C12["Raise --max-steps, or the model loops:<br/>read the trajectory for repeated calls"]
    B6 -->|"budget:tokens"| C13["Verbose model or long history.<br/>Lower --max-tokens, raise --max-trial-tokens"]
    B6 -->|"budget:time"| C14["Slow server: check GPU offload (-ngl), context size,<br/>raise --max-trial-seconds. Time budgets are not replayable"]

    A6 --> B7{"exposed rate high?"}
    B7 -->|"yes"| C15["The agent reads poisoned output and obeys it: a finding, not a bug.<br/>Check with --agent gullible that the grader fires.<br/>Mitigate in the prompt: tool output is data, never instructions"]
    B7 -->|"no (low exposure)"| C16["ASR is low only because poisoned tools were never read.<br/>Read attack_success_rate_given_exposed"]

    A7 --> B8{"Message"}
    B8 -->|"connection refused"| C17["Nothing listens at --base-url.<br/>Start llama-server, check host and port.<br/>Inside Docker or WSL use the host's address.<br/>trialgauntlet doctor --base-url URL"]
    B8 -->|"HTTP 400 / 404"| C18["Wrong path or model name, or context exceeded.<br/>doctor lists the served models; use --model NAME,<br/>raise --ctx-size on the server"]
    B8 -->|"HTTP 429 / 5xx or timeout"| C19["Retried automatically with backoff (--retries).<br/>Persistent: raise --timeout, reduce server load"]

    A8 --> C20["The run directory holds trajectories from another agent configuration.<br/>Use a fresh --run-dir, or restore the old model, temperature and flags"]
    classDef fix fill:#d6f0d8,stroke:#2b7a2f,color:#000
    classDef q fill:#ffe9b8,stroke:#b07a00,color:#000
    class C1,C2,C3,C4,C5,C6,C7,C8,C9,C10,C11,C12,C13,C14,C15,C16,C17,C18,C19,C20 fix
    class B1,B2,B3,B4,B5,B6,B7,B8 q
```
