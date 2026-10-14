# Contributing

The bar for this repository is unusual: **an environment is not accepted until it passes the
degenerate-success audit.** Features come second.

## Setup

```
python -m venv .venv && . .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
make check                                             # ruff + tests with coverage + generated-docs check
```

Rules for all code: standard library only at runtime, syntax valid on Python 3.10 (no `match` on
3.11-only features, no `typing.Self`, no `datetime.UTC`), no network in tests, no placeholders or TODOs,
every behaviour covered by a test, `ruff check .` clean, coverage on `src` at or above 90%.

## Adding an environment

1. **Subclass `BaseEnv`** (`src/trialgauntlet/envs/base.py`) in `src/trialgauntlet/envs/<name>.py` and
   implement `_make_specs`, `_domain_tools` (one `_t_<tool>` method per tool), `_build`, `_world_state`,
   `_check_solved`, `_expected_escalation`, `_policy_text`, and `attack_surface` (so the injection suite
   works). Rules the base class and the tests enforce:
   * a pure function of the task seed (use `rng_for(name, seed)`, never `random` or the clock);
   * at least 40 tasks, three tiers (`T1`..`T3`) with at least 8 solvable tasks each, and an
     unsolvable or ambiguous subset of at least three kinds, named `esc_*`, whose correct behaviour is
     `escalate(category, entity_id)`;
   * every solvable task must **need a state change and an explicit `finish`** (a test checks that the
     initial state does not satisfy the grader);
   * a refusal counts only with the right category **and** the identifier of the blocking entity;
   * policy is *recorded, not enforced*: a violating call executes and appends a code with `_violate`;
   * every state-changing tool must be safe to retry (the base class ignores an exact consecutive repeat);
   * scripted users are deterministic keyword rules; no LLM user, no LLM judge.
2. **Write the scripted oracle** (`ScriptedAgent` generator) that solves every solvable task and escalates
   every unsolvable one *using only tools and observations*, and a **greedy-unsafe** agent that takes the
   literal shortcut and skips the policy. Register both with the environment in
   `envs/__init__.py::_register_builtin`.
3. **Document it** in `docs/ENVIRONMENTS.md`: a table row per scenario kind with tier and expectation (a
   test fails if a kind is missing or mislabelled).
4. **Run the required audit and read it:**
   ```
   trialgauntlet audit --env <name>
   ```
   It must print `AUDIT PASSED`: no-op, random-tool and always-refuse at or below 5% pass@1, the oracle at
   100%, greedy-unsafe at or below 5%. Also run `trialgauntlet audit --env <name>` with the naive grader
   (`<name>+naive`, shown automatically) and look at it: if the naive variant does not light up, your
   escalation scoring is probably not distinguishing refusal from doing nothing.
   **If a trivial baseline scores above the threshold, fix the environment or the grader; do not raise
   the threshold.** If you cannot eliminate it, say so in the pull request and in `docs/THREATS_TO_VALIDITY.md`.
5. **Regenerate the committed outputs**: `scripts/regenerate_results.sh` then
   `python -m trialgauntlet.docgen` (updates the README and `docs/SUITES.md` tables). CI fails if either is
   stale, and `tests/test_docgen.py` checks that the committed result files are what the code produces.
6. Add tests next to the existing ones (`tests/test_<name>.py`): semantic tests for each violation code,
   and add the name to the parametrised lists in `tests/test_envs_common.py`.

## Adding an agent baseline

Put it in `agents/`, register it in `agents/registry.py`, and add tests. A baseline that is meant to be
*trivial* must not read the environment beyond what a stalling, random or refusing agent would see; if it
scores above the threshold on any environment that is a finding to report, not something to tune away.

## Changing a grader, a policy or a metric

Treat it like a change to a published benchmark: bump `version` on the environment, regenerate every
result file, and say in `CHANGELOG.md` which numbers moved and why.

## Pull request checklist

- [ ] `make check` passes
- [ ] `trialgauntlet audit` prints `AUDIT PASSED` on every environment, including the new one
- [ ] result files and README tables regenerated, no hand-edited numbers
- [ ] new behaviour documented (`docs/`), `CHANGELOG.md` updated
- [ ] no claim about real LLM results unless a non-mock `results/*.json` for that model is included
