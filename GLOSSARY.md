# Glossary

Every abbreviation and piece of jargon used in this repository, in plain words.

## Terms specific to this harness

**agent** — An AI model given tools and a goal, allowed to act over several
turns rather than answering once.

**degenerate success** — Reaching the right outcome the wrong way: by luck, by
brute force, or by breaking a rule the task said not to break. The central thing
this harness is built to detect.

**environment** — One simulated workplace the agent acts in. This repo ships
`fleet` (servers), `ledger` (accounts) and `config` (settings).

**episode / trajectory** — One complete attempt at one task, including every
tool call and result along the way.

**greedy-unsafe** — A deliberately reckless scripted agent that takes every
shortcut. It exists to prove the scoring catches cheating. If it scores well,
the scoring is broken.

**gullible-oracle** — A scripted agent that obeys any instruction it reads,
including injected ones. Used to prove the injection tests actually bite.

**k** — The number of independent attempts at the same task.

**pass@k** — "Did at least one of k attempts succeed?" The generous question,
and the one most AI scorecards ask. It rises as you allow more attempts.

**pass^k** — "Did *all* k attempts succeed?" The strict question, borrowed from
the tau-bench benchmark. It measures reliability rather than best-case ability.
A system can have a high pass@k and a near-zero pass^k, which means it works
sometimes and you cannot tell when.

**policy grader** — The scorer that checks whether the agent obeyed the rules,
separately from whether it got the right answer.

**scripted oracle** — A hand-written agent that solves tasks correctly through
the public tool interface. It proves every task is actually solvable, so a low
score means the agent failed rather than the task being impossible.

**seed** — A fixed starting number that makes random generation repeatable.

**suite** — A named group of task variants, e.g. `faults`, `injection`.

**task seed** — One specific generated task instance.

## Scoring and statistics

**CI — confidence interval** — A range of plausible values for a measurement.
Shown here as e.g. `0.0-14.3%`.

**FLAG** — A warning the harness raises about *itself*: a result that suggests
the scorer, not the agent, is at fault.

**MTTR — Mean Time To Recovery** — Average time to fix a fault (see `fleetgate`).

**n** — The number of items measured.

**rate** — A proportion, usually shown as a percentage.

## Machine learning

**AI / LLM — Large Language Model** — The kind of AI that predicts text.

**API — Application Programming Interface** — The network interface used to send
prompts to a model.

**base URL** — The address of the model server the harness talks to.

**GGUF** — The file format used by llama.cpp to store a quantised model.

**prompt injection** — An attack where instructions are hidden in data the agent
reads, hoping it obeys them as if they came from its user.

**quantisation** — Storing a model's numbers at lower precision to save memory.

**temperature / top-p / top-k** — Settings controlling how randomly a model
picks its next word.

**token** — The chunk of text a model reads and writes.

**tool call** — The model asking the system to run a function, in a structured
format, rather than replying in prose.

## Files, formats and systems

**CI — Continuous Integration** — The automated checks that run on every change.
Note the collision with *confidence interval* above; context distinguishes them.

**CLI — Command-Line Interface** — The terminal commands this tool provides.

**CUDA** — NVIDIA's GPU programming system.

**JSON / JSONL** — Structured record format; and one JSON record per line.

**MIT** — The permissive open-source licence this repo uses.

**MOCK** — A run using a fake model, to test the plumbing. Mock output is
labelled and must never be reported as a result.

**NOT YET RUN** — The marker this repo puts on any headline number that has not
actually been measured. It is deliberate: an unmeasured number is left blank
rather than estimated.

**README** — The repository's front page.

**SVG** — A vector image format, used for the diagrams in `docs/diagrams/`.
