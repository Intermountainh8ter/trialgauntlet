#!/usr/bin/env bash
# Regenerate every result file that is produced by non-LLM agents. Deterministic: running this twice
# produces byte-identical files. No network, no API key, a few seconds.
set -euo pipefail
cd "$(dirname "$0")/.."
TG="${TRIALGAUNTLET:-trialgauntlet}"

# 1. degenerate-success audit (five baseline agents, all environments, plus the naive-grader demo)
"$TG" audit --out-dir results --format markdown

# 2. injection suite: a well-behaved agent versus an agent that obeys instructions found in tool results
for agent in oracle gullible; do
  "$TG" run --agent "$agent" --env all --inject all --n 2 --k 2 --out "results/suite-injection-$agent.json" > /dev/null
done

# 3. fault suite: the same scripted agent without and with retries, mixed faults at 30%
for agent in oracle oracle-retry; do
  "$TG" run --agent "$agent" --env all --fault mixed:0.3 --n 8 --k 4 --out "results/suite-faults-$agent.json" > /dev/null
done
echo "result files written to results/"
