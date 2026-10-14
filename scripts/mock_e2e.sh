#!/usr/bin/env bash
# End-to-end plumbing check: start the scripted MOCK server, run the LLM agent through real HTTP, render
# the report. Everything it produces is labelled MOCK and says nothing about any model.
set -euo pipefail
cd "$(dirname "$0")/.."
TG="${TRIALGAUNTLET:-trialgauntlet}"
PORT="${PORT:-18089}"
OUT="${OUT:-$(mktemp -d)}"
"$TG" mock-server --mode flaky --flaky 0.05 --port "$PORT" >"$OUT/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do
  "$TG" doctor --base-url "http://127.0.0.1:$PORT/v1" >/dev/null 2>&1 && break
  sleep 0.2
done
"$TG" doctor --base-url "http://127.0.0.1:$PORT/v1"
"$TG" run --agent llm --base-url "http://127.0.0.1:$PORT/v1" --model example-model --env all --n 4 --k 2 \
  --limit 8 --temperature 0.7 --quiet --run-dir "$OUT/runs" --out "$OUT/results/mock-run.json"
"$TG" replay "$OUT/runs"
"$TG" report "$OUT/results" --out-dir "$OUT/report"
echo "MOCK end-to-end run complete; outputs in $OUT"
