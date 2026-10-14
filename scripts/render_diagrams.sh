#!/usr/bin/env bash
# Re-render docs/diagrams/*.mmd to SVG. Requires node >= 18; Chromium is fetched by puppeteer
# unless PUPPETEER_EXECUTABLE_PATH points at an existing browser.
set -euo pipefail
cd "$(dirname "$0")/.."
cfg=$(mktemp)
printf '{"args":["--no-sandbox","--disable-gpu"]%s}\n' \
  "${PUPPETEER_EXECUTABLE_PATH:+,\"executablePath\":\"$PUPPETEER_EXECUTABLE_PATH\"}" > "$cfg"
for f in docs/diagrams/*.mmd; do
  npx --yes @mermaid-js/mermaid-cli -p "$cfg" -c docs/diagrams/mermaid.json -i "$f" -o "${f%.mmd}.svg" -b transparent
done
rm -f "$cfg"
